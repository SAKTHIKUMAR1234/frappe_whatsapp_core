import frappe


no_cache = 1


def get_context(context):
	context.no_cache = 1
	context.csrf_token = frappe.sessions.get_csrf_token()
	context.boot = {
		"developer_mode": bool(frappe.conf.get("developer_mode")),
		"site": frappe.local.site,
		"socketio_port": frappe.conf.get("socketio_port") or 9000,
		"user": frappe.session.user,
	}
	return context
