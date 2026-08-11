"""Time-bounded AI summary layers used to build bounded conversation context."""

import frappe
from frappe.model.document import Document


class WhatsAppCoreSummaryPeriod(Document):
	pass


def on_doctype_update():
	frappe.db.add_index(
		"WhatsApp Core Summary Period",
		["identity", "period_type", "period_start"],
		"identity_period_start_index",
	)
	frappe.db.add_index(
		"WhatsApp Core Summary Period",
		["period_type", "period_end"],
		"period_type_end_index",
	)
