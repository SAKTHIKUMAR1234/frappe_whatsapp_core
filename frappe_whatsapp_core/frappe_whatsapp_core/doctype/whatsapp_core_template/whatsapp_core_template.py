"""Site-local projection of templates assigned by the Integration app."""

from __future__ import annotations

import frappe
from frappe.model.document import Document


class WhatsAppCoreTemplate(Document):
	def validate(self):
		from frappe_whatsapp_core.template_catalog import scoped_template_key

		self.account_name = (self.account_name or "").strip()
		self.channel = (self.channel or "").strip()
		self.template_name = (self.template_name or "").strip()
		self.language_code = (self.language_code or "en").strip()
		self.approval_status = (self.approval_status or "UNKNOWN").upper()
		self.parameter_format = (self.parameter_format or "POSITIONAL").strip().upper()
		if not self.account_name or not self.channel:
			frappe.throw(
				"Template account and channel are required",
				frappe.ValidationError,
			)
		if not frappe.db.exists(
			"WhatsApp Core Hub Account",
			{
				"parent": "WhatsApp Core Settings",
				"parenttype": "WhatsApp Core Settings",
				"parentfield": "accounts",
				"account_name": self.account_name,
				"channel": self.channel,
			},
		):
			frappe.throw(
				"Template account is not mapped to this Core channel",
				frappe.ValidationError,
			)
		expected_key = scoped_template_key(
			self.account_name, self.template_name, self.language_code
		)
		if self.template_key != expected_key:
			frappe.throw(
				"Template key does not match its account-scoped identity",
				frappe.ValidationError,
			)

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
		if self.parameter_format not in {"POSITIONAL", "NAMED"}:
			frappe.throw("Unsupported template parameter format", frappe.ValidationError)
