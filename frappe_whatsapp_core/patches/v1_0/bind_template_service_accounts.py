import frappe

from frappe_whatsapp_core.permissions import is_dedicated_transport_user


def execute():
	"""Bind legacy template callbacks only when the account/user pair is unambiguous."""
	if not frappe.db.table_exists("WhatsApp Core Hub Account"):
		return
	columns = set(frappe.db.get_table_columns("WhatsApp Core Hub Account") or [])
	if "template_service_user" not in columns:
		return
	accounts = frappe.get_all(
		"WhatsApp Core Hub Account",
		filters={
			"parent": "WhatsApp Core Settings",
			"parenttype": "WhatsApp Core Settings",
			"parentfield": "accounts",
		},
		fields=["name", "template_service_user"],
		limit_page_length=0,
	)
	if len(accounts) != 1 or accounts[0].template_service_user:
		return
	users = frappe.get_all(
		"Has Role",
		filters={
			"role": "WhatsApp Core Template Service",
			"parenttype": "User",
			"parentfield": "roles",
		},
		pluck="parent",
		limit_page_length=0,
	)
	users = sorted({
		user for user in users if is_dedicated_transport_user(user, capability="template")
	})
	if len(users) == 1:
		frappe.db.set_value(
			"WhatsApp Core Hub Account",
			accounts[0].name,
			"template_service_user",
			users[0],
			update_modified=False,
		)
