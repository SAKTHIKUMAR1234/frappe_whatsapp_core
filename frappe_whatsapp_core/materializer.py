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
				results.append(materialize_status(channel, status))
			for call in value.get("calls") or []:
				results.append(materialize_call(event, channel, call))
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
	status = str(provider_call.get("event") or provider_call.get("status") or "received")
	direction = str(provider_call.get("direction") or "Inbound").title()
	if direction not in {"Inbound", "Outbound"}:
		direction = "Inbound"
	values = {
		"doctype": "WhatsApp Core Call", "call_id": call_id, "relay_event": event.name,
		"channel": channel.name,
		"direction": direction, "status": status,
		"remote_number": provider_call.get("from") or provider_call.get("to") or provider_call.get("recipient") or "",
		"callback_data": provider_call.get("biz_opaque_callback_data") or "",
		"session": provider_call.get("session") or {}, "last_event": provider_call,
	}
	if status in {"connect", "connected", "ringing"}:
		values["started_at"] = parse_provider_timestamp(provider_call.get("timestamp"))
	if status in {"terminate", "terminated", "rejected", "failed"}:
		values["ended_at"] = parse_provider_timestamp(provider_call.get("timestamp"))
	if frappe.db.exists("WhatsApp Core Call", call_id):
		doc = frappe.get_doc("WhatsApp Core Call", call_id)
		doc.update(values)
		doc.save(ignore_permissions=True)
		return {"kind": "call", "status": "updated", "name": doc.name}
	doc = frappe.get_doc(values).insert(ignore_permissions=True)
	return {"kind": "call", "status": "created", "name": doc.name}


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


def materialize_status(channel, provider_status):
	provider_id = provider_status.get("id")
	if not provider_id:
		return {"kind": "status", "status": "ignored", "reason": "missing_provider_id"}
	message_name = frappe.db.get_value(
		"WhatsApp Core Message",
		{"channel": channel.name, "provider_message_id": provider_id},
		"name",
	)
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
