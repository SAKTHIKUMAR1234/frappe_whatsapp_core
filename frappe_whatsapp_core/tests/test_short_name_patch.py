from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase

from frappe_whatsapp_core.patches.v1_0.shorten_business_key_names import (
	_update_link_field_values_without_hooks,
)


class TestShortNamePatch(FrappeTestCase):
	@patch("frappe_whatsapp_core.patches.v1_0.shorten_business_key_names.frappe.clear_cache")
	@patch("frappe_whatsapp_core.patches.v1_0.shorten_business_key_names.frappe.db.set_value")
	@patch("frappe_whatsapp_core.patches.v1_0.shorten_business_key_names.frappe.db.sql")
	def test_single_links_are_rewritten_without_saving_the_settings_document(
		self, sql, set_value, clear_cache
	):
		_update_link_field_values_without_hooks(
			[
				{
					"parent": "Customer WhatsApp Settings",
					"fieldname": "receipt_template",
					"issingle": 1,
				}
			],
			"receipt-template-en",
			"a1b2c3d4e5",
			"WhatsApp Core Template",
		)

		sql.assert_called_once_with(
			"""UPDATE `tabSingles`
				SET `value` = %s
				WHERE `doctype` = %s AND `field` = %s AND `value` = %s""",
			(
				"a1b2c3d4e5",
				"Customer WhatsApp Settings",
				"receipt_template",
				"receipt-template-en",
			),
		)
		set_value.assert_not_called()
		clear_cache.assert_called_once_with(doctype="Customer WhatsApp Settings")

	@patch("frappe_whatsapp_core.patches.v1_0.shorten_business_key_names.frappe.db.set_value")
	def test_regular_links_are_rewritten_without_modified_timestamp_churn(self, set_value):
		_update_link_field_values_without_hooks(
			[
				{
					"parent": "WhatsApp Core Campaign",
					"fieldname": "template",
					"issingle": 0,
				}
			],
			"receipt-template-en",
			"a1b2c3d4e5",
			"WhatsApp Core Template",
		)

		set_value.assert_called_once_with(
			"WhatsApp Core Campaign",
			{"template": "receipt-template-en"},
			"template",
			"a1b2c3d4e5",
			update_modified=False,
		)
