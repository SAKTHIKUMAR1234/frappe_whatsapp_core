"""Durable Core-owned storage for WhatsApp message media.

The Integration app is only the authenticated Meta mediator.  Bytes are saved
as a private Frappe ``File`` on the Core site as soon as an inbound event is
projected.  Keeping the normal File lifecycle is deliberate: sites with the S3
integration installed can move and serve the same document without WhatsApp
Core knowing anything about bucket credentials.
"""

from __future__ import annotations

import json
import mimetypes
from pathlib import Path
from urllib.parse import quote

import frappe
from frappe.utils import add_days, cint, now_datetime
from frappe.utils.file_manager import save_file

from frappe_whatsapp_core.hub_client import download_media, get_settings
from frappe_whatsapp_core.permissions import require_core_access

MEDIA_MESSAGE_TYPES = {"audio", "document", "image", "sticker", "template", "video"}
MEDIA_METHOD = "frappe_whatsapp_core.message_media.download_message_media"


def add_media_url(message) -> None:
	"""Add a same-origin media URL without resolving Meta media during list reads."""
	descriptor = media_descriptor(message.get("message_type"), message.get("content"))
	if not descriptor:
		return
	message["media_url"] = f"/api/method/{MEDIA_METHOD}?message={quote(str(message.get('name') or ''))}"


def media_descriptor(message_type: str | None, content) -> dict:
	message_type = str(message_type or "").lower()
	if message_type not in MEDIA_MESSAGE_TYPES:
		return {}
	parsed = _json_dict(content)
	if message_type == "template":
		return _template_media_descriptor(parsed)
	payload = parsed.get("payload")
	if isinstance(payload, dict):
		candidate = payload
	else:
		candidate = parsed.get(message_type)
	if not isinstance(candidate, dict):
		return {}
	media_id = str(candidate.get("id") or "").strip()
	local_file_url = _safe_local_file_url(candidate.get("local_file_url"))
	if not media_id and not local_file_url:
		return {}
	return {
		"id": media_id,
		"local_file_url": local_file_url,
		"filename": str(candidate.get("filename") or "").strip(),
		"mime_type": str(candidate.get("mime_type") or "").strip(),
	}


def _template_media_descriptor(content: dict) -> dict:
	snapshot = content.get("template_snapshot")
	if not isinstance(snapshot, dict):
		snapshot = {}
	header_type = str(snapshot.get("header_type") or "").strip().upper()
	local_file_url = _safe_local_file_url(snapshot.get("header_media"))
	media_id = ""
	filename = ""
	for component in content.get("components") or []:
		if not isinstance(component, dict) or str(component.get("type") or "").lower() != "header":
			continue
		for parameter in component.get("parameters") or []:
			if not isinstance(parameter, dict):
				continue
			parameter_type = str(parameter.get("type") or "").lower()
			if parameter_type not in {"document", "image", "video"}:
				continue
			value = parameter.get(parameter_type)
			if not isinstance(value, dict):
				continue
			media_id = str(value.get("id") or "").strip()
			local_file_url = local_file_url or _safe_local_file_url(value.get("link"))
			filename = str(value.get("filename") or "").strip()
			header_type = header_type or parameter_type.upper()
			break
		if media_id or local_file_url:
			break
	if not media_id and not local_file_url:
		return {}
	return {
		"id": media_id,
		"local_file_url": local_file_url,
		"filename": filename,
		"mime_type": {
			"DOCUMENT": "application/octet-stream",
			"IMAGE": "image/jpeg",
			"VIDEO": "video/mp4",
		}.get(header_type, ""),
	}


@frappe.whitelist()
@require_core_access()
def download_message_media(message: str, download: int | str = 0):
	"""Stream message media through Core and cache it as a private attached File."""
	message = str(message or "").strip()
	if not message or not frappe.db.exists("WhatsApp Core Message", message):
		frappe.throw("Message not found", frappe.DoesNotExistError)
	doc = frappe.get_doc("WhatsApp Core Message", message)
	from frappe_whatsapp_core.workspace_api import _assert_conversation_access

	_assert_conversation_access(doc.conversation)
	frappe.has_permission("WhatsApp Core Message", "read", doc=doc, throw=True)
	descriptor = media_descriptor(doc.message_type, doc.content)
	if not descriptor:
		frappe.throw("This message does not contain downloadable media", frappe.ValidationError)

	file_doc = cache_message_media(doc.name)
	content = file_doc.get_content()
	filename = file_doc.file_name or _filename(doc.name, descriptor)
	content_type = file_doc.get("content_type") or descriptor.get("mime_type") or ""

	frappe.local.response.filename = filename
	frappe.local.response.filecontent = content
	frappe.local.response.type = "download"
	frappe.local.response.content_type = _content_type(content_type, filename)
	frappe.local.response.display_content_as = (
		"attachment" if cint(download) or doc.message_type == "document" else "inline"
	)


def enqueue_message_media_cache(message_names, *, enqueue_after_commit=True) -> None:
	"""Queue one bounded cache job for newly projected media messages."""
	if isinstance(message_names, str):
		message_names = [message_names]
	message_names = list(dict.fromkeys(str(name) for name in (message_names or []) if name))
	if not message_names:
		return
	for offset in range(0, len(message_names), 100):
		frappe.enqueue(
			"frappe_whatsapp_core.message_media.cache_message_media_batch",
			queue="short",
			enqueue_after_commit=enqueue_after_commit,
			message_names=message_names[offset : offset + 100],
		)


def cache_message_media_batch(message_names) -> dict:
	"""Persist each media item independently so one expired object cannot block a batch."""
	stored = []
	failed = []
	for message_name in list(dict.fromkeys(message_names or []))[:100]:
		try:
			file_doc = cache_message_media(message_name)
			stored.append({"message": message_name, "file": file_doc.name})
		except Exception:
			failed.append(message_name)
			_mark_cache_failure(message_name)
			frappe.log_error(
				title=f"WhatsApp media cache failed: {message_name}",
				message=frappe.get_traceback(),
			)
	return {"stored": stored, "failed": failed}


def queue_uncached_recent_media(limit: int = 100) -> dict:
	"""Retry recent uncached media without repeatedly chasing expired objects."""
	limit = max(1, min(int(limit or 100), 500))
	names = []
	scanned = 0
	page_size = min(max(limit * 2, 100), 500)
	max_scan = min(max(limit * 10, page_size * 2), 5000)
	while len(names) < limit and scanned < max_scan:
		query_limit = min(page_size, max_scan - scanned)
		rows = frappe.db.sql(
			"""
			SELECT message.name, message.message_type, message.content
			FROM `tabWhatsApp Core Message` AS message
			WHERE message.message_type IN ('audio', 'document', 'image', 'sticker', 'template', 'video')
				AND message.creation >= %(cutoff)s
				AND NOT EXISTS (
					SELECT 1 FROM `tabFile` AS media_file
					WHERE media_file.attached_to_doctype = 'WhatsApp Core Message'
						AND media_file.attached_to_name = message.name
						AND media_file.is_private = 1
				)
			ORDER BY message.creation DESC
			LIMIT %(limit)s OFFSET %(offset)s
			""",
			{
				"cutoff": add_days(now_datetime(), -7),
				"limit": query_limit,
				"offset": scanned,
			},
			as_dict=True,
		)
		if not rows:
			break
		scanned += len(rows)
		for row in rows:
			content = _json_dict(row.content)
			state = content.get("_media_cache") if isinstance(content.get("_media_cache"), dict) else {}
			if state.get("status") == "stored":
				continue
			if int(state.get("attempts") or 0) >= 5:
				continue
			if media_descriptor(row.message_type, content):
				names.append(row.name)
				if len(names) >= limit:
					break
		if len(rows) < query_limit:
			break
	if names:
		enqueue_message_media_cache(names, enqueue_after_commit=False)
	return {"queued": len(names), "scanned": scanned}


def cache_message_media(message: str):
	"""Return the private local File, downloading it through Integration once."""
	message = str(message or "").strip()
	if not message or not frappe.db.exists("WhatsApp Core Message", message):
		frappe.throw("Message not found", frappe.DoesNotExistError)
	with frappe.cache.lock(f"whatsapp_core_media:{message}", timeout=90, blocking_timeout=10):
		cached = _cached_file(message)
		if cached:
			_record_local_reference(frappe.get_doc("WhatsApp Core Message", message), cached)
			return cached
		doc = frappe.get_doc("WhatsApp Core Message", message)
		descriptor = media_descriptor(doc.message_type, doc.content)
		if not descriptor:
			frappe.throw(
				"This message does not contain downloadable media",
				frappe.ValidationError,
			)
		local_file = _referenced_local_file(doc, descriptor)
		if local_file:
			_record_local_reference(doc, local_file)
			return local_file
		if not descriptor.get("id"):
			frappe.throw(
				"The archived media file is no longer available on this site",
				frappe.DoesNotExistError,
			)
		settings = get_settings()
		result = download_media(
			settings.get_account_name(doc.channel),
			descriptor["id"],
		)
		if not result.get("success") or not result.get("content"):
			frappe.throw(result.get("error") or "Meta media download failed")
		content = result["content"]
		content_type = str(result.get("mime_type") or descriptor.get("mime_type") or "").strip()
		filename = _filename(message, {**descriptor, "mime_type": content_type})
		file_doc = save_file(
			filename,
			content,
			"WhatsApp Core Message",
			message,
			is_private=1,
		)
		_record_local_reference(doc, file_doc)
		return file_doc


def _record_local_reference(message, file_doc) -> None:
	"""Persist the Core-owned File reference so Meta is never needed again."""
	file_url = _safe_local_file_url(getattr(file_doc, "file_url", ""))
	if not file_url:
		return
	content = _json_dict(message.content)
	message_type = str(message.message_type or "").lower()
	if message_type == "template":
		snapshot = content.get("template_snapshot")
		if not isinstance(snapshot, dict):
			snapshot = {}
		content["template_snapshot"] = snapshot
		snapshot["header_media"] = file_url
	else:
		payload = content.get("payload")
		if isinstance(payload, dict):
			payload["local_file_url"] = file_url
		else:
			candidate = content.get(message_type)
			if not isinstance(candidate, dict):
				candidate = {}
			content[message_type] = candidate
			candidate["local_file_url"] = file_url
	existing_state = content.get("_media_cache") if isinstance(content.get("_media_cache"), dict) else {}
	content["_media_cache"] = (
		existing_state
		if existing_state.get("status") == "stored" and existing_state.get("file") == file_doc.name
		else {
			"status": "stored",
			"file": file_doc.name,
			"stored_at": str(now_datetime()),
		}
	)
	serialized = json.dumps(content, separators=(",", ":"), ensure_ascii=False)
	if serialized != str(message.content or ""):
		frappe.db.set_value(
			"WhatsApp Core Message",
			message.name,
			"content",
			serialized,
			update_modified=False,
		)
		message.content = serialized


def _mark_cache_failure(message: str) -> None:
	row = frappe.db.get_value(
		"WhatsApp Core Message",
		message,
		["name", "content"],
		as_dict=True,
	)
	if not row:
		return
	content = _json_dict(row.content)
	state = content.get("_media_cache") if isinstance(content.get("_media_cache"), dict) else {}
	content["_media_cache"] = {
		"status": "retry_pending",
		"attempts": min(int(state.get("attempts") or 0) + 1, 5),
		"last_attempt_at": str(now_datetime()),
	}
	frappe.db.set_value(
		"WhatsApp Core Message",
		message,
		"content",
		json.dumps(content, separators=(",", ":"), ensure_ascii=False),
		update_modified=False,
	)


def _cached_file(message: str):
	name = frappe.db.get_value(
		"File",
		{
			"attached_to_doctype": "WhatsApp Core Message",
			"attached_to_name": message,
			"is_private": 1,
		},
		"name",
		order_by="creation desc",
	)
	return frappe.get_doc("File", name) if name else None


def _referenced_local_file(message, descriptor: dict):
	"""Resolve a trusted site-local File retained by the legacy migration.

	The media endpoint already enforces conversation access. We additionally
	require the File to be attached to this Core message, or the message to carry
	the migration marker, so arbitrary message JSON cannot expose another local
	File by guessing its URL.
	"""
	file_url = _safe_local_file_url(descriptor.get("local_file_url"))
	if not file_url:
		return None
	content = _json_dict(message.content)
	filters = {"file_url": file_url, "is_folder": 0}
	file_rows = frappe.get_all(
		"File",
		filters=filters,
		fields=["name", "attached_to_doctype", "attached_to_name"],
		order_by="creation desc",
		limit_page_length=1,
	)
	if not file_rows:
		return None
	row = file_rows[0]
	attached_to_message = (
		row.attached_to_doctype == "WhatsApp Core Message" and row.attached_to_name == message.name
	)
	if not attached_to_message and not content.get("legacy_source"):
		return None
	return frappe.get_doc("File", row.name)


def _safe_local_file_url(value) -> str:
	value = str(value or "").strip().split("?", 1)[0].split("#", 1)[0]
	if value.startswith(("/files/", "/private/files/")) and "\\" not in value:
		return value
	return ""


def _filename(message: str, descriptor: dict) -> str:
	provided = Path(str(descriptor.get("filename") or "")).name
	if provided:
		return provided
	extension = mimetypes.guess_extension(str(descriptor.get("mime_type") or "")) or ""
	return f"whatsapp-{message}{extension}"


def _content_type(content_type: str, filename: str) -> str:
	content_type = str(content_type or "").strip().lower()
	if "/" in content_type and "\n" not in content_type and "\r" not in content_type:
		return content_type
	return mimetypes.guess_type(filename)[0] or "application/octet-stream"


def _json_dict(value) -> dict:
	if isinstance(value, dict):
		return value
	if not value:
		return {}
	try:
		parsed = json.loads(value)
		return parsed if isinstance(parsed, dict) else {}
	except (TypeError, ValueError):
		return {}
