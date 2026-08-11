import frappe
from frappe.model.document import Document


class WhatsAppCoreConversationRead(Document):
	pass


def on_doctype_update():
	frappe.db.add_index(
		"WhatsApp Core Conversation Read",
		["conversation", "user", "last_read_at"],
		"conversation_user_read_index",
	)
