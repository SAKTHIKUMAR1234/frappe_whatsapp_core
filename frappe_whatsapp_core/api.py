import hashlib
import json

import frappe
from frappe.utils import now_datetime

from frappe_whatsapp_core.dispatcher import enqueue_event, enqueue_event_batch


@frappe.whitelist()
def receive():
	"""Persist one event or a relay-provided batch before business processing."""
	payload = frappe.request.get_json()
	if not payload:
		frappe.throw("No payload received")
	if isinstance(payload, list):
		return receive_batch(payload)
	return receive_one(payload)


def receive_one(payload):
	event = describe_payload(payload)
	event_id = payload_fingerprint(payload)
	if frappe.db.exists("WhatsApp Core Event", event_id):
		return {"status": "duplicate", "event_id": event_id}

	try:
		doc = frappe.get_doc({
			"doctype": "WhatsApp Core Event",
			"event_id": event_id,
			"status": "Pending",
			"event_type": event["event_type"],
			"direction": "Inbound",
			"channel_key": event["channel_key"],
			"external_id": event["external_id"],
			"conversation_key": event["conversation_key"],
			"payload": canonical_json(payload),
		})
		doc.insert(ignore_permissions=True)
	except frappe.DuplicateEntryError:
		return {"status": "duplicate", "event_id": event_id}

	enqueue_event(event_id, enqueue_after_commit=True)
	return {"status": "queued", "event_id": event_id}


def receive_batch(payloads):
	"""Insert a relay window with one SQL operation and enqueue one background job."""
	if not payloads:
		frappe.throw("No events received")
	if len(payloads) > 500:
		frappe.throw("Batch exceeds the 500 event safety limit")
	if any(not isinstance(payload, dict) for payload in payloads):
		frappe.throw("Every batch item must be a JSON object")

	described = []
	for payload in payloads:
		event_id = payload_fingerprint(payload)
		described.append((event_id, describe_payload(payload), canonical_json(payload)))

	event_ids = list(dict.fromkeys(item[0] for item in described))
	existing = set(frappe.get_all(
		"WhatsApp Core Event",
		filters={"name": ["in", event_ids]},
		pluck="name",
	))
	new_items = []
	seen = set(existing)
	for event_id, event, canonical_payload in described:
		if event_id in seen:
			continue
		seen.add(event_id)
		new_items.append((event_id, event, canonical_payload))

	if new_items:
		timestamp = now_datetime()
		user = frappe.session.user or "Administrator"
		fields = [
			"name", "creation", "modified", "modified_by", "owner", "docstatus", "idx",
			"event_id", "status", "event_type", "direction", "channel_key",
			"external_id", "conversation_key", "payload", "attempts",
		]
		values = [
			(
				event_id, timestamp, timestamp, user, user, 0, 0,
				event_id, "Pending", event["event_type"], "Inbound",
				event["channel_key"], event["external_id"], event["conversation_key"],
				canonical_payload, 0,
			)
			for event_id, event, canonical_payload in new_items
		]
		frappe.db.bulk_insert(
			"WhatsApp Core Event",
			fields=fields,
			values=values,
			ignore_duplicates=True,
		)
		enqueue_event_batch(
			[item[0] for item in new_items],
			enqueue_after_commit=True,
		)

	return {
		"status": "queued",
		"received": len(payloads),
		"inserted": len(new_items),
		"duplicates": len(payloads) - len(new_items),
		"event_ids": [item[0] for item in new_items],
	}


def payload_fingerprint(payload):
	return hashlib.sha256(canonical_json(payload).encode()).hexdigest()


def canonical_json(payload):
	return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def describe_payload(payload):
	description = {
		"event_type": "unknown",
		"channel_key": "",
		"external_id": "",
		"conversation_key": "",
	}
	if payload.get("template_status_update"):
		value = payload["template_status_update"]
		description.update({
			"event_type": "template_status",
			"external_id": str(value.get("message_template_id") or value.get("message_template_name") or ""),
		})
		return description

	for entry in payload.get("entry", []):
		for change in entry.get("changes", []):
			value = change.get("value", {})
			description["channel_key"] = value.get("metadata", {}).get("phone_number_id", "")
			if change.get("field") == "message_template_status_update":
				description["event_type"] = "template_status"
				description["external_id"] = str(
					value.get("message_template_id") or value.get("message_template_name") or ""
				)
				return description
			messages = value.get("messages", [])
			if messages:
				message = messages[0]
				description.update({
					"event_type": f"message:{message.get('type', 'unknown')}",
					"external_id": message.get("id", ""),
					"conversation_key": message.get("from", ""),
				})
				return description
			statuses = value.get("statuses", [])
			if statuses:
				status = statuses[0]
				description.update({
					"event_type": f"status:{status.get('status', 'unknown')}",
					"external_id": status.get("id", ""),
					"conversation_key": status.get("recipient_id", ""),
				})
				return description
	return description
