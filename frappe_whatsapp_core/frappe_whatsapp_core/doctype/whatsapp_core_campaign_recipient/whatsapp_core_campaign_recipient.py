"""One idempotent recipient row in a prepared campaign audience."""

import frappe
from frappe.model.document import Document


class WhatsAppCoreCampaignRecipient(Document):
	pass


def on_doctype_update():
	"""Keep campaign hot-path lookups indexed as audiences grow."""
	frappe.db.add_index(
		"WhatsApp Core Campaign Recipient",
		["campaign", "status", "creation"],
		"campaign_status_creation_index",
	)
	frappe.db.add_index(
		"WhatsApp Core Campaign Recipient",
		["core_message", "campaign"],
		"core_message_campaign_index",
	)
