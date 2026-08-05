import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime

from frappe_whatsapp_core.party_bindings import make_binding_key


class WhatsAppCorePartyBinding(Document):
	def before_insert(self):
		self.binding_key = self._expected_key()

	def before_validate(self):
		expected_key = self._expected_key()
		if not self.binding_key:
			self.binding_key = expected_key
		elif not self.is_new() and self.binding_key != expected_key:
			frappe.throw(
				"Identity, workspace and party are immutable; create a new binding"
			)

	def _expected_key(self):
		return make_binding_key(
			self.identity,
			self.party_doctype,
			self.party_name,
			self.workspace_key,
		)

	def validate(self):
		if not frappe.db.exists(self.party_doctype, self.party_name):
			frappe.throw(
				f"{self.party_doctype} {self.party_name} does not exist"
			)
		if self.status == "Verified":
			self.verified_at = self.verified_at or now_datetime()
			self.verified_by = (
				self.verified_by
				or frappe.session.user
				or "Administrator"
			)

	def before_save(self):
		if self.is_primary and self.status == "Verified":
			filters = {
				"identity": self.identity,
				"workspace_key": self.workspace_key or "",
				"is_primary": 1,
				"status": "Verified",
			}
			existing = frappe.get_all(
				"WhatsApp Core Party Binding",
				filters=filters,
				pluck="name",
			)
			for name in existing:
				if name != self.name:
					frappe.db.set_value(
						"WhatsApp Core Party Binding",
						name,
						"is_primary",
						0,
						update_modified=False,
					)
