from __future__ import annotations

import frappe
from frappe.model.document import Document


class WhatsAppCoreContactFolder(Document):
	def validate(self):
		self.user = frappe.session.user
		self.folder_name = " ".join(str(self.folder_name or "").split())[:80]
		self.folder_type = self.folder_type or "Custom"
		if not self.folder_name:
			frappe.throw("Folder name is required", frappe.ValidationError)
		if self.folder_type == "Important":
			self.folder_name = "Important"
