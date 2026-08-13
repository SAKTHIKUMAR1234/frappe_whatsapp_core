"""Durable Core-owned storage for WhatsApp message media.

The Integration app is only the authenticated Meta mediator.  Bytes are saved
as a private Frappe ``File`` on the Core site as soon as an inbound event is
projected.  Keeping the normal File lifecycle is deliberate: sites with the S3
integration installed can move and serve the same document without WhatsApp
Core knowing anything about bucket credentials.
"""

from __future__ import annotations

import base64
import binascii
import json
import mimetypes
from pathlib import Path
from urllib.parse import quote

import frappe
from frappe.utils import cint
from frappe.utils.file_manager import save_file

from frappe_whatsapp_core.hub_client import call_management, get_settings
from frappe_whatsapp_core.permissions import require_core_access

MEDIA_MESSAGE_TYPES = {"audio", "document", "image", "sticker", "template", "video"}
MEDIA_METHOD = "frappe_whatsapp_core.message_media.download_message_media"
HUB_DOWNLOAD_METHOD = (
	"frappe_whatsapp_integration.frappe_whatsapp_hub.api.media.download_media"
)


def add_media_url(message) -> None:
	"""Add a same-origin media URL without resolving Meta media during list reads."""
	descriptor = media_descriptor(message.get("message_type"), message.get("content"))
	if not descriptor.get("id"):
		return
	message["media_url"] = (
		f"/api/method/{MEDIA_METHOD}?message={quote(str(message.get('name') or ''))}"
	)


def media_descriptor(message_type: str | None, content) -> dict:
	message_type = str(message_type or "").lower()
	if message_type not in MEDIA_MESSAGE_TYPES:
		return {}
	parsed = _json_dict(content)
	payload = parsed.get("payload")
	if isinstance(payload, dict):
		candidate = payload
	else:
		candidate = parsed.get(message_type)
	if not isinstance(candidate, dict):
		return {}
	media_id = str(candidate.get("id") or "").strip()
	if not media_id:
		return {}
	return {
		"id": media_id,
		"filename": str(candidate.get("filename") or "").strip(),
		"mime_type": str(candidate.get("mime_type") or "").strip(),
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
			frappe.log_error(
				title=f"WhatsApp media cache failed: {message_name}",
				message=frappe.get_traceback(),
			)
	return {"stored": stored, "failed": failed}


def cache_message_media(message: str):
	"""Return the private local File, downloading it through Integration once."""
	message = str(message or "").strip()
	if not message or not frappe.db.exists("WhatsApp Core Message", message):
		frappe.throw("Message not found", frappe.DoesNotExistError)
	with frappe.cache.lock(
		f"whatsapp_core_media:{message}", timeout=90, blocking_timeout=10
	):
		cached = _cached_file(message)
		if cached:
			return cached
		doc = frappe.get_doc("WhatsApp Core Message", message)
		descriptor = media_descriptor(doc.message_type, doc.content)
		if not descriptor:
			frappe.throw(
				"This message does not contain downloadable media",
				frappe.ValidationError,
			)
		settings = get_settings()
		result = call_management(
			HUB_DOWNLOAD_METHOD,
			{
				"account_name": settings.get_account_name(doc.channel),
				"media_id": descriptor["id"],
			},
		)
		if not result.get("success") or not result.get("content_b64"):
			frappe.throw(result.get("error") or "Meta media download failed")
		try:
			content = base64.b64decode(result["content_b64"], validate=True)
		except (binascii.Error, TypeError, ValueError):
			frappe.throw(
				"WhatsApp Hub returned invalid media content",
				frappe.ValidationError,
			)
		content_type = str(
			result.get("mime_type") or descriptor.get("mime_type") or ""
		).strip()
		filename = _filename(message, {**descriptor, "mime_type": content_type})
		return save_file(
			filename,
			content,
			"WhatsApp Core Message",
			message,
			is_private=1,
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
