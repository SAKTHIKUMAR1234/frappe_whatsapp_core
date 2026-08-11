import frappe
from frappe.model.document import Document

from frappe_whatsapp_core.flow_actions import validate_registered_actions
from frappe_whatsapp_core.flow_schema import validate_graph


class WhatsAppCoreFlow(Document):
	def validate(self):
		if self.draft_graph:
			graph = frappe.parse_json(self.draft_graph)
			errors = validate_graph(graph) + validate_registered_actions(graph)
			self.validation_errors = "\n".join(errors)
		else:
			self.validation_errors = ""
