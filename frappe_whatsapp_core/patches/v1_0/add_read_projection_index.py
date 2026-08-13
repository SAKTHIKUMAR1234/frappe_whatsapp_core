"""Add the covering index used to project per-message operator readers."""

import frappe


def execute():
	frappe.db.add_index(
		"WhatsApp Core Conversation Read",
		["conversation", "last_read_at", "last_read_creation", "user"],
		"wa_core_read_projection",
	)
