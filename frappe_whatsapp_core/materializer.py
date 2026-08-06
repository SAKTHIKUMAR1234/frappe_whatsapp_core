import hashlib
import json
from datetime import datetime, timezone

import frappe
from frappe.utils import get_datetime, now_datetime

from frappe_whatsapp_core.delivery import advance_delivery_status
from frappe_whatsapp_core.identity import (
	get_or_create_identity as get_or_create_core_identity,
)
from frappe_whatsapp_core.party_bindings import ensure_party_bindings


def materialize_event(event, payload):
	"""Project a raw provider event into the reusable messaging kernel."""
	results = []
	for entry in payload.get("entry", []):
		for change in entry.get("changes", []):
			value = change.get("value") or {}
			phone_number_id = value.get("metadata", {}).get("phone_number_id")
			if not phone_number_id:
				continue
			channel = get_or_create_channel(phone_number_id, entry.get("id"))
			for message in value.get("messages") or []:
				results.append(materialize_inbound_message(event, channel, message))
			for status in value.get("statuses") or []:
				results.append(materialize_status(channel, status, event=event))
			for call in value.get("calls") or []:
				results.append(materialize_call(event, channel, call))
			for group_event in value.get("groups") or []:
				results.append(
					materialize_group_event(
						event,
						channel,
						group_event,
						change.get("field") or "groups",
					)
				)
	return results


def get_or_create_channel(phone_number_id, waba_id=None):
	channel_key = f"meta:{phone_number_id}"
	if frappe.db.exists("WhatsApp Core Channel", channel_key):
		return frappe.get_doc("WhatsApp Core Channel", channel_key)
	doc = frappe.get_doc({
		"doctype": "WhatsApp Core Channel",
		"channel_key": channel_key,
		"provider": "meta",
		"phone_number_id": phone_number_id,
		"waba_id": waba_id or "",
		"display_name": phone_number_id,
		"enabled": 1,
	})
	try:
		doc.insert(ignore_permissions=True)
	except frappe.DuplicateEntryError:
		return frappe.get_doc("WhatsApp Core Channel", channel_key)
	return doc


def get_or_create_identity(value):
	return get_or_create_core_identity(value)


def get_or_create_conversation(channel, identity):
	conversation_key = hashlib.sha256(f"{channel.name}:{identity.name}:active".encode()).hexdigest()
	if frappe.db.exists("WhatsApp Core Conversation", conversation_key):
		return frappe.get_doc("WhatsApp Core Conversation", conversation_key)
	doc = frappe.get_doc({
		"doctype": "WhatsApp Core Conversation",
		"conversation_key": conversation_key,
		"channel": channel.name,
		"remote_identity": identity.name,
		"status": "Open",
		"last_message_at": now_datetime(),
	})
	try:
		doc.insert(ignore_permissions=True)
	except frappe.DuplicateEntryError:
		return frappe.get_doc("WhatsApp Core Conversation", conversation_key)
	return doc


def materialize_inbound_message(event, channel, provider_message):
	provider_id = provider_message.get("id")
	if not provider_id:
		return {"kind": "message", "status": "ignored", "reason": "missing_provider_id"}
	message_key = hashlib.sha256(f"{channel.name}:{provider_id}".encode()).hexdigest()
	if frappe.db.exists("WhatsApp Core Message", message_key):
		return {"kind": "message", "status": "duplicate", "name": message_key}

	group_id = provider_message.get("group_id")
	identity = get_or_create_group_identity(group_id) if group_id else get_or_create_identity(provider_message.get("from") or "")
	if not group_id:
		ensure_party_bindings(identity.name, {"channel": channel.name, "provider_message": provider_message})
	conversation = get_or_create_conversation(channel, identity)
	message_type = provider_message.get("type") or "unknown"
	content = provider_message.get(message_type) or {}
	body = inbound_message_body(message_type, content)
	timestamp = provider_message.get("timestamp")
	provider_timestamp = parse_provider_timestamp(timestamp)
	doc = frappe.get_doc({
		"doctype": "WhatsApp Core Message",
		"message_key": message_key,
		"conversation": conversation.name,
		"relay_event": event.name,
		"channel": channel.name,
		"provider_message_id": provider_id,
		"direction": "Inbound",
		"message_type": message_type,
		"body": body or "",
		"content": json.dumps(provider_message, separators=(",", ":"), ensure_ascii=False),
		"provider_timestamp": provider_timestamp,
		"delivery_status": "Received",
	})
	try:
		doc.insert(ignore_permissions=True)
	except frappe.DuplicateEntryError:
		return {"kind": "message", "status": "duplicate", "name": message_key}
	conversation.last_inbound_at = provider_timestamp
	conversation.last_message_at = provider_timestamp
	conversation.save(ignore_permissions=True)
	return {"kind": "message", "status": "created", "name": doc.name}


def get_or_create_group_identity(group_id):
	"""Keep a group thread separate from each participant's direct conversation."""
	group_id = str(group_id or "").strip()
	if not group_id:
		frappe.throw("A group ID is required")
	identity_key = hashlib.sha256(f"whatsapp-group:{group_id}".encode()).hexdigest()
	if frappe.db.exists("WhatsApp Core Identity", identity_key):
		return frappe.get_doc("WhatsApp Core Identity", identity_key)
	doc = frappe.get_doc({
		"doctype": "WhatsApp Core Identity", "identity_key": identity_key,
		"identity_type": "External", "normalized_value": f"group:{group_id}",
		"display_value": group_id, "provider": "meta", "status": "Active",
		"resolution_status": "Unresolved", "attributes": {"group_id": group_id},
	})
	try:
		doc.insert(ignore_permissions=True)
	except frappe.DuplicateEntryError:
		return frappe.get_doc("WhatsApp Core Identity", identity_key)
	return doc


def materialize_call(event, channel, provider_call):
	call_id = str(provider_call.get("id") or provider_call.get("call_id") or "").strip()
	if not call_id:
		return {"kind": "call", "status": "ignored", "reason": "missing_call_id"}
	existing = frappe.db.exists("WhatsApp Core Call", call_id)
	status = str(provider_call.get("event") or provider_call.get("status") or "received")
	values = {
		"doctype": "WhatsApp Core Call", "call_id": call_id, "relay_event": event.name,
		"channel": channel.name,
		"status": status, "last_event": provider_call,
	}
	direction = provider_call.get("direction")
	if direction or not existing:
		direction = str(
			direction
			or ("Outbound" if provider_call.get("to") or provider_call.get("recipient") else "Inbound")
		).title()
		values["direction"] = direction if direction in {"Inbound", "Outbound"} else "Inbound"
	for fieldname, value in {
		"remote_number": provider_call.get("from") or provider_call.get("to") or provider_call.get("recipient"),
		"remote_user_id": provider_call.get("from_user_id") or provider_call.get("to_user_id"),
		"remote_parent_user_id": provider_call.get("from_parent_user_id") or provider_call.get("to_parent_user_id"),
		"remote_username": provider_call.get("from_username") or provider_call.get("to_username"),
		"callback_data": provider_call.get("biz_opaque_callback_data"),
		"cta_payload": provider_call.get("cta_payload"),
		"deeplink_payload": provider_call.get("deeplink_payload"),
	}.items():
		if value not in (None, ""):
			values[fieldname] = value
	if provider_call.get("session"):
		values["session"] = provider_call["session"]
	recording = (provider_call.get("call_recording") or {}).get("audio") or {}
	transcript = (provider_call.get("call_transcript") or {}).get("document") or {}
	if recording:
		values.update({
			"recording_media_id": recording.get("id") or "",
			"recording_url": recording.get("url") or "",
			"recording_mime_type": recording.get("mime_type") or "",
			"recording_sha256": recording.get("sha256") or "",
		})
	if transcript:
		values.update({
			"transcript_media_id": transcript.get("id") or "",
			"transcript_url": transcript.get("url") or "",
			"transcript_mime_type": transcript.get("mime_type") or "",
			"transcript_sha256": transcript.get("sha256") or "",
		})
	if status in {"connect", "connected", "ringing"}:
		values["started_at"] = parse_provider_timestamp(provider_call.get("timestamp"))
	if status in {"terminate", "terminated", "rejected", "failed"}:
		values["ended_at"] = parse_provider_timestamp(provider_call.get("timestamp"))
	if existing:
		doc = frappe.get_doc("WhatsApp Core Call", call_id)
		doc.update(values)
		doc.save(ignore_permissions=True)
		return {"kind": "call", "status": "updated", "name": doc.name}
	doc = frappe.get_doc(values).insert(ignore_permissions=True)
	return {"kind": "call", "status": "created", "name": doc.name}


def materialize_group_event(event, channel, provider_group, webhook_field="groups"):
	"""Project Meta group lifecycle, settings, status and membership webhooks."""
	group_id = str(provider_group.get("group_id") or "").strip()
	if not group_id:
		return {"kind": "group", "status": "ignored", "reason": "missing_group_id"}
	event_type = str(provider_group.get("type") or webhook_field or "group_update")
	values = {
		"doctype": "WhatsApp Core Group",
		"group_id": group_id,
		"relay_event": event.name,
		"channel": channel.name,
		"last_event_type": event_type,
		"last_event": provider_group,
		"last_synced": now_datetime(),
	}
	if not frappe.db.exists("WhatsApp Core Group", group_id):
		values["status"] = "Active"
	if event_type == "group_create":
		values.update({
			"subject": provider_group.get("subject") or "",
			"description": provider_group.get("description") or "",
			"invite_link": provider_group.get("invite_link") or "",
			"join_approval_mode": provider_group.get("join_approval_mode") or "",
			"created_at": parse_provider_timestamp(provider_group.get("timestamp")),
			"status": "Failed" if provider_group.get("errors") else "Active",
		})
	elif event_type == "group_delete":
		values["status"] = "Failed" if provider_group.get("errors") else "Deleted"
	elif event_type == "group_suspend":
		values["status"] = "Suspended"
	elif event_type == "group_suspend_cleared":
		values["status"] = "Active"
	elif event_type == "group_settings_update":
		subject = provider_group.get("group_subject") or {}
		description = provider_group.get("group_description") or {}
		if subject.get("update_successful") is not False and subject.get("text") is not None:
			values["subject"] = subject["text"]
		if description.get("update_successful") is not False and description.get("text") is not None:
			values["description"] = description["text"]

	if frappe.db.exists("WhatsApp Core Group", group_id):
		group = frappe.get_doc("WhatsApp Core Group", group_id)
		group.update(values)
		group.save(ignore_permissions=True)
		projection_status = "updated"
	else:
		group = frappe.get_doc(values).insert(ignore_permissions=True)
		projection_status = "created"

	member_results = _materialize_group_members(event, group, provider_group)
	if member_results:
		group.participant_count = frappe.db.count(
			"WhatsApp Core Group Member",
			{"group": group.name, "status": "Active"},
		)
		group.save(ignore_permissions=True)
	return {
		"kind": "group",
		"status": projection_status,
		"name": group.name,
		"members": member_results,
	}


def _materialize_group_members(event, group, provider_group):
	results = []
	event_type = str(provider_group.get("type") or "")
	if event_type in {"group_join_request_created", "group_join_request_revoked"}:
		participant = provider_group.get("wa_id")
		if participant:
			results.append(_upsert_group_member(
				event,
				group,
				participant,
				"Pending" if event_type.endswith("created") else "Revoked",
				provider_group,
			))
	for item in provider_group.get("added_participants") or []:
		participant = item.get("wa_id") or item.get("input")
		if participant:
			results.append(_upsert_group_member(event, group, participant, "Active", provider_group))
	for item in provider_group.get("removed_participants") or []:
		participant = item.get("wa_id") or item.get("input")
		if participant:
			results.append(_upsert_group_member(event, group, participant, "Removed", provider_group))
	for item in provider_group.get("failed_participants") or []:
		participant = item.get("wa_id") or item.get("input")
		if participant:
			results.append(_upsert_group_member(event, group, participant, "Failed", provider_group))
	return results


def _upsert_group_member(event, group, participant, status, provider_group):
	participant = str(participant).strip()
	member_key = hashlib.sha256(f"{group.name}:{participant}".encode()).hexdigest()
	values = {
		"doctype": "WhatsApp Core Group Member",
		"member_key": member_key,
		"relay_event": event.name,
		"group": group.name,
		"participant_id": participant,
		"status": status,
		"join_request_id": provider_group.get("join_request_id") or "",
		"reason": provider_group.get("reason") or "",
		"last_event": provider_group,
		"last_synced": now_datetime(),
	}
	if frappe.db.exists("WhatsApp Core Group Member", member_key):
		doc = frappe.get_doc("WhatsApp Core Group Member", member_key)
		doc.update(values)
		doc.save(ignore_permissions=True)
		return {"status": "updated", "name": doc.name}
	doc = frappe.get_doc(values).insert(ignore_permissions=True)
	return {"status": "created", "name": doc.name}


def inbound_message_body(message_type: str, content) -> str:
	"""Create a searchable/operator-friendly summary without losing raw Meta data."""
	if message_type == "contacts" and isinstance(content, list):
		names = [((item.get("name") or {}).get("formatted_name")) for item in content if isinstance(item, dict)]
		return "Contacts: " + ", ".join(name for name in names if name)
	if not isinstance(content, dict):
		return ""
	if message_type == "text":
		return str(content.get("body") or "")
	if message_type in {"image", "video", "document", "audio"}:
		return str(content.get("caption") or f"[{message_type.title()}]")
	if message_type == "sticker":
		return "[Sticker]"
	if message_type == "reaction":
		return str(content.get("emoji") or "[Reaction removed]")
	if message_type == "button":
		return str(content.get("text") or content.get("payload") or "[Button reply]")
	if message_type == "interactive":
		reply = content.get("button_reply") or content.get("list_reply") or {}
		if reply:
			return str(reply.get("title") or reply.get("id") or "[Interactive reply]")
		flow_reply = content.get("nfm_reply") or {}
		if flow_reply:
			response = flow_reply.get("response_json")
			try:
				response = json.loads(response) if isinstance(response, str) else response
			except (TypeError, ValueError):
				pass
			return f"Flow response: {json.dumps(response, ensure_ascii=False) if isinstance(response, (dict, list)) else response or 'received'}"
	if message_type == "location":
		return str(content.get("name") or content.get("address") or f"Location: {content.get('latitude')}, {content.get('longitude')}")
	return str(content.get("body") or f"[{message_type.replace('_', ' ').title()}]")


def materialize_status(channel, provider_status, event=None):
	provider_id = provider_status.get("id")
	if not provider_id:
		return {"kind": "status", "status": "ignored", "reason": "missing_provider_id"}
	message_name = frappe.db.get_value(
		"WhatsApp Core Message",
		{"channel": channel.name, "provider_message_id": provider_id},
		"name",
	)
	participant_id = (
		provider_status.get("recipient_participant_id")
		or provider_status.get("participant_recipient_id")
	)
	if provider_status.get("recipient_type") == "group" and participant_id:
		return materialize_group_receipt(event, channel, provider_status, message_name)
	if not message_name:
		return {"kind": "status", "status": "orphan", "provider_message_id": provider_id}
	status = (provider_status.get("status") or "sent").title()
	allowed = {"Queued", "Sent", "Delivered", "Read", "Failed", "Deleted"}
	incoming = status if status in allowed else "Sent"
	current = frappe.db.get_value(
		"WhatsApp Core Message",
		message_name,
		"delivery_status",
	)
	frappe.db.set_value(
		"WhatsApp Core Message",
		message_name,
		"delivery_status",
		advance_delivery_status(current, incoming),
	)
	return {"kind": "status", "status": "updated", "name": message_name}


def materialize_group_receipt(event, channel, provider_status, message_name=None):
	group_id = str(provider_status.get("recipient_id") or "").strip()
	participant = str(
		provider_status.get("recipient_participant_id")
		or provider_status.get("participant_recipient_id")
		or ""
	).strip()
	if not group_id or not participant:
		return {"kind": "group_receipt", "status": "ignored", "reason": "missing_group_or_participant"}
	if not frappe.db.exists("WhatsApp Core Group", group_id):
		group = frappe.get_doc({
			"doctype": "WhatsApp Core Group",
			"group_id": group_id,
			"relay_event": event.name if event else None,
			"channel": channel.name,
			"status": "Active",
			"last_event_type": "message_status",
			"last_event": provider_status,
			"last_synced": now_datetime(),
		}).insert(ignore_permissions=True)
	else:
		group = frappe.get_doc("WhatsApp Core Group", group_id)
	receipt_key = hashlib.sha256(
		f"{provider_status.get('id')}:{group_id}:{participant}".encode()
	).hexdigest()
	values = {
		"doctype": "WhatsApp Core Group Receipt",
		"receipt_key": receipt_key,
		"relay_event": event.name if event else None,
		"message": message_name,
		"group": group.name,
		"participant_id": participant,
		"status": str(provider_status.get("status") or "sent").title(),
		"provider_timestamp": parse_provider_timestamp(provider_status.get("timestamp")),
		"error": json.dumps(provider_status.get("errors") or [], separators=(",", ":")),
		"last_event": provider_status,
	}
	if frappe.db.exists("WhatsApp Core Group Receipt", receipt_key):
		doc = frappe.get_doc("WhatsApp Core Group Receipt", receipt_key)
		doc.update(values)
		doc.save(ignore_permissions=True)
		status = "updated"
	else:
		doc = frappe.get_doc(values).insert(ignore_permissions=True)
		status = "created"
	return {"kind": "group_receipt", "status": status, "name": doc.name}


def normalize_phone(value, *, assume_local: bool = False, country_code: str = "91"):
	from frappe_whatsapp_core.identity import normalize_phone as normalize_identity_phone

	return normalize_identity_phone(
		value,
		assume_local=assume_local,
		country_code=country_code,
	)


def parse_provider_timestamp(value):
	"""Convert Meta's Unix-second timestamp without treating it as a date string."""
	if value in (None, ""):
		return now_datetime()
	if isinstance(value, (int, float)) or str(value).strip().isdigit():
		return datetime.fromtimestamp(int(value), tz=timezone.utc).replace(tzinfo=None)
	return get_datetime(value)
