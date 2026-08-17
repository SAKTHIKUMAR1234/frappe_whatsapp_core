"""Replace legacy business-key primary names with Frappe short hashes."""

import hashlib
import json

import frappe
from frappe.model.rename_doc import (
	get_link_fields,
	rename_dynamic_links,
	rename_eps_records,
	rename_parent_and_child,
	rename_versions,
	update_attachments,
	update_user_settings,
)
from frappe.utils.password import rename_password

from frappe_whatsapp_core.naming import KEY_FIELDS


LEGACY_NAME_MINIMUM = 21
USER_SETTING_DOCTYPES = {
	"WhatsApp Core Campaign",
	"WhatsApp Core Case",
	"WhatsApp Core Case Type",
	"WhatsApp Core Channel",
	"WhatsApp Core Flow",
	"WhatsApp Core Identity Source",
	"WhatsApp Core Message Category",
	"WhatsApp Core Solution",
	"WhatsApp Core Team",
	"WhatsApp Core Template",
	"WhatsApp Core Workspace",
}


def execute():
	rename_map = {}
	for doctype, key_field in KEY_FIELDS.items():
		if not frappe.db.exists("DocType", doctype):
			continue
		while True:
			legacy_names = frappe.db.sql(
				f"""SELECT name
				FROM `tab{doctype}`
				WHERE name = `{key_field}` AND CHAR_LENGTH(name) >= %s
				ORDER BY name
				LIMIT 250""",
				(LEGACY_NAME_MINIMUM,),
				pluck=True,
			)
			if not legacy_names:
				break
			for old_name in legacy_names:
				new_name = _unused_short_name(doctype)
				if old_name in rename_map and rename_map[old_name] != new_name:
					raise RuntimeError(
						"Cannot safely rewrite ambiguous JSON references for duplicate "
						f"legacy name {old_name!r}"
					)
				_rename_generated_record(doctype, old_name, new_name)
				rename_map[old_name] = new_name
		frappe.clear_cache(doctype=doctype)
	_rewrite_json_references(rename_map)
	_rebuild_derived_keys()


def _rename_generated_record(doctype: str, old_name: str, new_name: str) -> None:
	"""Rename generated rows without one comment/cache/search job per record.

	Frappe's interactive rename routine intentionally creates a timeline Comment,
	clears the entire site cache and queues a search rebuild for every document.
	Those side effects are useful for a human rename but make a data migration both
	slower and larger. Core has no before/after rename hooks on these DocTypes, so
	the link-preserving primitives are the exact operation required here.
	"""
	meta = frappe.get_meta(doctype)
	link_fields = get_link_fields(doctype)
	rename_parent_and_child(doctype, old_name, new_name, meta)
	_update_link_field_values_without_hooks(link_fields, old_name, new_name, doctype)
	rename_dynamic_links(doctype, old_name, new_name)
	if doctype in USER_SETTING_DOCTYPES:
		update_user_settings(old_name, new_name, link_fields)
	update_attachments(doctype, old_name, new_name)
	rename_versions(doctype, old_name, new_name)
	rename_eps_records(doctype, old_name, new_name)
	rename_password(doctype, old_name, new_name)


def _update_link_field_values_without_hooks(
	link_fields: list[dict], old_name: str, new_name: str, doctype: str
) -> None:
	"""Rewrite Link values without validating unrelated business documents.

	Frappe's interactive rename helper saves Single DocTypes through the ORM so
	their defaults and validation hooks run. That is unsafe inside this migration:
	a customer settings DocType may validate the renamed Core row before the rest
	of the transaction has been reconciled. Direct writes preserve exactly the
	Link value while leaving modified timestamps and application hooks untouched.
	"""
	for field in link_fields:
		parent = field["parent"]
		fieldname = field["fieldname"]
		if field["issingle"]:
			frappe.db.sql(
				"""UPDATE `tabSingles`
				SET `value` = %s
				WHERE `doctype` = %s AND `field` = %s AND `value` = %s""",
				(new_name, parent, fieldname, old_name),
			)
			frappe.clear_cache(doctype=parent)
			continue

		# Match Frappe's DocType-rename special case while avoiding document
		# construction, save hooks and modified-timestamp churn.
		if parent == new_name and doctype == "DocType":
			parent = old_name
		frappe.db.set_value(
			parent,
			{fieldname: old_name},
			fieldname,
			new_name,
			update_modified=False,
		)


def _unused_short_name(doctype):
	for _attempt in range(20):
		candidate = frappe.generate_hash(length=10)
		if not frappe.db.exists(doctype, candidate):
			return candidate
	raise RuntimeError(f"Could not allocate a unique short name for {doctype}")


def _rewrite_json_references(rename_map: dict[str, str]) -> None:
	"""Translate primary-name references embedded in Core-owned JSON fields."""
	if not rename_map:
		return
	for doctype in KEY_FIELDS:
		if not frappe.db.exists("DocType", doctype):
			continue
		json_fields = [
			field.fieldname
			for field in frappe.get_meta(doctype).fields
			if field.fieldtype == "JSON"
		]
		if not json_fields:
			continue
		for row in frappe.get_all(
			doctype,
			fields=["name", *json_fields],
			limit_page_length=0,
		):
			updates = {}
			for fieldname in json_fields:
				raw = row.get(fieldname)
				if raw in (None, ""):
					continue
				try:
					value = json.loads(raw) if isinstance(raw, str) else raw
				except (TypeError, ValueError):
					continue
				rewritten = _rewrite_json_value(value, rename_map)
				if rewritten != value:
					updates[fieldname] = json.dumps(
						rewritten,
						separators=(",", ":"),
						ensure_ascii=False,
					)
			if updates:
				frappe.db.set_value(doctype, row.name, updates, update_modified=False)


def _rewrite_json_value(value, rename_map):
	if isinstance(value, str):
		return rename_map.get(value, value)
	if isinstance(value, list):
		return [_rewrite_json_value(item, rename_map) for item in value]
	if isinstance(value, dict):
		return {
			rename_map.get(key, key): _rewrite_json_value(item, rename_map)
			for key, item in value.items()
		}
	return value


def _rebuild_derived_keys() -> None:
	"""Recompute unique keys whose inputs include renamed Link values."""
	_rebuild_hash_key(
		"WhatsApp Core Identity Alias",
		"alias_key",
		["identity_scope", "alias_type", "alias_value"],
		lambda row: _sha(
			f"meta:{row.identity_scope or '*'}:{row.alias_type}:{row.alias_value}"
		),
	)
	_rebuild_hash_key(
		"WhatsApp Core Identity Link",
		"link_key",
		["identity", "identity_source", "reference_doctype", "reference_name"],
		lambda row: _sha(
			f"{row.identity}:{row.identity_source}:{row.reference_doctype}:{row.reference_name}"
		),
	)
	_rebuild_hash_key(
		"WhatsApp Core Party Binding",
		"binding_key",
		["identity", "workspace_key", "party_doctype", "party_name"],
		lambda row: _sha(
			"\x1f".join([
				str(row.identity or "").strip(),
				str(row.workspace_key or "").strip(),
				str(row.party_doctype or "").strip(),
				str(row.party_name or "").strip(),
			])
		),
	)
	_rebuild_hash_key(
		"WhatsApp Core Conversation",
		"conversation_key",
		["channel", "remote_identity"],
		lambda row: _sha(f"{row.channel}:{row.remote_identity}:active"),
	)
	_rebuild_hash_key(
		"WhatsApp Core Message",
		"message_key",
		["channel", "provider_message_id", "idempotency_key"],
		lambda row: _sha(f"{row.channel}:{row.provider_message_id}"),
		additional=lambda row: (
			{"idempotency_key": _sha(f"{row.channel}:{row.provider_message_id}")}
			if row.idempotency_key
			else {}
		),
	)
	_rebuild_hash_key(
		"WhatsApp Core Group Member",
		"member_key",
		["group", "participant_id"],
		lambda row: _sha(f"{row.group}:{row.participant_id}"),
	)
	_rebuild_hash_key(
		"WhatsApp Core Conversation Read",
		"read_key",
		["conversation", "user"],
		lambda row: _sha(f"{row.conversation}:{row.user}"),
	)
	_rebuild_hash_key(
		"WhatsApp Core Message Read",
		"read_key",
		["message", "user"],
		lambda row: _sha(f"{row.message}:{row.user}"),
	)
	_rebuild_hash_key(
		"WhatsApp Core Message Bookmark",
		"bookmark_key",
		["message", "user"],
		lambda row: _sha(f"{row.message}:{row.user}"),
	)
	_rebuild_hash_key(
		"WhatsApp Core Message Category Assignment",
		"assignment_key",
		["message", "category"],
		lambda row: _sha(f"{row.message}:{row.category}"),
	)
	_rebuild_hash_key(
		"WhatsApp Core Topic Message",
		"assignment_key",
		["topic", "message"],
		lambda row: _sha(f"{row.topic}:{row.message}"),
	)
	_rebuild_hash_key(
		"WhatsApp Core Handler Run",
		"run_key",
		["relay_event", "handler"],
		lambda row: _sha(f"{row.relay_event}:{row.handler}:v1"),
	)
	_rebuild_hash_key(
		"WhatsApp Core Message Insight",
		"insight_key",
		["message"],
		lambda row: _sha(f"message-insight:{row.message}"),
	)
	_rebuild_hash_key(
		"WhatsApp Core Summary Period",
		"summary_key",
		["identity", "period_type", "period_start"],
		lambda row: _sha(f"{row.identity}:{row.period_type}:{row.period_start}"),
	)
	_rebuild_flow_response_keys()
	_rebuild_contact_summary_keys()


def _rebuild_hash_key(doctype, key_field, source_fields, calculate, additional=None):
	if not frappe.db.exists("DocType", doctype):
		return
	rows = frappe.get_all(
		doctype,
		fields=["name", key_field, *source_fields],
		limit_page_length=0,
	)
	planned = [(row, calculate(row)) for row in rows]
	counts = {}
	for _row, value in planned:
		counts[value] = counts.get(value, 0) + 1
	for row, value in planned:
		# Historical imports can intentionally retain several source rows for one
		# semantic target. Preserve their original unique audit keys.
		updates = (
			{key_field: value}
			if counts[value] == 1 and row.get(key_field) != value
			else {}
		)
		if additional:
			updates.update({
				fieldname: fieldvalue
				for fieldname, fieldvalue in additional(row).items()
				if row.get(fieldname) != fieldvalue
			})
		if updates:
			frappe.db.set_value(doctype, row.name, updates, update_modified=False)


def _rebuild_flow_response_keys():
	doctype = "WhatsApp Core Flow Response"
	if not frappe.db.exists("DocType", doctype):
		return
	for row in frappe.get_all(
		doctype,
		fields=["name", "response_key", "response_type", "flow_instance", "message"],
		limit_page_length=0,
	):
		if row.response_type == "Automation" and row.flow_instance:
			value = f"instance:{row.flow_instance}"
		elif row.response_type == "Meta Submission" and row.message:
			value = f"message:{row.message}"
		else:
			continue
		if row.response_key != value:
			frappe.db.set_value(doctype, row.name, "response_key", value, update_modified=False)


def _rebuild_contact_summary_keys():
	doctype = "WhatsApp Core Contact Summary"
	if not frappe.db.exists("DocType", doctype):
		return
	for row in frappe.get_all(
		doctype,
		fields=["name", "summary_key", "scope_type", "scope_key", "identity", "source_identities"],
		limit_page_length=0,
	):
		if row.scope_type == "Identity" and row.identity:
			scope_key = row.identity
		else:
			try:
				identities = json.loads(row.source_identities or "[]")
			except (TypeError, ValueError):
				identities = []
			if not identities:
				continue
			scope_key = "group:" + _sha("|".join(sorted(identities)))
		value = _sha(f"{row.scope_type}:{scope_key}")
		updates = {}
		if row.scope_key != scope_key:
			updates["scope_key"] = scope_key
		if row.summary_key != value:
			updates["summary_key"] = value
		if updates:
			frappe.db.set_value(doctype, row.name, updates, update_modified=False)


def _sha(value) -> str:
	return hashlib.sha256(str(value).encode()).hexdigest()
