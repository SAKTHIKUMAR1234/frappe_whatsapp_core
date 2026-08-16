"""Provider-neutral consent controls for deterministic WhatsApp operations."""

from __future__ import annotations

import json

import frappe
from frappe.utils import now_datetime

from frappe_whatsapp_core.delivery import enqueue_delivery_status_handlers
from frappe_whatsapp_core.flows import cancel_flow
from frappe_whatsapp_core.realtime import publish_invalidation

OPT_OUT_COMMANDS = {"stop", "/stop"}


def is_opt_out_event(event: dict | None) -> bool:
	if not isinstance(event, dict):
		return False
	value = (
		event.get("button_id")
		or event.get("interactive_id")
		or event.get("interactive_value")
		or event.get("body")
		or event.get("text")
		or ""
	)
	return str(value).strip().casefold() in OPT_OUT_COMMANDS


def suppress_conversation(conversation_name: str, event_key: str) -> dict:
	"""Block an identity and cancel all Core work that has not left the site."""
	conversation = frappe.get_doc("WhatsApp Core Conversation", conversation_name)
	identity = frappe.get_doc("WhatsApp Core Identity", conversation.remote_identity)
	attributes = _json_dict(identity.attributes)
	attributes["consent"] = {
		"status": "Opted Out",
		"source": "Inbound STOP",
		"event_key": event_key,
		"at": str(now_datetime()),
	}
	identity.status = "Blocked"
	identity.attributes = json.dumps(attributes, separators=(",", ":"), ensure_ascii=False)
	identity.save(ignore_permissions=True)

	active = frappe.db.get_value(
		"WhatsApp Core Flow Instance",
		{"conversation": conversation.name, "status": ["in", ["Running", "Waiting"]]},
		"name",
		order_by="started_at desc",
	)
	if active:
		cancel_flow(active, event_key, reason="Customer opted out")

	now = now_datetime()
	queued_messages = frappe.get_all(
		"WhatsApp Core Message",
		filters={
			"conversation": conversation.name,
			"direction": "Outbound",
			"delivery_status": "Queued",
		},
		pluck="name",
		limit_page_length=10000,
	)
	if queued_messages:
		frappe.db.sql(
			"""
			UPDATE `tabWhatsApp Core Message`
			SET delivery_status = 'Failed',
				failure = %(failure)s,
				modified = %(now)s,
				modified_by = %(user)s
			WHERE name IN %(names)s AND delivery_status = 'Queued'
			""",
			{
				"names": tuple(queued_messages),
				"failure": json.dumps({"reason": "Customer opted out before delivery"}),
				"now": now,
				"user": frappe.session.user,
			},
		)
		enqueue_delivery_status_handlers([
			{"message_name": name, "delivery_status": "Failed"}
			for name in queued_messages
		])

	skipped_recipients = frappe.get_all(
		"WhatsApp Core Campaign Recipient",
		filters={
			"identity": identity.name,
			"status": ["in", ["Prepared", "Queued"]],
		},
		pluck="name",
		limit_page_length=10000,
	)
	if skipped_recipients:
		frappe.db.sql(
			"""
			UPDATE `tabWhatsApp Core Campaign Recipient`
			SET status = 'Skipped', completed_at = %(now)s,
				modified = %(now)s, modified_by = %(user)s
			WHERE name IN %(names)s AND status IN ('Prepared', 'Queued')
			""",
			{
				"names": tuple(skipped_recipients),
				"now": now,
				"user": frappe.session.user,
			},
		)

	publish_invalidation("whatsapp_core_consent")
	return {
		"status": "blocked",
		"identity": identity.name,
		"cancelled_flow": active,
		"cancelled_messages": len(queued_messages),
		"skipped_campaign_recipients": len(skipped_recipients),
	}


def _json_dict(value) -> dict:
	if isinstance(value, dict):
		return dict(value)
	if not value:
		return {}
	try:
		parsed = json.loads(value)
		return parsed if isinstance(parsed, dict) else {}
	except (TypeError, ValueError):
		return {}
