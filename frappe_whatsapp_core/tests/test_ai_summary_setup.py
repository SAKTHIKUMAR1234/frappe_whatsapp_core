import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from frappe_whatsapp_core.ai_summary_setup import (
	ACTION_NAME,
	ACTION_OUTPUT_SCHEMA,
	ensure_whatsapp_summary_i2a_action,
)


class TestCoreAISummarySetup(FrappeTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		if frappe.db.exists("I2A Action", ACTION_NAME):
			frappe.delete_doc("I2A Action", ACTION_NAME, force=True, ignore_permissions=True)

	def test_core_owns_action_creation_and_settings_link(self):
		model_name = f"WhatsApp Core Test {frappe.generate_hash(length=8)}"
		frappe.get_doc({
			"doctype": "AI Model",
			"model_label": model_name,
			"enabled": 1,
			"provider": "OpenRouter",
			"model_id": "test/whatsapp-json-model",
			"supports_vision": 1,
			"supports_json_mode": 1,
			"max_tokens": 8192,
		}).insert(ignore_permissions=True)

		first = ensure_whatsapp_summary_i2a_action()
		second = ensure_whatsapp_summary_i2a_action()

		self.assertEqual(first["status"], "created")
		self.assertEqual(second["status"], "updated")
		action = frappe.get_doc("I2A Action", ACTION_NAME)
		self.assertIn("payment screenshot", action.instructions.lower())
		self.assertIn("ordinary social conversation", action.instructions.lower())
		self.assertIn("never invent", action.rules.lower())
		self.assertEqual(
			{row["key"] for row in json.loads(action.output_schema)},
			{row["key"] for row in ACTION_OUTPUT_SCHEMA},
		)
		settings = frappe.get_single("WhatsApp Core Settings")
		self.assertEqual(settings.summary_i2a_action, ACTION_NAME)
		self.assertEqual(settings.enable_ai_summaries, 1)

	def test_core_setup_skips_cleanly_without_frappe_tools(self):
		with patch("frappe.get_installed_apps", return_value=["frappe", "frappe_whatsapp_core"]):
			result = ensure_whatsapp_summary_i2a_action()

		self.assertEqual(result["status"], "skipped")
		self.assertEqual(result["reason"], "frappe_tools_not_installed")

	def test_core_setup_waits_for_a_compatible_model(self):
		with patch("frappe_whatsapp_core.ai_summary_setup._select_model", return_value=None):
			result = ensure_whatsapp_summary_i2a_action()

		self.assertEqual(result["status"], "waiting_for_model")
		self.assertEqual(result["reason"], "enabled_json_model_required")
