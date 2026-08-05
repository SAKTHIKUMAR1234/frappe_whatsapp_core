"""Campaign aggregate with deliberately separate preparation and send gates."""

from __future__ import annotations

import frappe
from frappe.model.document import Document


class WhatsAppCoreCampaign(Document):
	def validate(self):
		self.campaign_key = (self.campaign_key or "").strip()
		self.title = (self.title or "").strip()
		if not self.campaign_key:
			frappe.throw("Campaign key is required")
		if not self.title:
			frappe.throw("Campaign title is required")

		previous = self.get_doc_before_save()
		if not previous:
			return

		changed_definition = any(
			self.get(fieldname) != previous.get(fieldname)
			for fieldname in (
				"channel",
				"template",
				"audience_source",
			)
		)
		if changed_definition and previous.send_authorized:
			self.send_authorized = 0
			self.authorized_by = None
			self.authorized_at = None
			if self.status not in {"Draft", "Cancelled"}:
				self.status = "Draft"

