"""Site-local projection of templates assigned by the Integration app."""

from __future__ import annotations

import frappe
from frappe.model.document import Document


class WhatsAppCoreTemplate(Document):
	def validate(self):
		self.template_name = (self.template_name or "").strip()
		self.language_code = (self.language_code or "en").strip()
		self.approval_status = (self.approval_status or "UNKNOWN").upper()

		if self.approval_status not in {
			"UNKNOWN",
			"DRAFT",
			"IN_REVIEW",
			"APPROVED",
			"REJECTED",
			"PAUSED",
			"DISABLED",
		}:
			frappe.throw(
				f"Unsupported template approval status: {self.approval_status}",
				frappe.ValidationError,
			)

