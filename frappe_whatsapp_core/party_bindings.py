"""Business-neutral identity-to-party bindings."""

from __future__ import annotations

import hashlib
import json

import frappe

from frappe_whatsapp_core.naming import name_by_key


def make_binding_key(
	identity: str,
	party_doctype: str,
	party_name: str,
	workspace_key: str | None = None,
) -> str:
	raw = "\x1f".join(
		[
			str(identity or "").strip(),
			str(workspace_key or "").strip(),
			str(party_doctype or "").strip(),
			str(party_name or "").strip(),
		]
	)
	return hashlib.sha256(raw.encode()).hexdigest()


def upsert_party_binding(
	identity: str,
	party_doctype: str,
	party_name: str,
	*,
	workspace_key: str | None = None,
	party_role: str | None = None,
	is_primary: bool = False,
	status: str = "Verified",
	source: str = "Adapter",
	source_reference: str | None = None,
	attributes: dict | str | None = None,
):
	"""Create or update one exact adapter-owned party binding."""
	if not frappe.db.exists("WhatsApp Core Identity", identity):
		frappe.throw(f"WhatsApp Core Identity {identity} does not exist")
	if not frappe.db.exists(party_doctype, party_name):
		frappe.throw(f"{party_doctype} {party_name} does not exist")

	key = make_binding_key(
		identity,
		party_doctype,
		party_name,
		workspace_key,
	)
	record_name = frappe.db.get_value(
		"WhatsApp Core Party Binding",
		{
			"identity": identity,
			"workspace_key": workspace_key or "",
			"party_doctype": party_doctype,
			"party_name": party_name,
		},
		"name",
	) or name_by_key("WhatsApp Core Party Binding", key)
	doc = (
		frappe.get_doc("WhatsApp Core Party Binding", record_name)
		if record_name
		else frappe.new_doc("WhatsApp Core Party Binding")
	)
	doc.identity = identity
	doc.workspace_key = workspace_key or ""
	doc.party_doctype = party_doctype
	doc.party_name = party_name
	doc.party_role = party_role or ""
	doc.is_primary = 1 if is_primary else 0
	doc.status = status
	doc.source = source
	doc.source_reference = source_reference or ""
	doc.attributes = _json_value(attributes)
	if doc.is_new():
		doc.insert(ignore_permissions=True)
	else:
		doc.save(ignore_permissions=True)
	return doc


def get_primary_binding(identity: str, workspace_key: str | None = None):
	filters = {
		"identity": identity,
		"status": "Verified",
		"is_primary": 1,
	}
	if workspace_key is not None:
		filters["workspace_key"] = workspace_key
	name = frappe.db.get_value(
		"WhatsApp Core Party Binding",
		filters,
		"name",
		order_by="modified desc",
	)
	return (
		frappe.get_doc("WhatsApp Core Party Binding", name)
		if name
		else None
	)


def ensure_party_bindings(identity: str, context: dict | None = None) -> list[str]:
	"""Ask installed business adapters to resolve an otherwise unmapped identity."""
	existing = frappe.get_all(
		"WhatsApp Core Party Binding",
		filters={"identity": identity, "status": "Verified"},
		pluck="name",
	)
	if existing:
		return existing

	created = []
	for resolver_path in frappe.get_hooks("whatsapp_core_party_resolvers"):
		resolver = frappe.get_attr(resolver_path)
		result = resolver(identity=identity, context=context or {})
		if not result:
			continue
		bindings = result if isinstance(result, list) else [result]
		for binding in bindings:
			if not isinstance(binding, dict):
				frappe.throw(
					f"Party resolver {resolver_path} returned an invalid binding"
				)
			doc = upsert_party_binding(identity=identity, **binding)
			created.append(doc.name)
	return created


def _json_value(value: dict | str | None) -> str:
	if isinstance(value, str):
		try:
			parsed = json.loads(value)
		except (TypeError, ValueError):
			frappe.throw("Party binding attributes must be valid JSON")
		if not isinstance(parsed, dict):
			frappe.throw("Party binding attributes must be a JSON object")
		value = parsed
	return json.dumps(
		value or {},
		sort_keys=True,
		separators=(",", ":"),
		ensure_ascii=False,
	)
