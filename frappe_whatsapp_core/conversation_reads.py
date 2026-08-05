"""Per-user conversation read cursors.

Provider delivery/read receipts and operator read state are different facts.
This service records only which authenticated operator opened which local
conversation, without changing the provider message status.
"""

from __future__ import annotations

import hashlib

import frappe
from frappe.utils import now

from frappe_whatsapp_core.permissions import require_core_access


@frappe.whitelist()
@require_core_access()
def mark_conversation_read(conversation: str, message: str | None = None) -> dict:
	frappe.has_permission(
		"WhatsApp Core Conversation",
		"read",
		conversation,
		throw=True,
	)
	if message:
		message_conversation = frappe.db.get_value(
			"WhatsApp Core Message",
			message,
			"conversation",
		)
		if message_conversation != conversation:
			frappe.throw("The read cursor message does not belong to this conversation")

	user = frappe.session.user
	read_key = hashlib.sha256(f"{conversation}:{user}".encode()).hexdigest()
	doc = (
		frappe.get_doc("WhatsApp Core Conversation Read", read_key)
		if frappe.db.exists("WhatsApp Core Conversation Read", read_key)
		else frappe.new_doc("WhatsApp Core Conversation Read")
	)
	doc.read_key = read_key
	doc.conversation = conversation
	doc.user = user
	doc.last_read_message = message
	doc.last_read_at = now()
	doc.save(ignore_permissions=True)
	provider_message = _latest_inbound_provider_message(conversation)
	if provider_message:
		frappe.enqueue(
			"frappe_whatsapp_core.conversation_reads.sync_provider_read",
			queue="short",
			enqueue_after_commit=True,
			channel=provider_message.channel,
			message_id=provider_message.provider_message_id,
		)
	return {
		"conversation": conversation,
		"user": user,
		"last_read_message": message,
		"last_read_at": doc.last_read_at,
	}


@frappe.whitelist()
@require_core_access()
def show_typing(conversation: str) -> dict:
	frappe.has_permission(
		"WhatsApp Core Conversation",
		"read",
		conversation,
		throw=True,
	)
	provider_message = _latest_inbound_provider_message(conversation)
	if not provider_message:
		return {"sent": False, "reason": "No inbound provider message"}
	from frappe_whatsapp_core.hub_client import mark_message_read

	mark_message_read(
		provider_message.channel,
		provider_message.provider_message_id,
		typing_indicator=True,
	)
	return {"sent": True, "message_id": provider_message.provider_message_id}


def sync_provider_read(channel: str, message_id: str) -> None:
	from frappe_whatsapp_core.hub_client import mark_message_read

	mark_message_read(channel, message_id)


def _latest_inbound_provider_message(conversation: str):
	rows = frappe.get_all(
		"WhatsApp Core Message",
		filters={
			"conversation": conversation,
			"direction": "Inbound",
			"provider_message_id": ["not like", "local:%"],
		},
		fields=["channel", "provider_message_id"],
		order_by="provider_timestamp desc, creation desc",
		limit_page_length=1,
	)
	return rows[0] if rows else None


@frappe.whitelist()
@require_core_access()
def conversation_readers(conversation: str) -> list[dict]:
	frappe.has_permission(
		"WhatsApp Core Conversation",
		"read",
		conversation,
		throw=True,
	)
	return frappe.get_all(
		"WhatsApp Core Conversation Read",
		filters={"conversation": conversation},
		fields=["user", "last_read_message", "last_read_at"],
		order_by="last_read_at desc",
		limit_page_length=100,
	)
