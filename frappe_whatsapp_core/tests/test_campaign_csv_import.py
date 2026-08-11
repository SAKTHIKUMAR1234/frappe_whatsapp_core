import json

import frappe
from frappe.tests.utils import FrappeTestCase

from frappe_whatsapp_core.frontend_api import preview_campaign_audience_csv


class TestCampaignCSVImport(FrappeTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		suffix = frappe.generate_hash(length=6)
		self.identity = frappe.get_doc({
			"doctype": "WhatsApp Core Identity",
			"identity_key": f"csv-audience-{suffix}",
			"identity_type": "WhatsApp",
			"normalized_value": f"919876{suffix}",
			"display_value": "CSV Audience Contact",
			"provider": "meta",
			"status": "Active",
		}).insert(ignore_permissions=True)

	def test_csv_resolves_identity_and_template_values(self):
		result = preview_campaign_audience_csv(
			"identity,body_1,body_2,button_0\n"
			f"{self.identity.name},First,Second,details\n"
		)
		self.assertEqual(result["resolved_count"], 1)
		self.assertEqual(result["error_count"], 0)
		recipient = result["recipients"][0]
		self.assertEqual(recipient["identity"], self.identity.name)
		self.assertEqual(
			recipient["personalization"]["components"],
			[
				{
					"type": "body",
					"parameters": [
						{"type": "text", "text": "First"},
						{"type": "text", "text": "Second"},
					],
				},
				{
					"type": "button",
					"sub_type": "url",
					"index": "0",
					"parameters": [{"type": "text", "text": "details"}],
				},
			],
		)

	def test_components_json_and_invalid_rows_are_reported(self):
		components = json.dumps([
			{"type": "body", "parameters": [{"type": "text", "text": "Personal"}]}
		])
		result = preview_campaign_audience_csv(
			"identity,components_json\n"
			f'{self.identity.name},"{components.replace(chr(34), chr(34) * 2)}"\n'
			"missing-contact,[]\n"
		)
		self.assertEqual(result["resolved_count"], 1)
		self.assertEqual(result["error_count"], 1)
		self.assertEqual(result["errors"][0]["row"], 3)
