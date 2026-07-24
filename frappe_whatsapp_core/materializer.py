import hashlib
import json
from datetime import datetime, timezone

import frappe
from frappe.utils import get_datetime, now_datetime


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
	normalized = normalize_phone(value)
	identity_key = hashlib.sha256(f"whatsapp:{normalized}".encode()).hexdigest()
	if frappe.db.exists("WhatsApp Core Identity", identity_key):
		return frappe.get_doc("WhatsApp Core Identity", identity_key)
	doc = frappe.get_doc({
		"doctype": "WhatsApp Core Identity",
		"identity_key": identity_key,
		"identity_type": "WhatsApp",
		"normalized_value": normalized,
		"display_value": value,
		"provider": "meta",
		"status": "Active",
	})
	try:
		doc.insert(ignore_permissions=True)
	except frappe.DuplicateEntryError:
		return frappe.get_doc("WhatsApp Core Identity", identity_key)
	return doc


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

	identity = get_or_create_identity(provider_message.get("from") or "")
	conversation = get_or_create_conversation(channel, identity)
	message_type = provider_message.get("type") or "unknown"
	content = provider_message.get(message_type) or {}
	body = content.get("body") if isinstance(content, dict) else ""
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
	frappe.db.set_value(
		"WhatsApp Core Message",
		message_name,
		"delivery_status",
		status if status in allowed else "Sent",
	)
	return {"kind": "status", "status": "updated", "name": message_name}


def normalize_phone(value):
	return "".join(character for character in str(value or "") if character.isdigit())


def parse_provider_timestamp(value):
	"""Convert Meta's Unix-second timestamp without treating it as a date string."""
	if value in (None, ""):
		return now_datetime()
	if isinstance(value, (int, float)) or str(value).strip().isdigit():
		return datetime.fromtimestamp(int(value), tz=timezone.utc).replace(tzinfo=None)
	return get_datetime(value)
