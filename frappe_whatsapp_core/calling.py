"""Site-scoped Core facade for the complete WhatsApp Calling surface."""

import mimetypes
from pathlib import Path

import frappe

from frappe_whatsapp_core.hub_client import (
	call_action as relay_call_action,
)
from frappe_whatsapp_core.hub_client import (
	download_media,
	get_media_url,
	send_account_raw,
	upload_media,
)
from frappe_whatsapp_core.hub_client import (
	get_call_permission as relay_get_call_permission,
)
from frappe_whatsapp_core.identity import contact_options, is_business_scoped_user_id
from frappe_whatsapp_core.meta_flows import _accounts, _call, _resolve_account_name, _workspace_failure
from frappe_whatsapp_core.outbound import resolve_recipient_phone
from frappe_whatsapp_core.permissions import require_core_access


def _contact_target(
	identity=None,
	to_number=None,
	recipient=None,
	operation=None,
	account_name=None,
):
	"""Resolve a Core contact at send time while retaining advanced raw targets."""
	if identity:
		channel = frappe.db.get_value(
			"WhatsApp Core Hub Account",
			{"parent": "WhatsApp Core Settings", "account_name": account_name},
			"channel",
		)
		target = resolve_recipient_phone(
				identity,
				context={
					"operation": operation or "whatsapp_calling",
					**({"channel": channel} if channel else {}),
				},
			)
		return (None, target) if is_business_scoped_user_id(target) else (target, None)
	return to_number, recipient


def _set_target(payload, to_number=None, recipient=None):
	if not to_number and not recipient:
		frappe.throw("A phone number or business-scoped recipient is required", frappe.ValidationError)
	if to_number:
		payload["to"] = str(to_number)
	if recipient:
		payload["recipient"] = str(recipient)


def _json_object(value, label):
	if isinstance(value, str):
		value = frappe.parse_json(value)
	if value is not None and not isinstance(value, dict):
		frappe.throw(f"{label} must be an object", frappe.ValidationError)
	return value


def _consent_option(value, label):
	value = _json_object(value, label)
	if value is None:
		return None
	status = str(value.get("status") or "").upper()
	if status not in {"ENABLED", "DISABLED"}:
		frappe.throw(f"{label}.status must be ENABLED or DISABLED", frappe.ValidationError)
	result = {"status": status}
	if status == "ENABLED":
		purpose = str(value.get("purpose") or "").strip()
		language = str(value.get("announcement_language") or "").strip()
		if not purpose or len(purpose) > 250 or not language:
			frappe.throw(f"{label} requires purpose and announcement language", frappe.ValidationError)
		result.update({"purpose": purpose, "announcement_language": language})
	return result


def _calling_settings(value):
	"""Normalize the stable Meta calling controls exposed by Core's UI."""
	value = dict(_json_object(value, "calling") or {})
	status = str(value.get("status") or "").strip().upper()
	if status not in {"ENABLED", "DISABLED"}:
		frappe.throw("calling.status must be ENABLED or DISABLED", frappe.ValidationError)
	value["status"] = status

	visibility = value.get("call_icon_visibility")
	if visibility is None or str(visibility).strip().upper() in {"", "NOT_SET"}:
		value.pop("call_icon_visibility", None)
	else:
		visibility = str(visibility).strip().upper()
		if visibility not in {"DEFAULT", "DISABLE_ALL"}:
			frappe.throw(
				"calling.call_icon_visibility must be DEFAULT or DISABLE_ALL",
				frappe.ValidationError,
			)
		value["call_icon_visibility"] = visibility
	return value


@frappe.whitelist()
@require_core_access(manage=True)
def calling_workspace(account_name=None, include_sip_credentials=0):
	call_fields = [
		"name", "call_id", "channel", "direction", "status", "remote_number",
		"remote_user_id", "remote_username", "started_at", "ended_at",
		"cta_payload", "deeplink_payload", "recording_media_id",
		"recording_mime_type", "transcript_media_id", "transcript_mime_type", "modified",
	]
	meta = frappe.get_meta("WhatsApp Core Call")
	call_fields = [field for field in call_fields if field == "name" or meta.has_field(field)]
	calls = frappe.get_all(
		"WhatsApp Core Call",
		fields=call_fields,
		order_by="modified desc", limit_page_length=100,
	)
	templates = []
	accounts = []
	selected = None
	contacts = contact_options(limit=50)
	try:
		accounts = _accounts()
		selected = _resolve_account_name(account_name)
		channel = next(row["channel"] for row in accounts if row["account_name"] == selected)
		templates = frappe.get_all(
			"WhatsApp Core Template",
			filters={"approval_status": "APPROVED", "enabled": 1, "channel": channel},
			fields=["name", "template_name", "language_code", "body_text"],
			order_by="template_name asc, language_code asc",
			limit_page_length=500,
		)
		settings = _call("calling", "get_call_settings", {
			"account_name": selected, "include_sip_credentials": include_sip_credentials,
		})
		return {
			"configured": True,
			"available": True,
			"error": "",
			"accounts": accounts,
			"selected_account": selected,
			"settings": settings,
			"calls": calls,
			"templates": templates,
			"contacts": contacts,
		}
	except Exception as error:
		return _workspace_failure(
			error,
			accounts=accounts,
			selected_account=selected,
			settings={},
			calls=calls,
			templates=templates,
			contacts=contacts,
		)


@frappe.whitelist()
@require_core_access(manage=True)
def update_call_settings(account_name, calling):
	return _call("calling", "update_call_settings", {
		"account_name": _resolve_account_name(account_name),
		"calling": _calling_settings(calling),
	})


@frappe.whitelist()
@require_core_access(manage=True)
def get_call_permission(account_name, user_wa_id=None, recipient=None, identity=None):
	user_wa_id, recipient = _contact_target(
		identity, user_wa_id, recipient, "get_call_permission", account_name
	)
	return relay_get_call_permission(
		_resolve_account_name(account_name),
		user_wa_id=user_wa_id,
		recipient=recipient,
	)


@frappe.whitelist()
@require_core_access(manage=True)
def request_call_permission(
	account_name,
	body_text,
	to_number=None,
	recipient=None,
	identity=None,
	idempotency_key=None,
):
	to_number, recipient = _contact_target(
		identity, to_number, recipient, "request_call_permission", account_name
	)
	body_text = str(body_text or "").strip()
	if not body_text:
		frappe.throw("body_text is required", frappe.ValidationError)
	payload = {
		"messaging_product": "whatsapp",
		"recipient_type": "individual",
		"type": "interactive",
		"interactive": {
			"type": "call_permission_request",
			"action": {"name": "call_permission_request"},
			"body": {"text": body_text},
		},
	}
	_set_target(payload, to_number, recipient)
	return send_account_raw(
		_resolve_account_name(account_name), payload, idempotency_key,
	)


@frappe.whitelist()
@require_core_access(manage=True)
def send_call_button(
	account_name,
	body_text,
	to_number=None,
	recipient=None,
	identity=None,
	display_text="Call Now",
	ttl_minutes=10080,
	payload=None,
	idempotency_key=None,
):
	to_number, recipient = _contact_target(
		identity, to_number, recipient, "send_call_button", account_name
	)
	body_text = str(body_text or "").strip()
	display_text = str(display_text or "Call Now").strip()
	ttl_minutes = int(ttl_minutes or 10080)
	if not body_text or not 1 <= len(display_text) <= 20:
		frappe.throw("Valid body_text and display_text are required", frappe.ValidationError)
	if not 1 <= ttl_minutes <= 43200:
		frappe.throw("ttl_minutes must be between 1 and 43200", frappe.ValidationError)
	parameters = {"display_text": display_text, "ttl_minutes": ttl_minutes}
	if payload is not None:
		payload = str(payload)
		if len(payload) > 512:
			frappe.throw("payload cannot exceed 512 characters", frappe.ValidationError)
		parameters["payload"] = payload
	message = {
		"messaging_product": "whatsapp",
		"recipient_type": "individual",
		"type": "interactive",
		"interactive": {
			"type": "voice_call",
			"body": {"text": body_text},
			"action": {"name": "voice_call", "parameters": parameters},
		},
	}
	_set_target(message, to_number, recipient)
	return send_account_raw(
		_resolve_account_name(account_name), message, idempotency_key,
	)


@frappe.whitelist()
@require_core_access(manage=True)
def send_call_button_template(
	account_name,
	template_name,
	language_code="en",
	to_number=None,
	recipient=None,
	identity=None,
	ttl_minutes=None,
	payload=None,
	idempotency_key=None,
):
	to_number, recipient = _contact_target(
		identity, to_number, recipient, "send_call_button_template", account_name
	)
	parameters = []
	if ttl_minutes is not None:
		ttl_minutes = int(ttl_minutes)
		if not 1 <= ttl_minutes <= 43200:
			frappe.throw("ttl_minutes must be between 1 and 43200", frappe.ValidationError)
		parameters.append({"type": "ttl_minutes", "ttl_minutes": ttl_minutes})
	if payload is not None:
		payload = str(payload)
		if len(payload) > 512:
			frappe.throw("payload cannot exceed 512 characters", frappe.ValidationError)
		parameters.append({"type": "payload", "payload": payload})
	template_name = str(template_name or "").strip()
	if not template_name:
		frappe.throw("template_name is required", frappe.ValidationError)
	template = {
		"name": template_name,
		"language": {"code": str(language_code or "en").strip()},
	}
	if parameters:
		template["components"] = [{
			"type": "button", "sub_type": "voice_call", "parameters": parameters,
		}]
	message = {
		"messaging_product": "whatsapp",
		"recipient_type": "individual",
		"type": "template",
		"template": template,
	}
	_set_target(message, to_number, recipient)
	return send_account_raw(
		_resolve_account_name(account_name), message, idempotency_key,
	)


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
	return upload_media(
		_resolve_account_name(account_name),
		content,
		content_type="audio/ogg; codecs=opus",
		filename=file_doc.file_name or "announcement.ogg",
		use_case="call_voicemail_announcement",
		description=description,
	)


@frappe.whitelist()
@require_core_access(manage=True)
def get_call_artifact(account_name, media_id, download=0):
	account_name = _resolve_account_name(account_name)
	result = (
		download_media(account_name, media_id)
		if int(download or 0)
		else get_media_url(account_name, media_id)
	)
	if not int(download or 0) or not result.get("success"):
		return result
	content = result.get("content")
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
		content,
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
	identity=None,
	sdp_type=None,
	sdp=None,
	biz_opaque_callback_data=None,
	recording=None,
	transcription=None,
):
	to_number, recipient = _contact_target(
		identity, to_number, recipient, "call_action", account_name
	)
	action = str(action or "").lower()
	if action not in {"connect", "pre_accept", "accept", "reject", "terminate"}:
		frappe.throw("Invalid call action", frappe.ValidationError)
	payload = {"messaging_product": "whatsapp", "action": action}
	if action == "connect":
		_set_target(payload, to_number, recipient)
	else:
		if not call_id:
			frappe.throw("call_id is required", frappe.ValidationError)
		payload["call_id"] = call_id
	if action in {"connect", "pre_accept", "accept"}:
		if sdp_type not in {"offer", "answer"} or not sdp:
			frappe.throw("A valid SDP offer or answer is required", frappe.ValidationError)
		payload["session"] = {"sdp_type": sdp_type, "sdp": sdp}
	if biz_opaque_callback_data:
		payload["biz_opaque_callback_data"] = str(biz_opaque_callback_data)[:512]
	if recording is not None or transcription is not None:
		if action not in {"connect", "accept"}:
			frappe.throw("Recording controls require connect or accept", frappe.ValidationError)
		if recording is not None:
			payload["recording"] = _consent_option(recording, "recording")
		if transcription is not None:
			payload["transcription"] = _consent_option(transcription, "transcription")
	return relay_call_action(_resolve_account_name(account_name), payload)
