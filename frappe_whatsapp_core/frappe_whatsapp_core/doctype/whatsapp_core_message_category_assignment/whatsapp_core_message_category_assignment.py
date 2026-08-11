"""Indexed many-to-many category assignments for durable message discovery."""

import frappe
from frappe.model.document import Document


class WhatsAppCoreMessageCategoryAssignment(Document):
	pass


def on_doctype_update():
	frappe.db.add_index(
		"WhatsApp Core Message Category Assignment",
		["category", "conversation", "message"],
		"category_conversation_message_index",
	)
	frappe.db.add_index(
		"WhatsApp Core Message Category Assignment",
		["message", "category"],
		"message_category_index",
	)
