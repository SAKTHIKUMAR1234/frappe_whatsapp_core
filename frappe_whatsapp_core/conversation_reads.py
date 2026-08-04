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
	return {
		"conversation": conversation,
		"user": user,
		"last_read_message": message,
		"last_read_at": doc.last_read_at,
	}


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

