import json

import frappe
from frappe import _
from frappe.model.document import Document


class WhatsAppCoreIdentitySource(Document):
	def validate(self):
		self.source_key = (self.source_key or "").strip()
		self.display_name = (self.display_name or "").strip()
		self.phone_field = (self.phone_field or "").strip()
		if not self.source_key:
			frappe.throw(_("Source Key is required."))
		if not self.source_doctype:
			frappe.throw(_("Source DocType is required."))
		if not self.phone_field:
			frappe.throw(_("Phone Field is required."))
		self._validate_mapping_fields()
		self._validate_filter_fields()
		if self.filters:
			try:
				filters = json.loads(self.filters)
			except json.JSONDecodeError:
				frappe.throw(_("Filters must contain valid JSON."))
			if not isinstance(filters, dict):
				frappe.throw(_("Filters must be a JSON object."))

	def _validate_filter_fields(self):
		from frappe_whatsapp_core.business_filters import (
			MAX_CONFIGURED_FIELDS,
			is_filterable_field,
			table_multiselect_value_field,
		)

		try:
			configured = frappe.parse_json(self.filter_fields or "[]")
		except (TypeError, ValueError, json.JSONDecodeError):
			frappe.throw(_("Inbox Filter Fields must contain valid JSON."))
		if not isinstance(configured, list):
			frappe.throw(_("Inbox Filter Fields must be a JSON list."))
		configured = list(dict.fromkeys(str(value or "").strip() for value in configured if value))
		if len(configured) > MAX_CONFIGURED_FIELDS:
			frappe.throw(_("Select no more than {0} inbox filter fields.").format(MAX_CONFIGURED_FIELDS))
		meta = frappe.get_meta(self.source_doctype)
		for fieldname in configured:
			field = meta.get_field(fieldname)
			if not is_filterable_field(field):
				frappe.throw(_("{0} is not a filterable field on {1}.").format(fieldname, self.source_doctype))
			if field.fieldtype == "Table MultiSelect" and not table_multiselect_value_field(field):
				frappe.throw(_("{0} does not contain a Link value field.").format(field.label or fieldname))
		self.filter_fields = frappe.as_json(configured)

	def _validate_mapping_fields(self):
		meta = frappe.get_meta(self.source_doctype)
		phone_path = self.phone_field.split(".")
		if len(phone_path) == 1:
			self._require_data_field(
				meta,
				phone_path[0],
				"Phone Field",
			)
		elif len(phone_path) == 2:
			table_field = meta.get_field(phone_path[0])
			if (
				not table_field
				or table_field.fieldtype != "Table"
			):
				frappe.throw(
					_("{0} must be a child-table field.").format(
						phone_path[0]
					)
				)
			self._require_data_field(
				frappe.get_meta(table_field.options),
				phone_path[1],
				"Phone Field",
			)
		else:
			frappe.throw(
				_(
					"Phone Field supports one field or one child-table path."
				)
			)

		for fieldname, label in (
			(self.display_name_field, "Display Name Field"),
			(self.entity_type_field, "Entity Type Field"),
		):
			if fieldname:
				self._require_data_field(
					meta,
					fieldname,
					label,
				)

	def _require_data_field(self, meta, fieldname, label):
		field = meta.get_field(fieldname)
		if not field:
			frappe.throw(
				_("{0} {1} does not exist on {2}.").format(
					label,
					fieldname,
					meta.name,
				)
			)
		if field.fieldtype in (
			"Table",
			"Table MultiSelect",
			"Section Break",
			"Column Break",
			"Tab Break",
		):
			frappe.throw(
				_("{0} {1} cannot use {2}.").format(
					label,
					fieldname,
					field.fieldtype,
				)
			)
