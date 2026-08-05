import hashlib

import frappe
from frappe import _
from frappe.model.document import Document


class WhatsAppCoreIdentityLink(Document):
	def autoname(self):
		self.link_key = make_identity_link_key(
			self.identity,
			self.identity_source,
			self.reference_doctype,
			self.reference_name,
		)
		self.name = self.link_key

	def validate(self):
		if not frappe.db.exists(self.reference_doctype, self.reference_name):
			frappe.throw(
				_("{0} {1} does not exist.").format(
					self.reference_doctype,
					self.reference_name,
				)
			)
		_validate_dynamic_link(
			self.parent_reference_doctype,
			self.parent_reference_name,
		)
		_validate_dynamic_link(
			self.group_reference_doctype,
			self.group_reference_name,
		)


def on_doctype_update():
	frappe.db.add_index(
		"WhatsApp Core Identity Link",
		["identity", "identity_source", "status"],
		"identity_source_status_index",
	)
	frappe.db.add_index(
		"WhatsApp Core Identity Link",
		["reference_doctype", "reference_name", "status"],
		"business_reference_status_index",
	)


def make_identity_link_key(identity, source, reference_doctype, reference_name):
	value = f"{identity}:{source}:{reference_doctype}:{reference_name}"
	return hashlib.sha256(value.encode()).hexdigest()


def _validate_dynamic_link(doctype, name):
	if bool(doctype) != bool(name):
		frappe.throw(
			_(
				"Both the reference DocType and reference name are required."
			)
		)
	if doctype and not frappe.db.exists(doctype, name):
		frappe.throw(
			_("{0} {1} does not exist.").format(doctype, name)
		)
