import frappe


def execute():
	if not frappe.db.table_exists("WhatsApp Core Flow"):
		return
	frappe.db.sql(
		"""UPDATE `tabWhatsApp Core Flow`
		SET flow_type = 'Custom Automation'
		WHERE COALESCE(flow_type, '') = ''"""
	)
