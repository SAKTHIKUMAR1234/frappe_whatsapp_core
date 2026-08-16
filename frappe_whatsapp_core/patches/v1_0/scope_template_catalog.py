"""Make legacy template projections fail closed until their account is known."""

import frappe

from frappe_whatsapp_core.template_catalog import scoped_template_key


def execute():
	if not frappe.db.table_exists("WhatsApp Core Template"):
		return

	settings = frappe.get_single("WhatsApp Core Settings")
	mappings = [
		(str(row.account_name or "").strip(), str(row.channel or "").strip())
		for row in settings.accounts
		if row.account_name and row.channel
	]
	unresolved = []
	for row in frappe.get_all(
		"WhatsApp Core Template",
		fields=["name", "template_name", "language_code", "account_name", "channel"],
		limit_page_length=100000,
	):
		account_name = str(row.account_name or "").strip()
		channel = str(row.channel or "").strip()
		candidates = [
			mapping
			for mapping in mappings
			if (not account_name or mapping[0] == account_name)
			and (not channel or mapping[1] == channel)
		]
		if not account_name or not channel:
			if len(candidates) != 1:
				frappe.db.set_value(
					"WhatsApp Core Template", row.name, "enabled", 0, update_modified=False
				)
				unresolved.append(row.name)
				continue
			account_name, channel = candidates[0]
			frappe.db.set_value(
				"WhatsApp Core Template",
				row.name,
				{"account_name": account_name, "channel": channel},
				update_modified=False,
			)
		elif (account_name, channel) not in mappings:
			frappe.db.set_value(
				"WhatsApp Core Template", row.name, "enabled", 0, update_modified=False
			)
			unresolved.append(row.name)
			continue
		new_name = scoped_template_key(
			account_name, row.template_name, row.language_code or "en"
		)
		if row.name == new_name:
			continue
		if frappe.db.exists("WhatsApp Core Template", new_name):
			frappe.db.set_value(
				"WhatsApp Core Template", row.name, "enabled", 0, update_modified=False
			)
			unresolved.append(row.name)
			continue
		frappe.rename_doc(
			"WhatsApp Core Template", row.name, new_name, force=True, merge=False
		)

	if unresolved:
		frappe.log_error(
			title="WhatsApp template account migration requires review",
			message=(
				"Disabled account-ambiguous template projections: "
				+ ", ".join(unresolved[:100])
			),
		)
