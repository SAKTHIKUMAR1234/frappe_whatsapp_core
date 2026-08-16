import frappe

from frappe_whatsapp_core.identity import _ensure_alias, normalize_phone


def execute():
	"""Make existing phone identities addressable through the typed alias ledger."""
	for row in frappe.get_all(
		"WhatsApp Core Identity",
		filters={"identity_type": "WhatsApp"},
		fields=["name", "normalized_value", "identifier_type"],
		limit_page_length=0,
	):
		if row.identifier_type == "BSUID":
			continue
		phone = normalize_phone(row.normalized_value)
		if not 7 <= len(phone) <= 15:
			continue
		if row.identifier_type != "Phone":
			frappe.db.set_value(
				"WhatsApp Core Identity",
				row.name,
				"identifier_type",
				"Phone",
				update_modified=False,
			)
		_ensure_alias(row.name, "Phone", phone)
