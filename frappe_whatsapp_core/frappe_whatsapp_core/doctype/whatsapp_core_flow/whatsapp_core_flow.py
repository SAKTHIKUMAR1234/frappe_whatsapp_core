import frappe
from frappe.model.document import Document

from frappe_whatsapp_core.flow_schema import validate_graph


class WhatsAppCoreFlow(Document):
	def validate(self):
		if self.draft_graph:
			errors = validate_graph(frappe.parse_json(self.draft_graph))
			self.validation_errors = "\n".join(errors)
		else:
			self.validation_errors = ""

