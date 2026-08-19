"""Guarded operator helpers for a clean WhatsApp Core cutover.

These helpers are intentionally not whitelisted.  They are bench-only tools for
operators who have already taken a site backup and need to remove runtime/test
data without touching transport credentials or installed solution metadata.
"""

from __future__ import annotations

import frappe
from frappe.utils import cint

from frappe_whatsapp_core.network_security import validate_service_origin
from frappe_whatsapp_core.permissions import (
	TRANSPORT_CAPABILITY_ROLES,
	is_dedicated_transport_user,
)
from frappe_whatsapp_core.product import product_manifest


CORE_RUNTIME_DOCTYPES = (
	"WhatsApp Core Group Receipt",
	"WhatsApp Core Group Member",
	"WhatsApp Core Campaign Recipient",
	"WhatsApp Core Flow Step Run",
	"WhatsApp Core Flow Response",
	"WhatsApp Core Flow Instance",
	"WhatsApp Core Topic Message",
	"WhatsApp Core Conversation Topic",
	"WhatsApp Core Message Read",
	"WhatsApp Core Message Bookmark",
	"WhatsApp Core Message Category Assignment",
	"WhatsApp Core Message Insight",
	"WhatsApp Core Conversation Read",
	"WhatsApp Core Contact Summary",
	"WhatsApp Core Party Binding",
	"WhatsApp Core Identity Link",
	"WhatsApp Core Team Contact",
	"WhatsApp Core Team Member",
	"WhatsApp Core Handler Run",
	"WhatsApp Core Call",
	"WhatsApp Core Case",
	"WhatsApp Core Group",
	"WhatsApp Core Campaign",
	"WhatsApp Core Flow Trigger",
	"WhatsApp Core Flow Version",
	"WhatsApp Core Flow",
	"WhatsApp Core Meta Flow Exchange",
	"WhatsApp Core Summary Period",
	"WhatsApp Core MCP Invocation",
	"WhatsApp Core Message",
	"WhatsApp Core Conversation",
	"WhatsApp Core Team",
	"WhatsApp Core Template",
	"WhatsApp Core Identity Alias",
	"WhatsApp Core Identity",
	"WhatsApp Core Event",
)

LEGACY_RUNTIME_DOCTYPES = (
	"WhatsApp Poll Response",
	"WhatsApp AI Escalation",
	"WhatsApp AI Bot Log",
	"WhatsApp Webhook Log",
	"AI WhatsApp Queue",
	"Personal WhatsApp Queue",
	"WhatsApp Bulk Message",
	"WhatsApp Poll",
	"Template Wiring",
	"WhatsApp Message",
	"WhatsApp Template",
	"WhatsApp Contact",
	"Personal WhatsApp Account",
	"WhatsApp Account",
)

TEST_USERS = (
	"whatsapp.e2e@local.test",
	"whatsapp.reader@local.test",
)


def production_preflight() -> dict:
	"""Return a read-only, secret-free Core production readiness report.

	This is a bench/operator gate, not a live Meta test. It deliberately performs
	no HTTP requests and changes no state, so it can run safely before maintenance
	mode is lifted. Integration's ``run_production_acceptance`` and the live Meta
	canary remain separate mandatory gates.
	"""
	checks = []
	settings = frappe.get_single("WhatsApp Core Settings")

	schema_ready, schema_detail = _identity_schema_status()
	_add_check(
		checks,
		"identity_schema",
		"BSUID identity schema",
		schema_ready,
		schema_detail,
	)

	_add_check(
		checks,
		"core_enabled",
		"Core enabled",
		bool(settings.enabled),
		"WhatsApp Core is enabled" if settings.enabled else "Enable WhatsApp Core",
	)
	_add_check(
		checks,
		"outbound_enabled",
		"Outbound enabled",
		bool(settings.enabled and settings.outbound_enabled),
		(
			"Outbound delivery is enabled"
			if settings.enabled and settings.outbound_enabled
			else "Enable Core and outbound delivery"
		),
	)

	try:
		hub_origin = validate_service_origin(settings.hub_url, label="Hub HTTPS origin")
		hub_ready = bool(hub_origin)
		hub_detail = hub_origin or "Hub HTTPS origin is not configured"
	except Exception as exc:
		hub_origin = ""
		hub_ready = False
		hub_detail = _safe_detail(exc)
	_add_check(checks, "hub_origin", "Hub HTTPS origin", hub_ready, hub_detail)

	_add_check(
		checks,
		"data_plane",
		"Outbound data plane",
		hub_ready,
		(
			f"Hub-managed Frappe gateway: {hub_origin}"
			if hub_ready
			else "A valid Hub origin is required for the managed gateway"
		),
	)

	credentials_ready = bool(
		settings.get_password("api_key", raise_exception=False)
		and settings.get_password("api_secret", raise_exception=False)
	)
	_add_check(
		checks,
		"hub_credentials",
		"Route-scoped Hub credentials",
		credentials_ready,
		(
			"Encrypted API key and secret are configured"
			if credentials_ready
			else "Claim or rotate the dedicated Hub Site credential"
		),
	)

	account_rows = list(settings.accounts or [])
	channels = [str(row.channel or "").strip() for row in account_rows]
	accounts = [str(row.account_name or "").strip() for row in account_rows]
	mapping_ready = bool(
		account_rows
		and all(channels)
		and all(accounts)
		and len(channels) == len(set(channels))
		and len(accounts) == len(set(accounts))
		and sum(bool(row.is_default) for row in account_rows) <= 1
	)
	_add_check(
		checks,
		"account_mappings",
		"Exact channel/account mappings",
		mapping_ready,
		(
			f"{len(account_rows)} unique mapping(s)"
			if mapping_ready
			else "Configure at least one unique channel and Hub account mapping"
		),
	)

	invalid_channels = []
	for channel in channels:
		if not channel:
			continue
		if not frappe.db.exists("WhatsApp Core Channel", channel):
			invalid_channels.append(f"{channel} (missing)")
			continue
		channel_state = frappe.db.get_value(
			"WhatsApp Core Channel", channel, ["enabled", "phone_number_id"], as_dict=True
		) or {}
		if not channel_state.get("enabled") or not channel_state.get("phone_number_id"):
			invalid_channels.append(f"{channel} (disabled or missing phone ID)")
	_add_check(
		checks,
		"channels",
		"Mapped Core channels",
		bool(channels and not invalid_channels),
		(
			f"{len(channels)} enabled channel(s) have provider phone IDs"
			if channels and not invalid_channels
			else "; ".join(invalid_channels) or "No mapped channel is configured"
		),
	)

	for capability, role in TRANSPORT_CAPABILITY_ROLES.items():
		users = frappe.get_all(
			"Has Role",
			filters={
				"role": role,
				"parenttype": "User",
				"parentfield": "roles",
			},
			pluck="parent",
			limit_page_length=100,
		)
		valid_users = sorted({
			user for user in users
			if is_dedicated_transport_user(user, capability=capability)
		})
		if capability == "template":
			bindings = [
				str(row.template_service_user or "").strip()
				for row in account_rows
			]
			identity_ready = bool(
				account_rows
				and all(bindings)
				and set(bindings) == set(valid_users)
			)
			detail = (
				f"{len(set(bindings))} account-bound dedicated Website User(s) use {role}"
				if identity_ready
				else "Bind every Hub account to the configured valid Core service Website User"
			)
		else:
			identity_ready = len(valid_users) == 1
			detail = (
				f"One dedicated Website User is bound to {role}"
				if identity_ready
				else f"Expected exactly one valid {role} identity; found {len(valid_users)}"
			)
		_add_check(
			checks,
			f"service_identity:{capability}",
			f"{capability.title()} service identity",
			identity_ready,
			detail,
		)

	failed = [check for check in checks if not check["ready"]]
	return {
		"site": frappe.local.site,
		"product": product_manifest(),
		"ready": not failed,
		"passed": len(checks) - len(failed),
		"failed": len(failed),
		"total": len(checks),
		"checks": checks,
		"live_meta_canary_required": True,
	}


def _add_check(checks, key, component, ready, detail):
	checks.append({
		"key": key,
		"component": component,
		"ready": bool(ready),
		"detail": str(detail or "")[:500],
	})


def _safe_detail(error) -> str:
	return str(error or "Unknown error").replace("\n", " ")[:500]


def _identity_schema_status() -> tuple[bool, str]:
	"""Verify the physical BSUID schema needed before the first webhook arrives."""
	required = {
		"WhatsApp Core Identity": {"identifier_type", "identity_scope"},
		"WhatsApp Core Identity Alias": {
			"alias_key",
			"identity",
			"alias_type",
			"identity_scope",
			"alias_value",
		},
		"WhatsApp Core Message": {"provider_template_id"},
		"WhatsApp Core Template": {
			"account_name",
			"channel",
			"components",
			"correct_category",
			"message_send_ttl_seconds",
			"parameter_format",
			"status_reason",
			"template_source",
		},
		"WhatsApp Core Hub Account": {"template_service_user"},
	}
	try:
		for doctype, fields in required.items():
			if not frappe.db.table_exists(doctype):
				return False, f"Run migrate: {doctype} table is missing"
			columns = set(frappe.db.get_table_columns(doctype) or [])
			missing = sorted(fields - columns)
			if missing:
				return False, f"Run migrate: {doctype} is missing {', '.join(missing)}"
		if not _has_exact_unique_index("WhatsApp Core Identity Alias", "alias_key"):
			return False, "Run migrate: Identity Alias alias_key UNIQUE index is missing"
		return True, "Identity, template, alias, and provider status schema are ready"
	except Exception as exc:
		return False, _safe_detail(exc)


def _has_exact_unique_index(doctype: str, fieldname: str) -> bool:
	table_name = f"tab{doctype}"
	db_type = str(getattr(frappe.db, "db_type", "") or "").lower()
	if db_type in {"mariadb", "mysql"}:
		rows = frappe.db.sql(
			"""
			SELECT index_name, GROUP_CONCAT(column_name ORDER BY seq_in_index) AS columns
			FROM information_schema.statistics
			WHERE table_schema = DATABASE() AND table_name = %s AND non_unique = 0
			GROUP BY index_name
			""",
			(table_name,),
			as_dict=True,
		)
		return any(
			str(row.get("columns") or "").strip() == fieldname for row in rows
		)
	if db_type in {"postgres", "postgresql"}:
		rows = frappe.db.sql(
			"""
			SELECT ic.relname AS index_name,
			       array_agg(a.attname ORDER BY keys.ordinality) AS columns
			FROM pg_index AS idx
			JOIN pg_class AS tbl ON tbl.oid = idx.indrelid
			JOIN pg_namespace AS ns ON ns.oid = tbl.relnamespace
			JOIN pg_class AS ic ON ic.oid = idx.indexrelid
			CROSS JOIN LATERAL unnest(idx.indkey) WITH ORDINALITY AS keys(attnum, ordinality)
			JOIN pg_attribute AS a ON a.attrelid = tbl.oid AND a.attnum = keys.attnum
			WHERE ns.nspname = current_schema()
			  AND tbl.relname = %s
			  AND idx.indisunique
			  AND idx.indisvalid
			  AND idx.indisready
			  AND idx.indpred IS NULL
			  AND idx.indexprs IS NULL
			GROUP BY ic.relname
			""",
			(table_name,),
			as_dict=True,
		)
		return any(list(row.get("columns") or []) == [fieldname] for row in rows)
	return False


def clean_cutover_data(expected_site: str, execute: int = 0) -> dict:
	"""Remove runtime data while preserving credentials and product metadata.

	The caller must pass the exact active site name and explicitly set
	``execute=1``.  A call without execute returns the same count plan without
	writing anything.
	"""
	expected_site = str(expected_site or "").strip()
	if not expected_site or expected_site != frappe.local.site:
		frappe.throw(
			f"Cutover target mismatch: active site is {frappe.local.site}",
			frappe.ValidationError,
		)

	core_doctypes = [doctype for doctype in CORE_RUNTIME_DOCTYPES if _doctype_exists(doctype)]
	legacy_doctypes = [doctype for doctype in LEGACY_RUNTIME_DOCTYPES if _doctype_exists(doctype)]
	core_files = (
		frappe.get_all(
			"File",
			filters={"attached_to_doctype": ["like", "WhatsApp Core %"]},
			pluck="name",
			limit_page_length=100000,
		)
		if _doctype_exists("File")
		else []
	)
	preserved_channels = (
		set(
			frappe.get_all(
				"WhatsApp Core Hub Account",
				filters={"channel": ["is", "set"]},
				pluck="channel",
				limit_page_length=1000,
			)
		)
		if _doctype_exists("WhatsApp Core Hub Account")
		else set()
	)
	all_channels = (
		set(
			frappe.get_all(
				"WhatsApp Core Channel",
				pluck="name",
				limit_page_length=100000,
			)
		)
		if _doctype_exists("WhatsApp Core Channel")
		else set()
	)
	test_channels = sorted(all_channels - preserved_channels)

	before = {
		**{doctype: frappe.db.count(doctype) for doctype in core_doctypes},
		**{doctype: frappe.db.count(doctype) for doctype in legacy_doctypes},
		"File (WhatsApp Core attachments)": len(core_files),
		"WhatsApp Core Channel (unreferenced)": len(test_channels),
		"User (known WhatsApp tests)": sum(
			bool(frappe.db.exists("User", user)) for user in TEST_USERS
		),
	}
	result = {
		"site": frappe.local.site,
		"execute": bool(cint(execute)),
		"before": before,
		"preserved": {
			"settings": ["WhatsApp Core Settings", "SD WhatsApp Hub Settings"],
			"channels": sorted(preserved_channels),
			"configuration": [
				"WhatsApp Core Identity Source",
				"WhatsApp Core Message Category",
				"WhatsApp Core Solution",
				"WhatsApp Core Workspace",
				"WhatsApp Core Case Type",
			],
			"legacy_file_metadata": True,
		},
	}
	if not cint(execute):
		return result

	try:
		for doctype in core_doctypes:
			frappe.db.delete(doctype)
		for doctype in legacy_doctypes:
			frappe.db.delete(doctype)
		for name in core_files:
			if frappe.db.exists("File", name):
				frappe.delete_doc("File", name, ignore_permissions=True, force=True)
		if test_channels:
			frappe.db.delete("WhatsApp Core Channel", {"name": ["in", test_channels]})
		for user in TEST_USERS:
			if frappe.db.exists("User", user):
				frappe.delete_doc("User", user, ignore_permissions=True, force=True)
		frappe.db.commit()
	except Exception:
		frappe.db.rollback()
		raise

	result["after"] = {
		**{doctype: frappe.db.count(doctype) for doctype in core_doctypes},
		**{doctype: frappe.db.count(doctype) for doctype in legacy_doctypes},
		"File (WhatsApp Core attachments)": frappe.db.count(
			"File", {"attached_to_doctype": ["like", "WhatsApp Core %"]}
		),
		"WhatsApp Core Channel (unreferenced)": (
			frappe.db.count(
				"WhatsApp Core Channel", {"name": ["in", test_channels]}
			)
			if test_channels
			else 0
		),
		"User (known WhatsApp tests)": sum(
			bool(frappe.db.exists("User", user)) for user in TEST_USERS
		),
	}
	return result


def _doctype_exists(doctype: str) -> bool:
	return bool(
		frappe.db.exists("DocType", doctype) and frappe.db.table_exists(doctype)
	)
