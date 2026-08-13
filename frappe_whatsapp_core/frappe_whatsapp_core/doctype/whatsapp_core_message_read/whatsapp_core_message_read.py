"""Immutable per-message operator read ledger."""

import frappe
from frappe.model.document import Document


class WhatsAppCoreMessageRead(Document):
	pass


def on_doctype_update():
	frappe.db.add_index(
		"WhatsApp Core Message Read",
		["message", "user"],
		"wa_core_message_reader",
	)
	frappe.db.add_index(
		"WhatsApp Core Message Read",
		["conversation", "user", "read_at"],
		"wa_core_conversation_user_read",
	)
	frappe.db.add_index(
		"WhatsApp Core Message Read",
		["contact", "read_at"],
		"wa_core_contact_read",
	)
