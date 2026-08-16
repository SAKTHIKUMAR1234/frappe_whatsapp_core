"""Install the role boundary used by the company-facing Core application."""

import frappe

CORE_ROLES = (
	"WhatsApp User",
	"WhatsApp Flow User",
	"WhatsApp Manager",
)

TRANSPORT_SERVICE_ROLE = "WhatsApp Core Transport Service"
TEMPLATE_SERVICE_ROLE = "WhatsApp Core Template Service"
FLOW_SERVICE_ROLE = "WhatsApp Core Flow Service"
MACHINE_SERVICE_ROLES = (
	TRANSPORT_SERVICE_ROLE,
	TEMPLATE_SERVICE_ROLE,
	FLOW_SERVICE_ROLE,
)

LEGACY_ROLE_MAP = {
	"WhatsApp Core Admin": "WhatsApp Manager",
	"WhatsApp Core Manager": "WhatsApp Manager",
	"WhatsApp Core Agent": "WhatsApp User",
	"WhatsApp Core Analyst": "WhatsApp User",
}


def ensure_core_roles():
	for role_name in CORE_ROLES:
		if frappe.db.exists("Role", role_name):
			continue
		frappe.get_doc(
			{
				"doctype": "Role",
				"role_name": role_name,
				"desk_access": 1,
				"is_custom": 0,
			}
		).insert(ignore_permissions=True)
	for role_name in MACHINE_SERVICE_ROLES:
		if frappe.db.exists("Role", role_name):
			continue
		frappe.get_doc(
			{
				"doctype": "Role",
				"role_name": role_name,
				"desk_access": 0,
				"is_custom": 0,
			}
		).insert(ignore_permissions=True)
	_migrate_legacy_roles()


def ensure_core_setup():
	"""Install idempotent Core-owned roles, categories, and optional AI action."""
	ensure_core_roles()
	from frappe_whatsapp_core.message_categories import ensure_default_categories

	ensure_default_categories()
	from frappe_whatsapp_core.ai_summary_setup import ensure_whatsapp_summary_i2a_action

	ensure_whatsapp_summary_i2a_action()


def _migrate_legacy_roles():
	"""Collapse the former four-role model into the two public Core roles."""
	for legacy_role, target_role in LEGACY_ROLE_MAP.items():
		for row in frappe.get_all(
			"Has Role",
			filters={"role": legacy_role},
			fields=["name", "parent", "parenttype", "parentfield"],
		):
			duplicate = frappe.db.exists(
				"Has Role",
				{
					"parent": row.parent,
					"parenttype": row.parenttype,
					"parentfield": row.parentfield,
					"role": target_role,
				},
			)
			if duplicate:
				frappe.db.delete("Has Role", {"name": row.name})
			else:
				frappe.db.set_value("Has Role", row.name, "role", target_role, update_modified=False)
		if frappe.db.exists("Role", legacy_role):
			try:
				frappe.delete_doc("Role", legacy_role, force=True, ignore_permissions=True)
			except frappe.LinkExistsError:
				frappe.db.set_value("Role", legacy_role, "disabled", 1, update_modified=False)
	frappe.clear_cache()
