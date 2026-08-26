"""Permission-scoped business record filters for the shared inbox.

Identity Sources are the administrator-owned allowlist. Operators never send a
DocType or field name that is trusted directly: every identifier used below is
resolved from Frappe metadata and the source's configured ``filter_fields``.
"""

from __future__ import annotations

import json
import re

import frappe
from frappe.utils import cint

from frappe_whatsapp_core.permissions import conversation_conditions


MAX_ACTIVE_FILTERS = 8
MAX_CONFIGURED_FIELDS = 20
MAX_OPTION_ROWS = 50

_TEXT_FIELD_TYPES = {
	"Autocomplete",
	"Data",
	"Phone",
	"Read Only",
	"Small Text",
	"Text",
	"Long Text",
}
_NUMBER_FIELD_TYPES = {"Int", "Float", "Currency", "Percent", "Duration", "Rating"}
_DATE_FIELD_TYPES = {"Date", "Datetime", "Time"}
_EXACT_FIELD_TYPES = {"Link", "Select"}
_FILTERABLE_FIELD_TYPES = (
	_TEXT_FIELD_TYPES
	| _NUMBER_FIELD_TYPES
	| _DATE_FIELD_TYPES
	| _EXACT_FIELD_TYPES
	| {"Check", "Table MultiSelect"}
)


def source_schemas() -> list[dict]:
	"""Return the enabled, administrator-curated inbox filter schema."""
	result = []
	for source in frappe.get_all(
		"WhatsApp Core Identity Source",
		filters={"enabled": 1},
		fields=["name", "source_key", "display_name", "source_doctype", "filter_fields", "priority"],
		order_by="priority asc, display_name asc",
		limit_page_length=500,
	):
		fields = configured_fields(source)
		if not fields:
			continue
		result.append({
			"name": source.name,
			"source_key": source.source_key,
			"display_name": source.display_name,
			"source_doctype": source.source_doctype,
			"fields": [field_schema(field) for field in fields.values()],
		})
	return result


def configured_fields(source) -> dict:
	"""Resolve configured fields against current DocType metadata."""
	if isinstance(source, str):
		source = frappe.db.get_value(
			"WhatsApp Core Identity Source",
			source,
			["name", "source_key", "display_name", "source_doctype", "filter_fields", "enabled"],
			as_dict=True,
		)
	if not source or not cint(source.get("enabled", 1)):
		return {}
	try:
		configured = frappe.parse_json(source.get("filter_fields") or "[]")
	except (TypeError, ValueError, json.JSONDecodeError):
		return {}
	if not isinstance(configured, list):
		return {}
	meta = frappe.get_meta(source.source_doctype)
	result = {}
	for fieldname in list(dict.fromkeys(str(value or "").strip() for value in configured))[
		:MAX_CONFIGURED_FIELDS
	]:
		field = meta.get_field(fieldname)
		if not field or not is_filterable_field(field):
			continue
		if field.fieldtype == "Table MultiSelect" and not table_multiselect_value_field(field):
			continue
		result[fieldname] = field
	return result


def is_filterable_field(field) -> bool:
	return bool(
		field
		and field.fieldname
		and not getattr(field, "is_virtual", False)
		and field.fieldtype in _FILTERABLE_FIELD_TYPES
	)


def field_schema(field) -> dict:
	fieldtype = field.fieldtype
	control = "text"
	choices = []
	target = ""
	if fieldtype == "Check":
		control = "boolean"
	elif fieldtype == "Select":
		control = "choices"
		choices = [
			{"label": choice, "value": choice}
			for value in str(field.options or "").splitlines()
			if (choice := value.strip())
		]
	elif fieldtype == "Link":
		control = "link"
		target = field.options or ""
	elif fieldtype == "Table MultiSelect":
		control = "link"
		value_field = table_multiselect_value_field(field)
		target = value_field.options if value_field else ""
	elif fieldtype in _DATE_FIELD_TYPES:
		control = "date"
	elif fieldtype in _NUMBER_FIELD_TYPES:
		control = "number"
	return {
		"fieldname": field.fieldname,
		"label": field.label or field.fieldname.replace("_", " ").title(),
		"fieldtype": fieldtype,
		"options": target or field.options or "",
		"control": control,
		"multiple": fieldtype in _EXACT_FIELD_TYPES or fieldtype == "Table MultiSelect",
		"choices": choices,
	}


def add_business_filters(
	conditions: list[str],
	values: dict,
	*,
	source_name: str | None,
	raw_filters=None,
	conversation_alias: str = "conversation",
) -> None:
	"""Append a correlated Identity Link/source-document filter to a query."""
	source_name = str(source_name or "").strip()
	filters = _parse_filters(raw_filters)
	if not source_name:
		if filters:
			frappe.throw("Select a business contact source before applying its filters", frappe.ValidationError)
		return
	source = _enabled_source(source_name)
	fields = configured_fields(source)
	active = []
	for fieldname, value in filters.items():
		if fieldname not in fields:
			frappe.throw("A requested business filter is not enabled for this contact source", frappe.ValidationError)
		if _has_filter_value(value, fields[fieldname].fieldtype):
			active.append((fieldname, value, fields[fieldname]))
	if len(active) > MAX_ACTIVE_FILTERS:
		frappe.throw(f"Use no more than {MAX_ACTIVE_FILTERS} business filters at once", frappe.ValidationError)

	values["business_source"] = source.name
	values["business_source_doctype"] = source.source_doctype
	document_alias = "business_document"
	clauses = []
	for index, (fieldname, value, field) in enumerate(active):
		clauses.append(_field_condition(document_alias, source.source_doctype, field, value, index, values))
	table = quote_table(source.source_doctype)
	conditions.append(
		f"""EXISTS (
			SELECT 1
			FROM `tabWhatsApp Core Identity Link` AS business_link
			INNER JOIN {table} AS {document_alias}
				ON {document_alias}.name = business_link.reference_name
			WHERE business_link.identity = {conversation_alias}.remote_identity
				AND business_link.identity_source = %(business_source)s
				AND business_link.reference_doctype = %(business_source_doctype)s
				AND business_link.status = 'Active'
				{" AND ".join(["", *clauses])}
		)"""
	)


def filter_options(source_name: str, fieldname: str, search: str = "") -> list[dict]:
	"""Return distinct choices that occur on contacts visible to this operator."""
	source = _enabled_source(source_name)
	field = configured_fields(source).get(str(fieldname or "").strip())
	if not field:
		frappe.throw("This field is not enabled as an inbox filter", frappe.ValidationError)
	query = " ".join(str(search or "").strip().split())[:120]
	if field.fieldtype == "Select":
		choices = field_schema(field)["choices"]
		if query:
			choices = [row for row in choices if query.casefold() in row["label"].casefold()]
		return choices[:MAX_OPTION_ROWS]
	if field.fieldtype == "Check":
		return []

	conditions, values = conversation_conditions("option_conversation")
	values.update({
		"option_source": source.name,
		"option_doctype": source.source_doctype,
		"option_limit": MAX_OPTION_ROWS,
	})
	document_table = quote_table(source.source_doctype)
	document_alias = "option_document"
	joins = ""
	if field.fieldtype == "Table MultiSelect":
		value_field = table_multiselect_value_field(field)
		child_alias = "option_child"
		joins = f"""INNER JOIN {quote_table(field.options)} AS {child_alias}
			ON {child_alias}.parent = {document_alias}.name
			AND {child_alias}.parenttype = %(option_doctype)s
			AND {child_alias}.parentfield = %(option_parentfield)s"""
		values["option_parentfield"] = field.fieldname
		expression = f"{child_alias}.{quote_identifier(value_field.fieldname)}"
		target_doctype = value_field.options or ""
	else:
		expression = f"{document_alias}.{quote_identifier(field.fieldname)}"
		target_doctype = field.options if field.fieldtype == "Link" else ""
	conditions.extend([f"{expression} IS NOT NULL", f"{expression} != ''"])
	if query:
		values["option_search"] = f"%{query}%"
		conditions.append(f"CAST({expression} AS CHAR) LIKE %(option_search)s")
	rows = frappe.db.sql(
		f"""SELECT DISTINCT {expression} AS value
		FROM `tabWhatsApp Core Conversation` AS option_conversation
		INNER JOIN `tabWhatsApp Core Identity Link` AS option_link
			ON option_link.identity = option_conversation.remote_identity
			AND option_link.identity_source = %(option_source)s
			AND option_link.reference_doctype = %(option_doctype)s
			AND option_link.status = 'Active'
		INNER JOIN {document_table} AS {document_alias}
			ON {document_alias}.name = option_link.reference_name
		{joins}
		WHERE {" AND ".join(conditions)}
		ORDER BY value ASC
		LIMIT %(option_limit)s""",
		values,
		as_dict=True,
	)
	return _present_options(rows, target_doctype)


def table_multiselect_value_field(field):
	if not field or field.fieldtype != "Table MultiSelect" or not field.options:
		return None
	child_meta = frappe.get_meta(field.options)
	return next(
		(
			child
			for child in child_meta.fields
			if child.fieldtype == "Link" and child.fieldname and child.options
		),
		None,
	)


def quote_identifier(value: str) -> str:
	value = str(value or "")
	if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
		raise ValueError("Unsafe database field identifier")
	return f"`{value}`"


def quote_table(doctype: str) -> str:
	if not frappe.db.exists("DocType", doctype):
		raise ValueError("Unknown DocType")
	return f"`tab{str(doctype).replace('`', '``')}`"


def _enabled_source(source_name: str):
	source = frappe.db.get_value(
		"WhatsApp Core Identity Source",
		source_name,
		["name", "source_key", "display_name", "source_doctype", "filter_fields", "enabled"],
		as_dict=True,
	)
	if not source or not cint(source.enabled):
		frappe.throw("Enabled business contact source not found", frappe.DoesNotExistError)
	return source


def _parse_filters(raw_filters) -> dict:
	if not raw_filters:
		return {}
	try:
		filters = frappe.parse_json(raw_filters) if isinstance(raw_filters, str) else raw_filters
	except (TypeError, ValueError, json.JSONDecodeError):
		frappe.throw("Business filters must be a JSON object", frappe.ValidationError)
	if not isinstance(filters, dict):
		frappe.throw("Business filters must be a JSON object", frappe.ValidationError)
	return filters


def _has_filter_value(value, fieldtype: str) -> bool:
	if fieldtype == "Check":
		return value not in (None, "")
	if isinstance(value, (list, tuple, set)):
		return any(str(item or "").strip() for item in value)
	return bool(str(value or "").strip())


def _field_condition(document_alias, source_doctype, field, value, index, values) -> str:
	key = f"business_filter_{index}"
	column = f"{document_alias}.{quote_identifier(field.fieldname)}"
	if field.fieldtype == "Table MultiSelect":
		value_field = table_multiselect_value_field(field)
		selected = _selected_values(value)
		values[key] = tuple(selected)
		values[f"{key}_parentfield"] = field.fieldname
		values[f"{key}_parenttype"] = source_doctype
		return f"""EXISTS (
			SELECT 1 FROM {quote_table(field.options)} AS business_child_{index}
			WHERE business_child_{index}.parent = {document_alias}.name
				AND business_child_{index}.parenttype = %({key}_parenttype)s
				AND business_child_{index}.parentfield = %({key}_parentfield)s
				AND business_child_{index}.{quote_identifier(value_field.fieldname)} IN %({key})s
		)"""
	if field.fieldtype == "Check":
		values[key] = cint(value)
		return f"COALESCE({column}, 0) = %({key})s"
	if field.fieldtype in _EXACT_FIELD_TYPES:
		selected = _selected_values(value)
		values[key] = tuple(selected)
		return f"{column} IN %({key})s"
	if field.fieldtype in _NUMBER_FIELD_TYPES or field.fieldtype in _DATE_FIELD_TYPES:
		values[key] = value
		return f"{column} = %({key})s"
	values[key] = f"%{' '.join(str(value).strip().split())[:120]}%"
	return f"CAST({column} AS CHAR) LIKE %({key})s"


def _selected_values(value) -> list[str]:
	values = value if isinstance(value, (list, tuple, set)) else [value]
	result = list(dict.fromkeys(str(item or "").strip() for item in values if str(item or "").strip()))
	if not result:
		frappe.throw("Select at least one value for each active business filter", frappe.ValidationError)
	return result[:50]


def _present_options(rows, target_doctype: str) -> list[dict]:
	values = [str(row.value) for row in rows if row.value not in (None, "")]
	labels = {}
	if target_doctype and values and frappe.db.exists("DocType", target_doctype):
		meta = frappe.get_meta(target_doctype)
		title_field = meta.title_field if meta.title_field and meta.title_field != "name" else ""
		if title_field:
			labels = dict(
				frappe.get_all(
					target_doctype,
					filters={"name": ["in", values]},
					fields=["name", title_field],
					as_list=True,
					limit_page_length=len(values),
				)
			)
	return [
		{
			"value": value,
			"label": labels.get(value) or value,
			"description": value if labels.get(value) and labels[value] != value else "",
		}
		for value in values
	]
