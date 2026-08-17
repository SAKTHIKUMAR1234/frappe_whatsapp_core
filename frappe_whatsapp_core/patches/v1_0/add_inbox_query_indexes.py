"""Add the composite indexes used by cursor pagination and unread projections."""

import frappe


def execute():
	frappe.db.add_index(
		"WhatsApp Core Message",
		["conversation", "provider_timestamp", "creation"],
		"wa_core_message_conversation_time",
	)
	frappe.db.add_index(
		"WhatsApp Core Conversation",
		["last_message_at", "name"],
		"wa_core_conversation_last_message",
	)
	frappe.db.add_index(
		"WhatsApp Core Message Category Assignment",
		["conversation", "category"],
		"wa_core_category_conversation",
	)
	frappe.db.add_index(
		"WhatsApp Core Message Category Assignment",
		["message", "category"],
		"wa_core_category_message",
	)
