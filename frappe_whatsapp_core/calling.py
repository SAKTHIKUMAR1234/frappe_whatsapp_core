"""Site-scoped Core facade for the complete WhatsApp Calling surface."""

import base64
import mimetypes
from pathlib import Path

import frappe

from frappe_whatsapp_core.meta_flows import _accounts, _call, _resolve_account_name
from frappe_whatsapp_core.permissions import require_core_access


@frappe.whitelist()
@require_core_access(manage=True)
def calling_workspace(account_name=None, include_sip_credentials=0):
	selected = _resolve_account_name(account_name)
	settings = _call("calling", "get_call_settings", {
		"account_name": selected, "include_sip_credentials": include_sip_credentials,
	})
	calls = frappe.get_all(
		"WhatsApp Core Call",
		fields=[
			"name", "call_id", "channel", "direction", "status", "remote_number",
			"remote_user_id", "remote_username", "started_at", "ended_at",
			"cta_payload", "deeplink_payload", "recording_media_id",
			"recording_mime_type", "transcript_media_id", "transcript_mime_type", "modified",
		],
		order_by="modified desc", limit_page_length=100,
	)
	return {"accounts": _accounts(), "selected_account": selected, "settings": settings, "calls": calls}


@frappe.whitelist()
@require_core_access(manage=True)
def update_call_settings(account_name, calling):
	return _call("calling", "update_call_settings", {
		"account_name": _resolve_account_name(account_name), "calling": calling,
	})


@frappe.whitelist()
@require_core_access(manage=True)
def get_call_permission(account_name, user_wa_id=None, recipient=None):
	return _call("calling", "get_call_permission", {
		"account_name": _resolve_account_name(account_name), "user_wa_id": user_wa_id, "recipient": recipient,
	})


@frappe.whitelist()
@require_core_access(manage=True)
def request_call_permission(account_name, body_text, to_number=None, recipient=None, idempotency_key=None):
	return _call("calling", "request_call_permission", {
		"account_name": _resolve_account_name(account_name), "body_text": body_text,
		"to_number": to_number, "recipient": recipient, "idempotency_key": idempotency_key,
	})


@frappe.whitelist()
@require_core_access(manage=True)
def send_call_button(
	account_name,
	body_text,
	to_number=None,
	recipient=None,
	display_text="Call Now",
	ttl_minutes=10080,
	payload=None,
	idempotency_key=None,
):
	return _call("calling", "send_call_button", {
		"account_name": _resolve_account_name(account_name),
		"body_text": body_text,
		"to_number": to_number,
		"recipient": recipient,
		"display_text": display_text,
		"ttl_minutes": ttl_minutes,
		"payload": payload,
		"idempotency_key": idempotency_key,
	})


@frappe.whitelist()
@require_core_access(manage=True)
def send_call_button_template(
	account_name,
	template_name,
	language_code="en",
	to_number=None,
	recipient=None,
	ttl_minutes=None,
	payload=None,
	idempotency_key=None,
):
	return _call("calling", "send_call_button_template", {
		"account_name": _resolve_account_name(account_name),
		"template_name": template_name,
		"language_code": language_code,
		"to_number": to_number,
		"recipient": recipient,
		"ttl_minutes": ttl_minutes,
		"payload": payload,
		"idempotency_key": idempotency_key,
	})


@frappe.whitelist()
@require_core_access(manage=True)
def build_call_deep_link(account_name, biz_payload=None):
	return _call("calling", "build_call_deep_link", {
		"account_name": _resolve_account_name(account_name),
		"biz_payload": biz_payload,
	})


@frappe.whitelist()
@require_core_access(manage=True)
def upload_voicemail_announcement(account_name, file_url, description=None):
	file_name = frappe.db.get_value("File", {"file_url": file_url}, "name")
	if not file_name:
		frappe.throw("Uploaded file not found", frappe.DoesNotExistError)
	file_doc = frappe.get_doc("File", file_name)
	frappe.has_permission("File", "read", doc=file_doc, throw=True)
	content = file_doc.get_content()
	if isinstance(content, str):
		content = content.encode()
	content_type = mimetypes.guess_type(file_doc.file_name or "")[0] or "application/octet-stream"
	if content_type != "audio/ogg":
		frappe.throw("Voicemail announcement must be an OPUS OGG file", frappe.ValidationError)
	return _call("media", "upload_media", {
		"account_name": _resolve_account_name(account_name),
		"file_content_b64": base64.b64encode(content).decode(),
		"content_type": "audio/ogg; codecs=opus",
		"filename": file_doc.file_name or "announcement.ogg",
		"use_case": "call_voicemail_announcement",
		"description": description,
	})


@frappe.whitelist()
@require_core_access(manage=True)
def get_call_artifact(account_name, media_id, download=0):
	method = "download_media" if int(download or 0) else "get_media_url"
	result = _call("media", method, {
		"account_name": _resolve_account_name(account_name),
		"media_id": media_id,
	})
	if not int(download or 0) or not result.get("success"):
		return result
	content = result.get("content_b64")
	if not content:
		frappe.throw("Integration returned an empty call artifact", frappe.ValidationError)
	call = frappe.db.get_value(
		"WhatsApp Core Call",
		{"recording_media_id": media_id},
		["name", "call_id"],
		as_dict=True,
	)
	kind = "recording"
	if not call:
		call = frappe.db.get_value(
			"WhatsApp Core Call",
			{"transcript_media_id": media_id},
			["name", "call_id"],
			as_dict=True,
		)
		kind = "transcript"
	if not call:
		frappe.throw("Call artifact is not linked to a Core call", frappe.DoesNotExistError)
	mime_type = str(result.get("mime_type") or "application/octet-stream").split(";", 1)[0]
	extension = mimetypes.guess_extension(mime_type) or (".ogg" if kind == "recording" else ".json")
	filename = f"whatsapp-call-{call.call_id}-{kind}{Path(extension).suffix}"
	from frappe.utils.file_manager import save_file

	file_doc = save_file(
		filename,
		base64.b64decode(content, validate=True),
		"WhatsApp Core Call",
		call.name,
		is_private=1,
	)
	frappe.db.set_value(
		"WhatsApp Core Call",
		call.name,
		f"{kind}_url",
		file_doc.file_url,
		update_modified=False,
	)
	return {
		"success": True,
		"file_url": file_doc.file_url,
		"mime_type": mime_type,
		"media_id": media_id,
	}


@frappe.whitelist()
@require_core_access(manage=True)
def call_action(
	account_name,
	action,
	call_id=None,
	to_number=None,
	recipient=None,
	sdp_type=None,
	sdp=None,
	biz_opaque_callback_data=None,
	recording=None,
	transcription=None,
):
	return _call("calling", "call_action", {
		"account_name": _resolve_account_name(account_name), "action": action,
		"call_id": call_id, "to_number": to_number, "recipient": recipient,
		"sdp_type": sdp_type, "sdp": sdp,
		"biz_opaque_callback_data": biz_opaque_callback_data,
		"recording": recording,
		"transcription": transcription,
	})
