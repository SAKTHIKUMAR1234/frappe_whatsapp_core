import frappe
from frappe.model.document import Document

from frappe_whatsapp_core.permissions import assert_identity_team_access


class WhatsAppCoreContactFolderItem(Document):
	def validate(self):
		self.user = frappe.session.user
		owner = frappe.db.get_value("WhatsApp Core Contact Folder", self.folder, "user")
		if owner != self.user:
			frappe.throw("Folder not found", frappe.DoesNotExistError)
		assert_identity_team_access(self.identity)
