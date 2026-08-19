"""Site-scoped Core facade for the complete WhatsApp Calling surface."""

import hashlib
import mimetypes
from pathlib import Path

import frappe
from frappe.utils import cint, now_datetime

from frappe_whatsapp_core.contact_presentation import present_identity_names
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
from frappe_whatsapp_core.materializer import (
	get_or_create_conversation,
	touch_conversation_call_activity,
)
from frappe_whatsapp_core.meta_flows import _accounts, _call, _resolve_account_name, _workspace_failure
from frappe_whatsapp_core.outbound import resolve_recipient_phone
from frappe_whatsapp_core.permissions import (
	CORE_MANAGEMENT_ROLES,
	assert_call_access,
	assert_identity_team_access,
	conversation_conditions,
	require_core_access,
)


DEFAULT_RTC_CONFIGURATION = {
	"bundlePolicy": "max-bundle",
	"rtcpMuxPolicy": "require",
	"iceCandidatePoolSize": 2,
	"iceServers": [{"urls": ["stun:stun.cloudflare.com:3478"]}],
}

CALL_ACTION_SOURCE_STATES = {
	"pre_accept": {"connect", "ringing", "received"},
	"accept": {"connect", "ringing", "received", "pre_accept"},
	"reject": {"connect", "ringing", "received", "pre_accept"},
	"terminate": {
		"connect",
		"ringing",
		"received",
		"pre_accept",
		"accept",
		"accepted",
		"connected",
	},
}
INCOMING_CALL_CLAIM_STATES = {"connect", "ringing", "received"}

CALL_HISTORY_PAGE_SIZE = 30
CALL_HISTORY_MAX_PAGE_SIZE = 100
DEFAULT_CALL_RECORDING = {
	"status": "ENABLED",
	"purpose": "Customer service quality and record keeping",
	"announcement_language": "en_US",
}
MAX_BROWSER_CALL_RECORDING_BYTES = 50 * 1024 * 1024
MIXED_RECORDING_MIME_TYPES = {"audio/webm", "audio/ogg", "audio/mp4"}


def _can_manage():
	return bool(set(frappe.get_roles()) & CORE_MANAGEMENT_ROLES)


def _contact_target(
	identity=None,
	to_number=None,
	recipient=None,
	operation=None,
	account_name=None,
):
	"""Resolve a Core contact at send time while retaining advanced raw targets."""
	if identity:
		assert_identity_team_access(identity)
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
	if not _can_manage():
		frappe.throw("Select a contact within your team scope", frappe.PermissionError)
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


def _call_rows(
	channel=None,
	*,
	conversation=None,
	start=0,
	limit=CALL_HISTORY_PAGE_SIZE,
):
	conditions, values = conversation_conditions("conversation")
	if channel:
		conditions.append("call_log.channel = %(channel)s")
		values["channel"] = channel
	if conversation:
		conditions.append("call_log.conversation = %(conversation)s")
		values["conversation"] = conversation
	values["start"] = max(0, cint(start))
	values["limit"] = min(
		CALL_HISTORY_MAX_PAGE_SIZE + 1,
		max(1, cint(limit) or CALL_HISTORY_PAGE_SIZE),
	)
	rows = frappe.db.sql(
		f"""
		SELECT
			call_log.name, call_log.call_id, call_log.channel, call_log.conversation,
			call_log.remote_identity, call_log.direction, call_log.status,
			call_log.remote_number, call_log.remote_user_id, call_log.remote_username,
			call_log.handled_by,
			call_log.started_at, call_log.ended_at, call_log.cta_payload,
			call_log.deeplink_payload, call_log.recording_media_id,
			call_log.recording_mime_type, call_log.recording_url,
			call_log.mixed_recording_url, call_log.mixed_recording_mime_type,
			call_log.mixed_recording_sha256,
			call_log.transcript_media_id, call_log.transcript_mime_type,
			call_log.transcript_url, call_log.session, call_log.creation,
			call_log.modified
		FROM `tabWhatsApp Core Call` AS call_log
		LEFT JOIN `tabWhatsApp Core Conversation` AS conversation
			ON conversation.name = call_log.conversation
		WHERE {" AND ".join(conditions)}
		ORDER BY
			COALESCE(call_log.ended_at, call_log.started_at, call_log.creation) DESC,
			call_log.name DESC
		LIMIT %(start)s, %(limit)s
		""",
		values,
		as_dict=True,
	)
	presentations = present_identity_names(
		[row.remote_identity for row in rows if row.remote_identity],
		context={"surface": "calling"},
	)
	for row in rows:
		presentation = presentations.get(row.remote_identity) or {}
		row["display_name"] = (
			presentation.get("display_name")
			or row.remote_username
			or row.remote_number
			or "WhatsApp contact"
		)
		row["presentation"] = presentation
		row["timeline_at"] = row.started_at or row.ended_at or row.creation or row.modified
		row["provider_recording_url"] = row.recording_url
		row["recording_url"] = row.mixed_recording_url or row.recording_url
	handlers = {
		str(row.handled_by)
		for row in rows
		if str(row.handled_by or "").strip()
	}
	if handlers:
		profiles = frappe.get_all(
			"User",
			filters={"name": ["in", list(handlers)]},
			fields=["name", "full_name", "first_name"],
			limit_page_length=len(handlers),
		)
		labels = {
			profile.name: profile.full_name or profile.first_name or profile.name
			for profile in profiles
		}
		for row in rows:
			row["handled_by_name"] = labels.get(row.handled_by, row.handled_by or "")
	return rows


@frappe.whitelist()
@require_core_access()
def conversation_call_history(conversation, limit=CALL_HISTORY_MAX_PAGE_SIZE):
	"""Return call cards for one already-authorized Shared Inbox conversation."""
	from frappe_whatsapp_core.permissions import assert_conversation_access

	conversation = str(conversation or "").strip()
	assert_conversation_access(conversation)
	limit = min(CALL_HISTORY_MAX_PAGE_SIZE, max(1, cint(limit) or CALL_HISTORY_MAX_PAGE_SIZE))
	return {"rows": _call_rows(conversation=conversation, limit=limit)}


def _call_history_page(*, start=0, limit=CALL_HISTORY_PAGE_SIZE):
	start = max(0, cint(start))
	limit = min(CALL_HISTORY_MAX_PAGE_SIZE, max(1, cint(limit) or CALL_HISTORY_PAGE_SIZE))
	rows = _call_rows(start=start, limit=limit + 1)
	return {
		"rows": rows[:limit],
		"has_more": len(rows) > limit,
		"next_start": start + min(limit, len(rows)),
		"page_size": limit,
	}


def _calling_state(response):
	value = response if isinstance(response, dict) else {}
	if isinstance(value.get("data"), list) and value["data"]:
		value = value["data"][0] if isinstance(value["data"][0], dict) else {}
	calling = value.get("calling") if isinstance(value.get("calling"), dict) else value
	status = str(calling.get("status") or "DISABLED").upper()
	return {"enabled": status == "ENABLED", "status": status}


def _rtc_configuration():
	settings = frappe.get_single("WhatsApp Core Settings")
	desk_servers = settings.get_webrtc_ice_servers()
	if desk_servers:
		return {**DEFAULT_RTC_CONFIGURATION, "iceServers": desk_servers}

	configured = frappe.conf.get("whatsapp_core_webrtc_ice_servers")
	if isinstance(configured, str):
		try:
			configured = frappe.parse_json(configured)
		except Exception:
			configured = None
	servers = configured if isinstance(configured, list) and configured else DEFAULT_RTC_CONFIGURATION["iceServers"]
	return {**DEFAULT_RTC_CONFIGURATION, "iceServers": servers}


@frappe.whitelist()
@require_core_access()
def calling_workspace(account_name=None, include_sip_credentials=0):
	if int(include_sip_credentials or 0):
		frappe.throw("SIP credentials are not exposed to the browser", frappe.PermissionError)
	calls = []
	templates = []
	accounts = []
	selected = None
	contacts = contact_options(limit=50)
	try:
		accounts = _accounts()
		selected = _resolve_account_name(account_name)
		channel = next(row["channel"] for row in accounts if row["account_name"] == selected)
		# The global call dock must recover every pending scoped call after a page
		# reload, even when a different account happens to be selected in the page.
		call_page = _call_history_page()
		calls = call_page["rows"]
		templates = frappe.get_all(
			"WhatsApp Core Template",
			filters={"approval_status": "APPROVED", "enabled": 1, "channel": channel},
			fields=["name", "template_name", "language_code", "body_text"],
			order_by="template_name asc, language_code asc",
			limit_page_length=500,
		)
		settings = _call("calling", "get_call_settings", {
			"account_name": selected, "include_sip_credentials": 0,
		})
		return {
			"configured": True,
			"available": True,
			"error": "",
			"accounts": accounts,
			"selected_account": selected,
			"calling": _calling_state(settings),
			"can_manage": _can_manage(),
			"rtc_configuration": _rtc_configuration(),
			"calls": calls,
			"calls_has_more": call_page["has_more"],
			"calls_next_start": call_page["next_start"],
			"calls_page_size": call_page["page_size"],
			"templates": templates,
			"contacts": contacts,
		}
	except Exception as error:
		if not calls:
			calls = _call_rows()
		return _workspace_failure(
			error,
			accounts=accounts,
			selected_account=selected,
			calling={"enabled": False, "status": "UNAVAILABLE"},
			can_manage=_can_manage(),
			rtc_configuration=_rtc_configuration(),
			calls=calls,
			calls_has_more=False,
			calls_next_start=len(calls),
			calls_page_size=CALL_HISTORY_PAGE_SIZE,
			templates=templates,
			contacts=contacts,
		)


@frappe.whitelist()
@require_core_access()
def call_history(start=0, limit=CALL_HISTORY_PAGE_SIZE):
	"""Return one bounded, permission-scoped page of call history."""
	return _call_history_page(start=start, limit=limit)


@frappe.whitelist()
@require_core_access(manage=True)
def update_call_settings(account_name, calling):
	return _call("calling", "update_call_settings", {
		"account_name": _resolve_account_name(account_name),
		"calling": _calling_settings(calling),
	})


@frappe.whitelist()
@require_core_access(manage=True)
def enable_calling(account_name):
	"""Enable the supported Calling product defaults without exposing Meta enums."""
	_call("calling", "update_call_settings", {
		"account_name": _resolve_account_name(account_name),
		"calling": {"status": "ENABLED", "call_icon_visibility": "DEFAULT"},
	})
	return {"success": True, "calling": {"enabled": True, "status": "ENABLED"}}


def _claim_call(call_id, *, allowed_states=None):
	row = frappe.db.sql(
		"""SELECT name, handled_by, status FROM `tabWhatsApp Core Call`
		WHERE call_id = %s FOR UPDATE""",
		(str(call_id or "").strip(),),
		as_dict=True,
	)
	if not row:
		frappe.throw("Call not found", frappe.DoesNotExistError)
	if allowed_states and str(row[0].status or "").lower() not in allowed_states:
		frappe.throw("This call is no longer available to answer", frappe.ValidationError)
	handler = str(row[0].handled_by or "")
	if handler and handler != frappe.session.user:
		frappe.throw("This call is already being handled by another team member", frappe.PermissionError)
	if not handler:
		frappe.db.set_value(
			"WhatsApp Core Call", row[0].name, "handled_by", frappe.session.user,
			update_modified=False,
		)
	return row[0].name


def _release_call_claim(call_id):
	row = frappe.db.sql(
		"""SELECT name, handled_by, status FROM `tabWhatsApp Core Call`
		WHERE call_id = %s FOR UPDATE""",
		(str(call_id or "").strip(),),
		as_dict=True,
	)
	if not row:
		frappe.throw("Call not found", frappe.DoesNotExistError)
	handler = str(row[0].handled_by or "")
	if handler != frappe.session.user:
		frappe.throw("Only the operator handling this call can release it", frappe.PermissionError)
	if str(row[0].status or "").lower() not in INCOMING_CALL_CLAIM_STATES:
		frappe.throw("This call has already entered provider negotiation", frappe.ValidationError)
	frappe.db.set_value(
		"WhatsApp Core Call", row[0].name, "handled_by", None,
		update_modified=False,
	)
	return row[0].name


@frappe.whitelist()
@require_core_access()
def claim_incoming_call(account_name, call_id):
	"""Atomically reserve one incoming call before browser media negotiation."""
	resolved_account = _resolve_account_name(account_name)
	assert_call_access(call_id)
	_assert_call_account(call_id, resolved_account)
	name = _claim_call(call_id, allowed_states=INCOMING_CALL_CLAIM_STATES)
	from frappe_whatsapp_core.realtime import publish_call_changes

	publish_call_changes([name])
	return {"success": True, "call_id": call_id, "handled_by": frappe.session.user}


@frappe.whitelist()
@require_core_access()
def release_incoming_call_claim(account_name, call_id):
	"""Return a locally failed, not-yet-preaccepted call to the team queue."""
	resolved_account = _resolve_account_name(account_name)
	assert_call_access(call_id)
	_assert_call_account(call_id, resolved_account)
	name = _release_call_claim(call_id)
	from frappe_whatsapp_core.realtime import publish_call_changes

	publish_call_changes([name])
	return {"success": True, "call_id": call_id}


def _provider_call_id(result):
	value = result.get("data") if isinstance(result, dict) else None
	value = value if isinstance(value, dict) else result if isinstance(result, dict) else {}
	calls = value.get("calls") if isinstance(value.get("calls"), list) else []
	return str((calls[0].get("id") if calls and isinstance(calls[0], dict) else None) or value.get("call_id") or "").strip()


def _record_outgoing_call(account_name, identity, payload, result):
	"""Create the scoped call immediately; its webhook remains authoritative."""
	call_id = _provider_call_id(result)
	if not call_id or not identity:
		return
	channel_name = frappe.db.get_value(
		"WhatsApp Core Hub Account",
		{"parent": "WhatsApp Core Settings", "account_name": account_name},
		"channel",
	)
	if not channel_name:
		return
	identity_doc = frappe.get_cached_doc("WhatsApp Core Identity", identity)
	channel = frappe.get_cached_doc("WhatsApp Core Channel", channel_name)
	conversation = get_or_create_conversation(channel, identity_doc)
	name = frappe.db.get_value("WhatsApp Core Call", {"call_id": call_id}, "name")
	values = {
		"channel": channel.name,
		"conversation": conversation.name,
		"remote_identity": identity_doc.name,
		"direction": "Outbound",
		"status": "connect",
		"remote_number": payload.get("to"),
		"remote_user_id": payload.get("recipient"),
		"handled_by": frappe.session.user,
		"started_at": now_datetime(),
		"session": payload.get("session"),
		"last_event": {"event": "connect", "source": "browser"},
	}
	if name:
		frappe.db.set_value("WhatsApp Core Call", name, values, update_modified=False)
	else:
		name = frappe.get_doc({
			"doctype": "WhatsApp Core Call",
			"call_id": call_id,
			**values,
		}).insert(ignore_permissions=True).name
	touch_conversation_call_activity(conversation.name, values["started_at"])
	from frappe_whatsapp_core.realtime import publish_call_changes

	publish_call_changes([name])


def _assert_call_account(call_id, account_name):
	"""Prevent an authorized call id from being submitted through another channel."""
	account_channel = frappe.db.get_value(
		"WhatsApp Core Hub Account",
		{"parent": "WhatsApp Core Settings", "account_name": account_name},
		"channel",
	)
	call_channel = frappe.db.get_value(
		"WhatsApp Core Call", {"call_id": str(call_id or "").strip()}, "channel"
	)
	if not account_channel or call_channel != account_channel:
		frappe.throw("Call does not belong to the selected WhatsApp account", frappe.PermissionError)


def _record_call_action(call_id, action):
	"""Project a successful browser action without overtaking a newer webhook state."""
	row = frappe.db.get_value(
		"WhatsApp Core Call",
		{"call_id": str(call_id or "").strip()},
		["name", "status"],
		as_dict=True,
	)
	if not row or str(row.status or "").lower() not in CALL_ACTION_SOURCE_STATES[action]:
		return
	frappe.db.set_value("WhatsApp Core Call", row.name, "status", action, update_modified=False)
	from frappe_whatsapp_core.realtime import publish_call_changes

	publish_call_changes([row.name])


@frappe.whitelist()
@require_core_access()
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
@require_core_access()
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
@require_core_access()
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
@require_core_access()
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
@require_core_access()
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
@require_core_access()
def get_call_artifact(
	account_name=None,
	media_id=None,
	download=0,
	call_name=None,
	kind=None,
):
	"""Return a scoped call artifact, resolving its Hub account from the call.

	``account_name`` and ``media_id`` remain supported for the Calling workspace.
	The Shared Inbox sends the durable Core call name instead, so it never needs to
	guess which Hub account owns a recording on a multi-number site.
	"""
	kind = str(kind or "recording").strip().lower()
	if kind not in {"recording", "transcript"}:
		frappe.throw("Call artifact kind must be recording or transcript", frappe.ValidationError)
	fields = [
		"name", "call_id", "channel", "recording_media_id", "recording_url",
		"mixed_recording_url", "mixed_recording_mime_type",
		"transcript_media_id", "transcript_url",
	]
	call = None
	if call_name:
		call = frappe.db.get_value(
			"WhatsApp Core Call",
			str(call_name).strip(),
			fields,
			as_dict=True,
		)
		if call:
			media_id = call.get(f"{kind}_media_id")
	else:
		media_id = str(media_id or "").strip()
		call = frappe.db.get_value(
			"WhatsApp Core Call",
			{"recording_media_id": media_id},
			fields,
			as_dict=True,
		)
		kind = "recording"
		if not call:
			call = frappe.db.get_value(
				"WhatsApp Core Call",
				{"transcript_media_id": media_id},
				fields,
				as_dict=True,
			)
			kind = "transcript"
	if not call:
		frappe.throw("Call artifact is not linked to a Core call", frappe.DoesNotExistError)
	assert_call_access(call.call_id)
	local_url = str(
		(call.get("mixed_recording_url") if kind == "recording" else None)
		or call.get(f"{kind}_url")
		or ""
	).strip()
	if int(download or 0) and local_url.startswith("/private/files/"):
		return {
			"success": True,
			"file_url": local_url,
			"media_id": media_id or "",
			"cached": True,
		}
	if not media_id:
		frappe.throw(f"This call has no {kind} artifact", frappe.DoesNotExistError)
	if not account_name:
		settings = frappe.get_cached_doc("WhatsApp Core Settings")
		account_name = settings.get_account_name(call.channel)
	account_name = _resolve_account_name(account_name)
	_assert_call_account(call.call_id, account_name)
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


def _mixed_recording_mime_type(file_doc, content: bytes) -> str:
	"""Validate the small set of browser audio containers accepted by Core."""
	suffix = Path(file_doc.file_name or "").suffix.lower()
	mime_type = {
		".webm": "audio/webm",
		".ogg": "audio/ogg",
		".oga": "audio/ogg",
		".m4a": "audio/mp4",
		".mp4": "audio/mp4",
	}.get(suffix, "")
	valid_magic = (
		(mime_type == "audio/webm" and content.startswith(b"\x1aE\xdf\xa3"))
		or (mime_type == "audio/ogg" and content.startswith(b"OggS"))
		or (mime_type == "audio/mp4" and len(content) >= 12 and content[4:8] == b"ftyp")
	)
	if mime_type not in MIXED_RECORDING_MIME_TYPES or not valid_magic:
		frappe.throw("Call recording must be a WebM, OGG, or MP4 audio file", frappe.ValidationError)
	return mime_type


@frappe.whitelist()
@require_core_access()
def attach_mixed_call_recording(call_id, file_url):
	"""Attach the browser mix made by the operator who handled this call.

	The upload endpoint creates an unattached private File first. This operation
	binds it to exactly one authorized call only after checking ownership, size,
	container signature and the call claim.
	"""
	call_id = str(call_id or "").strip()
	file_url = str(file_url or "").strip()
	assert_call_access(call_id)
	call = frappe.db.get_value(
		"WhatsApp Core Call",
		{"call_id": call_id},
		["name", "handled_by", "mixed_recording_url"],
		as_dict=True,
	)
	if not call:
		frappe.throw("Call not found", frappe.DoesNotExistError)
	if str(call.handled_by or "") != frappe.session.user:
		frappe.throw(
			"Only the operator who handled this call can attach its browser recording",
			frappe.PermissionError,
		)
	if call.mixed_recording_url:
		if call.mixed_recording_url == file_url:
			return {"success": True, "file_url": file_url, "cached": True}
		frappe.throw("This call already has a browser recording", frappe.ValidationError)
	file_name = frappe.db.get_value("File", {"file_url": file_url}, "name")
	if not file_name:
		frappe.throw("Uploaded call recording not found", frappe.DoesNotExistError)
	file_doc = frappe.get_doc("File", file_name)
	if not file_doc.is_private or file_doc.owner != frappe.session.user:
		frappe.throw("The recording must be a private upload owned by you", frappe.PermissionError)
	if file_doc.attached_to_doctype or file_doc.attached_to_name:
		frappe.throw("The recording file is already attached to another document", frappe.PermissionError)
	if int(file_doc.file_size or 0) > MAX_BROWSER_CALL_RECORDING_BYTES:
		frappe.throw("Call recording exceeds the 50 MB limit", frappe.ValidationError)
	content = file_doc.get_content()
	if isinstance(content, str):
		content = content.encode()
	if not content or len(content) > MAX_BROWSER_CALL_RECORDING_BYTES:
		frappe.throw("Call recording is empty or exceeds the 50 MB limit", frappe.ValidationError)
	mime_type = _mixed_recording_mime_type(file_doc, content)
	file_doc.attached_to_doctype = "WhatsApp Core Call"
	file_doc.attached_to_name = call.name
	file_doc.save(ignore_permissions=True)
	frappe.db.set_value(
		"WhatsApp Core Call",
		call.name,
		{
			"mixed_recording_url": file_doc.file_url,
			"mixed_recording_mime_type": mime_type,
			"mixed_recording_sha256": hashlib.sha256(content).hexdigest(),
		},
		update_modified=False,
	)
	from frappe_whatsapp_core.realtime import publish_call_changes

	publish_call_changes([call.name])
	return {"success": True, "file_url": file_doc.file_url, "mime_type": mime_type}


@frappe.whitelist()
@require_core_access()
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
	resolved_account = _resolve_account_name(account_name)
	to_number, recipient = _contact_target(
		identity, to_number, recipient, "call_action", resolved_account
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
		assert_call_access(call_id)
		_assert_call_account(call_id, resolved_account)
		# Every provider-side action belongs to the operator who won this call's
		# row lock. A stale decline/hang-up from another ringing browser must never
		# terminate a call already answered by a teammate. The claim is per call,
		# so a different simultaneous call remains available to another operator.
		_claim_call(call_id)
		payload["call_id"] = call_id
	if action in {"connect", "pre_accept"}:
		if sdp_type not in {"offer", "answer"} or not sdp:
			frappe.throw("A valid SDP offer or answer is required", frappe.ValidationError)
		payload["session"] = {"sdp_type": sdp_type, "sdp": sdp}
	elif action == "accept" and (sdp_type or sdp):
		if sdp_type != "answer" or not sdp:
			frappe.throw("A complete SDP answer is required", frappe.ValidationError)
		payload["session"] = {"sdp_type": sdp_type, "sdp": sdp}
	if biz_opaque_callback_data:
		payload["biz_opaque_callback_data"] = str(biz_opaque_callback_data)[:512]
	# Recording is part of the product contract, not an operator-facing toggle.
	# Meta plays the consent announcement declared here before it records audio.
	if action in {"connect", "accept"}:
		if (
			recording is not None
			and _consent_option(recording, "recording").get("status") != "ENABLED"
		):
			frappe.throw("Call recording cannot be disabled", frappe.ValidationError)
		recording = dict(DEFAULT_CALL_RECORDING)
	if recording is not None or transcription is not None:
		if action not in {"connect", "accept"}:
			frappe.throw("Recording controls require connect or accept", frappe.ValidationError)
		if recording is not None:
			payload["recording"] = _consent_option(recording, "recording")
		if transcription is not None:
			payload["transcription"] = _consent_option(transcription, "transcription")
	result = relay_call_action(resolved_account, payload)
	# Meta has already accepted the action at this point. A local projection race
	# must not turn that successful operation into an error popup or a retry that
	# performs the action twice. The authoritative webhook repairs the projection.
	savepoint = "whatsapp_core_call_action_projection"
	frappe.db.savepoint(savepoint)
	try:
		if action == "connect":
			_record_outgoing_call(resolved_account, identity, payload, result)
		else:
			_record_call_action(call_id, action)
	except Exception:
		frappe.db.rollback(save_point=savepoint)
		frappe.log_error(
			title="WhatsApp call action projection failed",
			message=frappe.get_traceback(),
		)
	return result
