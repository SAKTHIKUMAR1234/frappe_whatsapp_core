"""Install the role boundary used by the company-facing Core application."""

import frappe

CORE_ROLES = (
	"WhatsApp Core Admin",
	"WhatsApp Core Manager",
	"WhatsApp Core Agent",
	"WhatsApp Core Analyst",
)


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
