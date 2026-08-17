"""Stable business-key lookup for short-named WhatsApp Core records."""

from __future__ import annotations

import frappe


KEY_FIELDS = {
	"WhatsApp Core Call": "call_id",
	"WhatsApp Core Campaign": "campaign_key",
	"WhatsApp Core Campaign Recipient": "recipient_key",
	"WhatsApp Core Case": "case_key",
	"WhatsApp Core Case Type": "type_key",
	"WhatsApp Core Channel": "channel_key",
	"WhatsApp Core Contact Summary": "summary_key",
	"WhatsApp Core Conversation": "conversation_key",
	"WhatsApp Core Conversation Read": "read_key",
	"WhatsApp Core Conversation Topic": "topic_key",
	"WhatsApp Core Event": "event_id",
	"WhatsApp Core Flow": "flow_key",
	"WhatsApp Core Flow Instance": "instance_key",
	"WhatsApp Core Flow Response": "response_key",
	"WhatsApp Core Flow Step Run": "run_key",
	"WhatsApp Core Flow Trigger": "trigger_key",
	"WhatsApp Core Flow Version": "version_key",
	"WhatsApp Core Group": "group_id",
	"WhatsApp Core Group Member": "member_key",
	"WhatsApp Core Group Receipt": "receipt_key",
	"WhatsApp Core Handler Run": "run_key",
	"WhatsApp Core Identity": "identity_key",
	"WhatsApp Core Identity Alias": "alias_key",
	"WhatsApp Core Identity Link": "link_key",
	"WhatsApp Core Identity Source": "source_key",
	"WhatsApp Core MCP Invocation": "invocation_key",
	"WhatsApp Core Message": "message_key",
	"WhatsApp Core Message Bookmark": "bookmark_key",
	"WhatsApp Core Message Category": "category_name",
	"WhatsApp Core Message Category Assignment": "assignment_key",
	"WhatsApp Core Message Insight": "insight_key",
	"WhatsApp Core Message Read": "read_key",
	"WhatsApp Core Meta Flow Exchange": "request_id",
	"WhatsApp Core Party Binding": "binding_key",
	"WhatsApp Core Solution": "solution_key",
	"WhatsApp Core Summary Period": "summary_key",
	"WhatsApp Core Team": "team_name",
	"WhatsApp Core Template": "template_key",
	"WhatsApp Core Topic Message": "assignment_key",
	"WhatsApp Core Workspace": "workspace_key",
}


def name_by_key(doctype: str, key, *, filters: dict | None = None) -> str | None:
	"""Resolve an immutable business key to the short Frappe document name."""
	fieldname = KEY_FIELDS.get(doctype)
	if not fieldname or key in (None, ""):
		return None
	query = {fieldname: key}
	query.update(filters or {})
	return frappe.db.get_value(doctype, query, "name")


def resolve_name(doctype: str, identifier) -> str | None:
	"""Accept a short document name or its immutable business key."""
	identifier = str(identifier or "").strip()
	if not identifier:
		return None
	if frappe.db.exists(doctype, identifier):
		return identifier
	return name_by_key(doctype, identifier)


def doc_by_key(doctype: str, key):
	name = name_by_key(doctype, key)
	return frappe.get_doc(doctype, name) if name else None


def audit_short_names() -> dict:
	"""Return a read-only integrity report for a completed short-name migration."""
	doctypes = {}
	for doctype, key_field in KEY_FIELDS.items():
		if not frappe.db.exists("DocType", doctype):
			continue
		row = frappe.db.sql(
			f"""SELECT COUNT(*) AS records,
				COALESCE(MAX(CHAR_LENGTH(name)), 0) AS max_name_length,
				SUM(CHAR_LENGTH(name) > 20) AS long_names,
				SUM(COALESCE(`{key_field}`, '') = '') AS missing_business_keys
			FROM `tab{doctype}`""",
			as_dict=True,
		)[0]
		doctypes[doctype] = {
			"records": int(row.records or 0),
			"max_name_length": int(row.max_name_length or 0),
			"long_names": int(row.long_names or 0),
			"missing_business_keys": int(row.missing_business_keys or 0),
		}

	orphan_links = []
	core_doctypes = frappe.get_all(
		"DocType",
		filters={"module": "Frappe WhatsApp Core"},
		pluck="name",
		limit_page_length=0,
	)
	for source_doctype in core_doctypes:
		meta = frappe.get_meta(source_doctype)
		if meta.issingle or meta.is_virtual:
			continue
		for field in meta.fields:
			if field.fieldtype == "Link" and field.options and frappe.db.exists("DocType", field.options):
				missing = frappe.db.sql(
					f"""SELECT COUNT(*)
					FROM `tab{source_doctype}` AS source
					LEFT JOIN `tab{field.options}` AS target
						ON target.name = source.`{field.fieldname}`
					WHERE COALESCE(source.`{field.fieldname}`, '') != ''
						AND target.name IS NULL""",
				)[0][0]
				if missing:
					orphan_links.append({
						"doctype": source_doctype,
						"field": field.fieldname,
						"target": field.options,
						"missing": int(missing),
					})
			elif field.fieldtype == "Dynamic Link" and field.options:
				for value in frappe.get_all(
					source_doctype,
					fields=[field.options, field.fieldname],
					filters={field.fieldname: ["is", "set"]},
					limit_page_length=0,
				):
					target_doctype = value.get(field.options)
					target_name = value.get(field.fieldname)
					if (
						target_doctype
						and target_name
						and frappe.db.exists("DocType", target_doctype)
						and not frappe.db.exists(target_doctype, target_name)
					):
						orphan_links.append({
							"doctype": source_doctype,
							"field": field.fieldname,
							"target": target_doctype,
							"name": target_name,
							"missing": 1,
						})
	return {
		"ok": not orphan_links and all(
			not row["long_names"] and not row["missing_business_keys"]
			for row in doctypes.values()
		),
		"doctypes": doctypes,
		"orphan_links": orphan_links,
	}
