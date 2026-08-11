import frappe
from frappe.model.document import Document


class WhatsAppCoreMessage(Document):
	def on_trash(self):
		# Cloud API messages cannot be recalled from Meta. Keep the matching local
		# row as the immutable audit trail as well; only an explicit app uninstall
		# may remove the underlying application data.
		if not frappe.flags.in_uninstall:
			frappe.throw(
				"WhatsApp messages are permanent audit records and cannot be deleted",
				frappe.ValidationError,
			)


def on_doctype_update():
	frappe.db.add_index(
		"WhatsApp Core Message",
		["conversation", "provider_timestamp"],
		"conversation_provider_timestamp_index",
	)
	frappe.db.add_index(
		"WhatsApp Core Message",
		["delivery_status", "modified"],
		"delivery_status_modified_index",
	)
