import frappe
from frappe.model.document import Document


class WhatsAppCoreEvent(Document):
	pass


def on_doctype_update():
	frappe.db.add_index(
		"WhatsApp Core Event",
		["external_id", "event_type", "status", "attempts"],
		"external_type_status_attempts_index",
	)
	frappe.db.add_index(
		"WhatsApp Core Event",
		["status", "modified"],
		"status_modified_index",
	)
