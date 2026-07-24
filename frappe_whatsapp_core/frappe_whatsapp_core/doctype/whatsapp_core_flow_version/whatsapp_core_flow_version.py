import frappe
from frappe.model.document import Document


class WhatsAppCoreFlowVersion(Document):
	def before_save(self):
		if not self.is_new():
			original = self.get_doc_before_save()
			if original and original.status in {"Published", "Superseded"}:
				for field in ("flow", "version_number", "graph", "graph_sha256"):
					if self.get(field) != original.get(field):
						frappe.throw("Published flow versions are immutable")

