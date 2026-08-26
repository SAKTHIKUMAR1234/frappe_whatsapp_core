import frappe
from frappe.model.document import Document
from frappe.utils import now


class WhatsAppCoreInternalComment(Document):
	def validate(self):
		self.content = str(self.content or "").strip()
		if not self.content:
			frappe.throw("Internal comment cannot be empty", frappe.ValidationError)
		if len(self.content) > 2000:
			frappe.throw("Internal comment cannot exceed 2,000 characters", frappe.ValidationError)
		if self.status not in {"Open", "Resolved"}:
			frappe.throw("Internal work status must be Open or Resolved", frappe.ValidationError)
		if self.status == "Resolved":
			self.resolved_by = self.resolved_by or frappe.session.user
			self.resolved_at = self.resolved_at or now()
		else:
			self.resolved_by = ""
			self.resolved_at = None
