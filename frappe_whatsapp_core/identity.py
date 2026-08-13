import hashlib
import json

import frappe
from frappe import _
from frappe.utils import cint, now_datetime

from frappe_whatsapp_core.contact_presentation import present_contacts
from frappe_whatsapp_core.frappe_whatsapp_core.doctype.whatsapp_core_identity_link.whatsapp_core_identity_link import (
	make_identity_link_key,
)
from frappe_whatsapp_core.permissions import identity_team_condition


def get_or_create_identity(value, resolve=True):
	"""Return the canonical WhatsApp identity and resolve business links."""
	normalized = normalize_phone(value)
	if not 8 <= len(normalized) <= 15:
		frappe.throw(_("A valid phone number is required."))

	identity_key = hashlib.sha256(
		f"whatsapp:{normalized}".encode()
	).hexdigest()
	if frappe.db.exists("WhatsApp Core Identity", identity_key):
		identity = frappe.get_doc(
			"WhatsApp Core Identity",
			identity_key,
		)
	else:
		identity = frappe.get_doc(
			{
				"doctype": "WhatsApp Core Identity",
				"identity_key": identity_key,
				"identity_type": "WhatsApp",
				"normalized_value": normalized,
				"display_value": value,
				"provider": "meta",
				"status": "Active",
				"resolution_status": "Unresolved",
			}
		)
		try:
			identity.insert(ignore_permissions=True)
		except frappe.DuplicateEntryError:
			identity = frappe.get_doc(
				"WhatsApp Core Identity",
				identity_key,
			)

	if resolve:
		resolve_identity(identity)
	return identity


def resolve_identity(identity):
	"""Resolve one canonical phone against every enabled business source."""
	if isinstance(identity, str):
		identity = frappe.get_doc(
			"WhatsApp Core Identity",
			identity,
		)

	sources = frappe.get_all(
		"WhatsApp Core Identity Source",
		filters={
			"enabled": 1,
			"auto_resolve": 1,
		},
		fields=[
			"name",
			"source_key",
			"source_doctype",
			"priority",
			"phone_field",
			"display_name_field",
			"entity_type_field",
			"filters",
		],
		order_by="priority asc, name asc",
	)
	_deactivate_disabled_source_links(identity)
	updated_links = []
	for source in sources:
		matches = _resolve_source(identity, source)
		updated_links.extend(
			_upsert_matches(identity, source, matches)
		)

	active_links = frappe.get_all(
		"WhatsApp Core Identity Link",
		filters={
			"identity": identity.name,
			"status": "Active",
		},
		fields=["name", "identity_source", "reference_doctype", "reference_name"],
		order_by="creation asc",
	)
	_set_primary_link(identity, active_links, sources)
	unique_references = {
		(link.reference_doctype, link.reference_name)
		for link in active_links
	}
	identity.resolution_status = (
		"Unresolved"
		if not unique_references
		else "Resolved"
		if len(unique_references) == 1
		else "Ambiguous"
	)
	identity.last_resolved_at = now_datetime()
	identity.save(ignore_permissions=True)
	return {
		"identity": identity.name,
		"status": identity.resolution_status,
		"links": [link.name for link in active_links],
		"updated": [link.name for link in updated_links],
	}


def _deactivate_disabled_source_links(identity):
	disabled_sources = frappe.get_all(
		"WhatsApp Core Identity Source",
		filters={"enabled": 0},
		pluck="name",
	)
	if not disabled_sources:
		return
	frappe.db.set_value(
		"WhatsApp Core Identity Link",
		{
			"identity": identity.name,
			"identity_source": ["in", disabled_sources],
			"status": "Active",
		},
		"status",
		"Inactive",
		update_modified=False,
	)


def normalize_phone(value, *, assume_local: bool = False, country_code: str = "91"):
	raw = str(value or "").strip()
	normalized = "".join(
		character
		for character in raw
		if character.isdigit()
	)
	if raw.startswith("00") and normalized.startswith("00"):
		normalized = normalized[2:]
	if assume_local and not raw.startswith(("+", "00")):
		country_code = "".join(character for character in str(country_code or "91") if character.isdigit())
		if normalized.startswith("0") and len(normalized) == 11:
			normalized = normalized[1:]
		if len(normalized) == 10 and country_code:
			normalized = f"{country_code}{normalized}"
	return normalized


def phone_candidates(value):
	"""Return exact-match variants for an E.164 or local phone value."""
	normalized = normalize_phone(value)
	if not normalized:
		return []

	candidates = {
		normalized,
		f"+{normalized}",
	}
	if len(normalized) >= 10:
		local = normalized[-10:]
		candidates.update(
			{
				local,
				f"+{local}",
				f"91{local}",
				f"+91{local}",
			}
		)
	return sorted(candidates)


def contact_options(
	limit: int = 50,
	search: str | None = None,
	include: list[str] | tuple[str, ...] | None = None,
) -> list[dict]:
	"""Return active Core contacts as stable options for every user-facing workflow."""
	limit = max(1, min(cint(limit or 50), 100))
	search = str(search or "").strip()
	include = list(dict.fromkeys(name for name in (include or []) if name))
	scope, scope_values = identity_team_condition("identity.name")
	conditions = [
		"identity.identity_type = 'WhatsApp'",
		"identity.status = 'Active'",
		scope,
	]
	values = {**scope_values, "limit": max(limit, len(include))}
	if search:
		conditions.append(
			"""(
				identity.name LIKE %(search)s
				OR identity.display_value LIKE %(search)s
				OR identity.normalized_value LIKE %(search)s
				OR search_link.display_name LIKE %(search)s
				OR search_link.reference_name LIKE %(search)s
			)"""
		)
		values["search"] = f"%{search}%"
	identities = frappe.db.sql(
		f"""
		SELECT DISTINCT
			identity.name,
			identity.normalized_value,
			identity.display_value,
			identity.primary_link,
			identity.attributes,
			identity.creation
		FROM `tabWhatsApp Core Identity` AS identity
		LEFT JOIN `tabWhatsApp Core Identity Link` AS search_link
			ON search_link.identity = identity.name AND search_link.status = 'Active'
		WHERE {" AND ".join(conditions)}
		ORDER BY identity.creation DESC, identity.name DESC
		LIMIT %(limit)s
		""",
		values,
		as_dict=True,
	)
	known = {row.name for row in identities}
	missing = [name for name in include if name not in known]
	if missing:
		include_scope, include_values = identity_team_condition("identity.name")
		identities.extend(frappe.db.sql(
			f"""
			SELECT identity.name, identity.normalized_value, identity.display_value,
				identity.primary_link, identity.attributes, identity.creation
			FROM `tabWhatsApp Core Identity` AS identity
			WHERE identity.identity_type = 'WhatsApp'
				AND identity.status = 'Active'
				AND identity.name IN %(include)s
				AND {include_scope}
			""",
			{**include_values, "include": tuple(missing)},
			as_dict=True,
		))
	link_names = [row.primary_link for row in identities if row.primary_link]
	links = (
		{
			row.name: row
			for row in frappe.get_all(
				"WhatsApp Core Identity Link",
				filters={"name": ["in", link_names], "status": "Active"},
				fields=["name", "display_name", "reference_doctype", "reference_name"],
				limit_page_length=max(1, len(link_names)),
			)
		}
		if link_names
		else {}
	)
	presentations = present_contacts(
		identities,
		primary_links=links,
		context={"surface": "contact_options"},
	)
	options = []
	for row in identities:
		presentation = presentations.get(row.name) or {}
		options.append(
			{
				"identity": row.name,
				"phone_number": row.normalized_value,
				"label": presentation.get("display_name") or row.normalized_value,
				"reference": presentation.get("reference") or "WhatsApp contact",
				"presentation": presentation,
			}
		)
	return options[: max(limit, len(include))]


def _resolve_source(identity, source):
	resolvers = frappe.get_hooks(
		"whatsapp_core_identity_resolvers"
	) or {}
	resolver_path = (
		resolvers.get(source.source_key)
		if isinstance(resolvers, dict)
		else None
	)
	if isinstance(resolver_path, (list, tuple)):
		registered_paths = list(dict.fromkeys(resolver_path))
		if len(registered_paths) > 1:
			frappe.throw(
				_(
					"Multiple identity resolvers registered for {0}."
				).format(source.source_key)
			)
		resolver_path = (
			registered_paths[0]
			if registered_paths
			else None
		)
	if resolver_path:
		return frappe.get_attr(resolver_path)(
			identity=identity,
			source=source,
		)
	return _resolve_generic_source(identity, source)


def _resolve_generic_source(identity, source):
	filters = (
		json.loads(source.filters)
		if source.filters
		else {}
	)
	phone_field = source.phone_field
	if "." not in phone_field:
		query_filters = dict(filters)
		query_filters[phone_field] = [
			"in",
			phone_candidates(identity.normalized_value),
		]
		names = frappe.get_all(
			source.source_doctype,
			filters=query_filters,
			pluck="name",
		)
	else:
		table_field, child_phone_field = phone_field.split(
			".",
			1,
		)
		source_meta = frappe.get_meta(source.source_doctype)
		table_meta = source_meta.get_field(table_field)
		if not table_meta or table_meta.fieldtype != "Table":
			frappe.throw(
				_(
					"{0} is not a valid child-table phone field."
				).format(phone_field)
			)
		names = frappe.get_all(
			table_meta.options,
			filters={
				"parenttype": source.source_doctype,
				"parentfield": table_field,
				child_phone_field: [
					"in",
					phone_candidates(identity.normalized_value),
				],
			},
			pluck="parent",
		)

	results = []
	for name in dict.fromkeys(names):
		if filters and not frappe.db.exists(
			source.source_doctype,
			{"name": name, **filters},
		):
			continue
		document = frappe.get_cached_doc(
			source.source_doctype,
			name,
		)
		results.append(
			{
				"reference_doctype": source.source_doctype,
				"reference_name": document.name,
				"display_name": (
					document.get(source.display_name_field)
					if source.display_name_field
					else document.name
				),
				"entity_type": (
					document.get(source.entity_type_field)
					if source.entity_type_field
					else ""
				),
				"match_quality": "Exact",
			}
		)
	return results


def _upsert_matches(identity, source, matches):
	matches = matches or []
	link_keys = {
		make_identity_link_key(
			identity.name,
			source.name,
			match.get("reference_doctype"),
			match.get("reference_name"),
		)
		for match in matches
		if match.get("reference_doctype")
		and match.get("reference_name")
	}
	existing_links = frappe.get_all(
		"WhatsApp Core Identity Link",
		filters={
			"identity": identity.name,
			"identity_source": source.name,
			"status": "Active",
		},
		pluck="name",
	)
	stale_links = [
		link_name
		for link_name in existing_links
		if link_name not in link_keys
	]
	if stale_links:
		frappe.db.set_value(
			"WhatsApp Core Identity Link",
			{"name": ["in", stale_links]},
			"status",
			"Inactive",
			update_modified=False,
		)

	links = []
	for match in matches:
		_validate_match(match)
		link_key = make_identity_link_key(
			identity.name,
			source.name,
			match["reference_doctype"],
			match["reference_name"],
		)
		values = {
			"display_name": match.get("display_name"),
			"entity_type": match.get("entity_type"),
			"parent_reference_doctype": match.get(
				"parent_reference_doctype"
			),
			"parent_reference_name": match.get(
				"parent_reference_name"
			),
			"group_reference_doctype": match.get(
				"group_reference_doctype"
			),
			"group_reference_name": match.get(
				"group_reference_name"
			),
			"match_quality": (
				match.get("match_quality")
				or "Exact"
			),
			"attributes": json.dumps(
				match.get("attributes") or {},
				sort_keys=True,
			),
			"status": "Active",
		}
		if frappe.db.exists(
			"WhatsApp Core Identity Link",
			link_key,
		):
			link = frappe.get_doc(
				"WhatsApp Core Identity Link",
				link_key,
			)
			link.update(values)
			link.save(ignore_permissions=True)
		else:
			link = frappe.get_doc(
				{
					"doctype": "WhatsApp Core Identity Link",
					"link_key": link_key,
					"identity": identity.name,
					"identity_source": source.name,
					"reference_doctype": match[
						"reference_doctype"
					],
					"reference_name": match[
						"reference_name"
					],
					**values,
				}
			).insert(ignore_permissions=True)
		links.append(link)
	return links


def _set_primary_link(identity, links, sources):
	priority = {
		source.name: source.priority or 100
		for source in sources
	}
	primary = (
		sorted(
			links,
			key=lambda link: (
				priority.get(
					link.identity_source,
					100,
				),
				link.name,
			),
		)[0]
		if links
		else None
	)
	frappe.db.set_value(
		"WhatsApp Core Identity Link",
		{
			"identity": identity.name,
			"is_primary": 1,
		},
		"is_primary",
		0,
		update_modified=False,
	)
	if primary:
		frappe.db.set_value(
			"WhatsApp Core Identity Link",
			primary.name,
			"is_primary",
			1,
			update_modified=False,
		)
	identity.primary_link = primary.name if primary else None


def _validate_match(match):
	missing = [
		fieldname
		for fieldname in (
			"reference_doctype",
			"reference_name",
		)
		if not match.get(fieldname)
	]
	if missing:
		frappe.throw(
			_("Identity resolver result is missing: ")
			+ ", ".join(missing)
		)
