"""Install the role boundary used by the company-facing Core application."""

import frappe

CORE_ROLES = (
	"WhatsApp User",
	"WhatsApp Manager",
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
	_migrate_legacy_roles()


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
