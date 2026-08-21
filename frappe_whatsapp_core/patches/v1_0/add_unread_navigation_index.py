"""Add the covering prefix used by global unread navigation projections."""

import frappe


def execute():
	frappe.db.add_index(
		"WhatsApp Core Message",
		["direction", "conversation", "message_type"],
		"wa_core_message_direction_conversation_type",
	)
