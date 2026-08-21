import frappe
from frappe.model.document import Document


class WhatsAppCoreInternalComment(Document):
	def validate(self):
		self.content = str(self.content or "").strip()
		if not self.content:
			frappe.throw("Internal comment cannot be empty", frappe.ValidationError)
		if len(self.content) > 2000:
			frappe.throw("Internal comment cannot exceed 2,000 characters", frappe.ValidationError)
