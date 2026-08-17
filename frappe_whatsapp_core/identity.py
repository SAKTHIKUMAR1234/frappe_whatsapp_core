import hashlib
import json
import re

import frappe
from frappe import _
from frappe.model.rename_doc import rename_doc
from frappe.utils import cint, now_datetime

from frappe_whatsapp_core.contact_presentation import present_contacts
from frappe_whatsapp_core.frappe_whatsapp_core.doctype.whatsapp_core_identity_link.whatsapp_core_identity_link import (
	make_identity_link_key,
)
from frappe_whatsapp_core.naming import name_by_key
from frappe_whatsapp_core.permissions import identity_team_condition


BSUID_PATTERN = re.compile(
	r"^[A-Za-z]{2}\.(?:[A-Za-z0-9]{1,128}|ENT\.[A-Za-z0-9]{1,128})$"
)
PARENT_BSUID_PATTERN = re.compile(r"^[A-Za-z]{2}\.ENT\.[A-Za-z0-9]{1,128}$")


def normalize_business_scoped_user_id(value) -> str:
	"""Validate but never rewrite Meta's opaque portfolio-scoped identifier."""
	identifier = str(value or "").strip()
	if not BSUID_PATTERN.fullmatch(identifier):
		frappe.throw(
			_("A valid WhatsApp business-scoped user ID is required."),
			frappe.ValidationError,
		)
	return identifier


def is_business_scoped_user_id(value) -> bool:
	return bool(BSUID_PATTERN.fullmatch(str(value or "").strip()))


def is_parent_business_scoped_user_id(value) -> bool:
	return bool(PARENT_BSUID_PATTERN.fullmatch(str(value or "").strip()))


def get_or_create_identity(value, resolve=True, *, scope=None, aliases=None):
	"""Return one typed WhatsApp identity, scoped where Meta scopes BSUIDs.

	Phone and BSUID values are aliases only when Meta supplies them in the same
	signed event. A BSUID is never digit-normalized and can never collide across
	two Core channels/business portfolios.
	"""
	aliases = dict(aliases or {})
	raw = str(value or "").strip()
	raw_parent = raw if is_parent_business_scoped_user_id(raw) else ""
	bsuid = aliases.get("user_id") or (
		raw if is_business_scoped_user_id(raw) and not raw_parent else ""
	)
	parent_bsuid = str(aliases.get("parent_user_id") or raw_parent).strip()
	has_scoped_id = bool(bsuid or parent_bsuid)
	phone_value = aliases.get("phone") or ("" if has_scoped_id else raw)
	phone = normalize_phone(phone_value)
	if bsuid:
		bsuid = normalize_business_scoped_user_id(bsuid)
	if parent_bsuid:
		parent_bsuid = normalize_business_scoped_user_id(parent_bsuid)
	if has_scoped_id and not scope:
		frappe.throw(
			_("A WhatsApp account scope is required for a business-scoped user ID."),
			frappe.ValidationError,
		)
	if phone and not 7 <= len(phone) <= 15:
		frappe.throw(_("A valid phone number is required."), frappe.ValidationError)
	if not has_scoped_id and not phone:
		frappe.throw(
			_("A valid phone number or WhatsApp business-scoped user ID is required."),
			frappe.ValidationError,
		)

	identity_names = {
		name
		for name in (
			_alias_identity("BSUID", bsuid, scope) if bsuid else None,
			_alias_identity("Parent BSUID", parent_bsuid, scope) if parent_bsuid else None,
			_alias_identity("Phone", phone, scope) if phone and scope else None,
		)
		if name
	}
	legacy_key = hashlib.sha256(f"whatsapp:{phone}".encode()).hexdigest() if phone else None
	shared_legacy = None
	legacy_name = name_by_key("WhatsApp Core Identity", legacy_key)
	if legacy_name:
		legacy = frappe.get_doc("WhatsApp Core Identity", legacy_name)
		legacy_scope = getattr(legacy, "identity_scope", None)
		if not legacy_scope and has_scoped_id:
			# Legacy phone identities were global.  A single identity may therefore
			# back current or future conversations for several accounts.  Never
			# convert that global row into one account's BSUID.  Split/rebind only
			# the current account and retain the phone identity for other accounts.
			shared_legacy = legacy.name
		elif legacy_scope == scope:
			identity_names.add(legacy.name)
	if len(identity_names) > 1:
		frappe.throw(
			_("WhatsApp identifiers are already assigned to different contacts."),
			frappe.ValidationError,
		)

	identity = frappe.get_doc("WhatsApp Core Identity", identity_names.pop()) if identity_names else None
	if not identity:
		key_material = (
			f"whatsapp:bsuid:{scope}:{bsuid or parent_bsuid}"
			if has_scoped_id
			else f"whatsapp:{phone}"
		)
		identity_key = hashlib.sha256(key_material.encode()).hexdigest()
		identity_name = name_by_key("WhatsApp Core Identity", identity_key)
		if identity_name:
			identity = frappe.get_doc("WhatsApp Core Identity", identity_name)
		else:
			identity = frappe.get_doc({
				"doctype": "WhatsApp Core Identity",
				"identity_key": identity_key,
				"identity_type": "WhatsApp",
				"identifier_type": "BSUID" if has_scoped_id else "Phone",
				"identity_scope": scope if has_scoped_id else None,
				"normalized_value": bsuid or parent_bsuid or phone,
				"display_value": _identity_display_value(aliases, phone, bsuid or parent_bsuid),
				"provider": "meta",
				"status": "Active",
				"resolution_status": "Unresolved",
			})
			try:
				identity.insert(ignore_permissions=True)
			except (frappe.DuplicateEntryError, frappe.UniqueValidationError):
				identity = frappe.get_doc(
					"WhatsApp Core Identity",
					name_by_key("WhatsApp Core Identity", identity_key),
				)

	_update_whatsapp_identity(
		identity,
		scope=scope,
		bsuid=bsuid,
		parent_bsuid=parent_bsuid,
		phone=phone,
		aliases=aliases,
	)
	if shared_legacy and shared_legacy != identity.name:
		_rebind_legacy_scope_conversations(shared_legacy, identity.name, scope)
	for alias_type, alias_value in (
		("BSUID", bsuid),
		("Parent BSUID", parent_bsuid),
		("Phone", phone),
	):
		if alias_value:
			_ensure_alias(identity.name, alias_type, alias_value, scope if has_scoped_id else None)

	if resolve and phone:
		resolve_identity(identity)
	return identity


def _rebind_legacy_scope_conversations(legacy_name, scoped_name, scope):
	"""Move only this account's legacy threads; never mutate the shared identity."""
	canonical_conversation = frappe.db.get_value(
		"WhatsApp Core Conversation",
		{"channel": scope, "remote_identity": scoped_name},
		"name",
		order_by="creation asc",
	)
	for legacy_conversation in frappe.get_all(
		"WhatsApp Core Conversation",
		filters={"channel": scope, "remote_identity": legacy_name},
		pluck="name",
		order_by="creation asc",
	):
		if canonical_conversation:
			rename_doc(
				"WhatsApp Core Conversation",
				legacy_conversation,
				canonical_conversation,
				merge=True,
				ignore_permissions=True,
			)
		else:
			canonical_conversation = _rename_conversation_for_identity(
				legacy_conversation, scoped_name, scope
			)


def _rename_conversation_for_identity(conversation_name, identity_name, scope):
	conversation_key = hashlib.sha256(
		f"{scope}:{identity_name}:active".encode()
	).hexdigest()
	frappe.db.set_value(
		"WhatsApp Core Conversation",
		conversation_name,
		{"conversation_key": conversation_key, "remote_identity": identity_name},
		update_modified=False,
	)
	return conversation_name


def _identity_display_value(aliases, phone, bsuid):
	profile = aliases.get("profile") if isinstance(aliases.get("profile"), dict) else {}
	return str(
		aliases.get("username")
		or profile.get("username")
		or profile.get("name")
		or aliases.get("profile_name")
		or phone
		or bsuid
	).strip()[:140]


def _update_whatsapp_identity(identity, *, scope, bsuid, parent_bsuid, phone, aliases):
	# Status callbacks for the same recipient can be projected by independent
	# workers at the same time.  Frappe's optimistic ``modified`` check correctly
	# rejects a stale Document, but a provider receipt must not become a permanent
	# failed event merely because another receipt enriched the same identity first.
	# Serialize the merge and reload only after owning the row so every callback
	# starts from the latest committed attributes.
	frappe.db.sql(
		"""
		SELECT name
		FROM `tabWhatsApp Core Identity`
		WHERE name = %s
		FOR UPDATE
		""",
		(identity.name,),
	)
	identity.reload()
	attributes = identity.attributes or {}
	if isinstance(attributes, str):
		attributes = frappe.parse_json(attributes)
	if not isinstance(attributes, dict):
		attributes = {}
	if bsuid:
		attributes["business_scoped_user_id"] = bsuid
	if parent_bsuid:
		attributes["parent_business_scoped_user_id"] = parent_bsuid
	if phone:
		phone_aliases = list(attributes.get("phone_aliases") or [])
		if phone not in phone_aliases:
			phone_aliases.append(phone)
		attributes["phone_aliases"] = phone_aliases
	profile = aliases.get("profile") if isinstance(aliases.get("profile"), dict) else {}
	for key, value in {
		"username": aliases.get("username") or profile.get("username"),
		"profile_name": aliases.get("profile_name") or profile.get("name"),
	}.items():
		if value not in (None, ""):
			attributes[key] = str(value)
	if bsuid:
		identity.identifier_type = "BSUID"
		identity.identity_scope = scope
		identity.normalized_value = bsuid
	elif parent_bsuid and not attributes.get("business_scoped_user_id"):
		identity.identifier_type = "BSUID"
		identity.identity_scope = scope
		identity.normalized_value = parent_bsuid
	elif not getattr(identity, "identifier_type", None):
		identity.identifier_type = "Phone"
	identity.attributes = attributes
	display = _identity_display_value(aliases, phone, bsuid)
	if display:
		identity.display_value = display
	identity.save(ignore_permissions=True)


def _alias_key(alias_type, alias_value, scope=None):
	return hashlib.sha256(
		f"meta:{scope or '*'}:{alias_type}:{alias_value}".encode()
	).hexdigest()


def _alias_identity(alias_type, alias_value, scope=None):
	if not alias_value:
		return None
	return frappe.db.get_value(
		"WhatsApp Core Identity Alias",
		{"alias_key": _alias_key(alias_type, alias_value, scope)},
		"identity",
	)


def _ensure_alias(identity, alias_type, alias_value, scope=None):
	alias_key = _alias_key(alias_type, alias_value, scope)
	existing = frappe.db.get_value(
		"WhatsApp Core Identity Alias", {"alias_key": alias_key}, "identity"
	)
	if existing and existing != identity:
		frappe.throw(
			_("WhatsApp identifier is already assigned to another contact."),
			frappe.ValidationError,
		)
	if existing:
		return alias_key
	try:
		frappe.get_doc({
			"doctype": "WhatsApp Core Identity Alias",
			"alias_key": alias_key,
			"identity": identity,
			"alias_type": alias_type,
			"identity_scope": scope,
			"alias_value": alias_value,
		}).insert(ignore_permissions=True)
	except (frappe.DuplicateEntryError, frappe.UniqueValidationError):
		if _alias_identity(alias_type, alias_value, scope) != identity:
			raise
	return alias_key


def link_business_scoped_user_id_change(
	old_user_id,
	new_user_id,
	*,
	scope,
	aliases=None,
):
	"""Atomically retain the old thread when Meta rotates a user's BSUID."""
	old_user_id = normalize_business_scoped_user_id(old_user_id)
	new_user_id = normalize_business_scoped_user_id(new_user_id)
	old_identity = _alias_identity("BSUID", old_user_id, scope)
	new_identity = _alias_identity("BSUID", new_user_id, scope)
	if not old_identity:
		old_key = hashlib.sha256(
			f"whatsapp:bsuid:{scope}:{old_user_id}".encode()
		).hexdigest()
		old_identity = name_by_key("WhatsApp Core Identity", old_key)
	if not new_identity:
		new_key = hashlib.sha256(
			f"whatsapp:bsuid:{scope}:{new_user_id}".encode()
		).hexdigest()
		new_identity = name_by_key("WhatsApp Core Identity", new_key)

	canonical_name = old_identity or new_identity
	if not canonical_name:
		canonical_name = get_or_create_identity(
			old_user_id,
			resolve=False,
			scope=scope,
			aliases={**(aliases or {}), "user_id": old_user_id},
		).name
	if old_identity and new_identity and old_identity != new_identity:
		_merge_scoped_identity(new_identity, old_identity, scope)
		canonical_name = old_identity

	# Explicit provider evidence authorizes rebinding the new/old aliases. Generic
	# inbound coalescing remains fail-closed on the same collision.
	for identifier in (old_user_id, new_user_id):
		key = _alias_key("BSUID", identifier, scope)
		alias_name = name_by_key("WhatsApp Core Identity Alias", key)
		if alias_name:
			frappe.db.set_value(
				"WhatsApp Core Identity Alias", alias_name, "identity", canonical_name,
				update_modified=False,
			)
		else:
			_ensure_alias(canonical_name, "BSUID", identifier, scope)
	canonical = frappe.get_doc("WhatsApp Core Identity", canonical_name)
	attributes = canonical.attributes or {}
	if isinstance(attributes, str):
		attributes = frappe.parse_json(attributes)
	if not isinstance(attributes, dict):
		attributes = {}
	current_user_id = str(attributes.get("business_scoped_user_id") or "").strip()
	if not current_user_id:
		current_user_id = new_user_id
	elif current_user_id == old_user_id:
		current_user_id = new_user_id
	# If current is neither edge of this update, the new ID is already a
	# predecessor alias on a later provider-confirmed chain (for example B->C
	# arrived before A->B on another relay lane). Preserve the later current ID.
	previous = list(attributes.get("previous_business_scoped_user_ids") or [])
	if old_user_id != new_user_id and old_user_id not in previous:
		previous.append(old_user_id)
	if new_user_id != current_user_id and new_user_id not in previous:
		previous.append(new_user_id)
	attributes["previous_business_scoped_user_ids"] = previous
	attributes["business_scoped_user_id"] = current_user_id
	canonical.identifier_type = "BSUID"
	canonical.identity_scope = scope
	canonical.normalized_value = current_user_id
	canonical.attributes = attributes
	canonical.save(ignore_permissions=True)
	alias_data = dict(aliases or {})
	parent_bsuid = str(alias_data.get("parent_user_id") or "").strip()
	previous_parent_bsuid = str(alias_data.get("previous_parent_user_id") or "").strip()
	existing_parent_bsuid = str(
		attributes.get("parent_business_scoped_user_id") or ""
	).strip()
	effective_parent_bsuid = (
		existing_parent_bsuid
		if current_user_id != new_user_id
		else parent_bsuid
	)
	phone = normalize_phone(alias_data.get("phone"))
	if phone and not 7 <= len(phone) <= 15:
		frappe.throw(_("A valid phone number is required."), frappe.ValidationError)
	_update_whatsapp_identity(
		canonical,
		scope=scope,
		bsuid=current_user_id,
		parent_bsuid=(
			normalize_business_scoped_user_id(effective_parent_bsuid)
			if effective_parent_bsuid
			else ""
		),
		phone=phone,
		aliases=alias_data,
	)
	if parent_bsuid:
		_ensure_alias(canonical.name, "Parent BSUID", parent_bsuid, scope)
	if previous_parent_bsuid:
		previous_parent_bsuid = normalize_business_scoped_user_id(previous_parent_bsuid)
		_ensure_alias(canonical.name, "Parent BSUID", previous_parent_bsuid, scope)
	if phone:
		_ensure_alias(canonical.name, "Phone", phone, scope)
	return canonical


def _merge_scoped_identity(secondary_name, canonical_name, scope):
	if secondary_name == canonical_name:
		return
	canonical = frappe.get_doc("WhatsApp Core Identity", canonical_name)
	secondary = frappe.get_doc("WhatsApp Core Identity", secondary_name)
	canonical.attributes = _merge_identity_attributes(
		canonical.attributes, secondary.attributes
	)
	canonical.save(ignore_permissions=True)
	canonical_conversation = frappe.db.get_value(
		"WhatsApp Core Conversation",
		{"channel": scope, "remote_identity": canonical_name},
		"name",
		order_by="creation asc",
	)
	for secondary_conversation in frappe.get_all(
		"WhatsApp Core Conversation",
		filters={"channel": scope, "remote_identity": secondary_name},
		pluck="name",
		order_by="creation asc",
	):
		if canonical_conversation:
			rename_doc(
				"WhatsApp Core Conversation",
				secondary_conversation,
				canonical_conversation,
				merge=True,
				ignore_permissions=True,
			)
		else:
			canonical_conversation = _rename_conversation_for_identity(
				secondary_conversation, canonical_name, scope
			)
	frappe.db.set_value(
		"WhatsApp Core Identity Alias",
		{"identity": secondary_name},
		"identity",
		canonical_name,
		update_modified=False,
	)
	frappe.db.set_value(
		"WhatsApp Core Identity", secondary_name, "status", "Superseded",
		update_modified=False,
	)


def _merge_identity_attributes(canonical_value, secondary_value):
	def as_dict(value):
		if isinstance(value, str):
			value = frappe.parse_json(value)
		return dict(value) if isinstance(value, dict) else {}

	canonical = as_dict(canonical_value)
	secondary = as_dict(secondary_value)
	for key, value in secondary.items():
		if key not in canonical or canonical[key] in (None, "", [], {}):
			canonical[key] = value
	canonical["phone_aliases"] = list(dict.fromkeys([
		*(canonical.get("phone_aliases") or []),
		*(secondary.get("phone_aliases") or []),
	]))
	preferences = dict(canonical.get("user_preferences") or {})
	for category, candidate in (secondary.get("user_preferences") or {}).items():
		existing = preferences.get(category)
		if not existing or _identity_preference_wins(candidate, existing):
			preferences[category] = candidate
	if preferences:
		canonical["user_preferences"] = preferences
	return canonical


def _identity_preference_wins(candidate, existing):
	try:
		candidate_timestamp = float((candidate or {}).get("timestamp"))
		existing_timestamp = float((existing or {}).get("timestamp"))
	except (TypeError, ValueError):
		return (
			str((candidate or {}).get("value") or "").upper() == "STOP"
			and str((existing or {}).get("value") or "").upper() != "STOP"
		)
	if candidate_timestamp != existing_timestamp:
		return candidate_timestamp > existing_timestamp
	return (
		str((candidate or {}).get("value") or "").upper() == "STOP"
		and str((existing or {}).get("value") or "").upper() != "STOP"
	)
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
		fields=[
			"name",
			"identity_source",
			"reference_doctype",
			"reference_name",
			"display_name",
		],
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
	identity_phone = _identity_phone(identity)
	if not identity_phone:
		return []
	if "." not in phone_field:
		query_filters = dict(filters)
		query_filters[phone_field] = [
			"in",
			phone_candidates(identity_phone),
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
					phone_candidates(identity_phone),
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


def _identity_phone(identity):
	if getattr(identity, "identifier_type", None) != "BSUID":
		phone = normalize_phone(identity.normalized_value)
		return phone if 7 <= len(phone) <= 15 else ""
	attributes = identity.attributes or {}
	if isinstance(attributes, str):
		attributes = frappe.parse_json(attributes)
	if not isinstance(attributes, dict):
		return ""
	aliases = attributes.get("phone_aliases") or []
	return normalize_phone(aliases[-1]) if aliases else ""


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
		fields=["name", "link_key"],
	)
	stale_links = [
		link.name
		for link in existing_links
		if link.link_key not in link_keys
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
		link_name = frappe.db.get_value(
			"WhatsApp Core Identity Link",
			{
				"identity": identity.name,
				"identity_source": source.name,
				"reference_doctype": match["reference_doctype"],
				"reference_name": match["reference_name"],
			},
			"name",
		) or name_by_key("WhatsApp Core Identity Link", link_key)
		if link_name:
			link = frappe.get_doc(
				"WhatsApp Core Identity Link",
				link_name,
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
		display_name = str(primary.display_name or "").strip()
		if display_name:
			# A verified business source is more authoritative than a provider
			# profile or the raw phone used to create an outbound conversation.
			identity.display_value = display_name[:140]
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
