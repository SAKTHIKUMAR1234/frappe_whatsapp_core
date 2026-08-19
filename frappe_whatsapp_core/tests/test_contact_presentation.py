from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from frappe_whatsapp_core.contact_presentation import present_contacts


class TestContactPresentation(FrappeTestCase):
	def test_core_default_is_business_neutral(self):
		result = present_contacts([
			frappe._dict({
				"name": "IDENTITY-1",
				"normalized_value": "10000000000",
				"display_value": "Default contact",
				"primary_link": None,
			})
		])
		self.assertEqual(result["IDENTITY-1"]["display_name"], "Default contact")
		self.assertEqual(result["IDENTITY-1"]["reference"], "WhatsApp contact")
		self.assertEqual(result["IDENTITY-1"]["secondary_text"], "10000000000")

	def test_phone_alias_hides_opaque_business_scoped_identifier(self):
		result = present_contacts(
			[
				frappe._dict({
					"name": "IDENTITY-1",
					"normalized_value": "IN.816402064840131",
					"display_value": "Member Company",
					"primary_link": None,
				})
			],
			phone_aliases={"IDENTITY-1": "918190986951"},
		)
		self.assertEqual(result["IDENTITY-1"]["secondary_text"], "918190986951")

	@patch("frappe_whatsapp_core.contact_presentation.frappe.get_attr")
	@patch("frappe_whatsapp_core.contact_presentation.frappe.get_hooks")
	def test_business_hook_can_override_presentation_only(self, get_hooks, get_attr):
		get_hooks.return_value = ["business_app.present_contacts"]
		get_attr.return_value = lambda contacts, context: {
			"IDENTITY-1": {
				"display_name": "Retailer · North",
				"badges": ["Retailer"],
				"normalized_value": "must-not-overwrite",
			}
		}
		result = present_contacts([
			frappe._dict({
				"name": "IDENTITY-1",
				"normalized_value": "10000000000",
				"display_value": "Default contact",
				"primary_link": None,
			})
		], context={"surface": "test"})
		self.assertEqual(result["IDENTITY-1"]["display_name"], "Retailer · North")
		self.assertEqual(result["IDENTITY-1"]["badges"], ["Retailer"])
		self.assertNotIn("normalized_value", result["IDENTITY-1"])
