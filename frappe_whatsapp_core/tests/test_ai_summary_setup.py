import json
from pathlib import Path
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
		self.frappe_tools_available = (
			"frappe_tools" in frappe.get_installed_apps()
			and frappe.db.exists("DocType", "I2A Action")
			and frappe.db.exists("DocType", "AI Model")
		)
		if self.frappe_tools_available and frappe.db.exists("I2A Action", ACTION_NAME):
			frappe.delete_doc("I2A Action", ACTION_NAME, force=True, ignore_permissions=True)

	def test_core_owns_action_creation_and_settings_link(self):
		if not self.frappe_tools_available:
			self.skipTest("Frappe Tools is not installed on this test site")
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

	def test_core_schema_does_not_link_to_optional_frappe_tools_doctypes(self):
		doctype_root = Path(__file__).resolve().parents[1] / "frappe_whatsapp_core" / "doctype"
		for relative_path, fieldnames in (
			(
				"whatsapp_core_settings/whatsapp_core_settings.json",
				{"summary_i2a_action", "summary_rollup_i2a_action"},
			),
			(
				"whatsapp_core_summary_period/whatsapp_core_summary_period.json",
				{"ai_action"},
			),
		):
			schema = json.loads((doctype_root / relative_path).read_text())
			fields = {row["fieldname"]: row for row in schema["fields"]}
			for fieldname in fieldnames:
				self.assertEqual(fields[fieldname]["fieldtype"], "Data")
				self.assertNotEqual(fields[fieldname].get("options"), "I2A Action")

	def test_core_setup_waits_for_a_compatible_model(self):
		if not self.frappe_tools_available:
			self.skipTest("Frappe Tools is not installed on this test site")
		with patch("frappe_whatsapp_core.ai_summary_setup._select_model", return_value=None):
			result = ensure_whatsapp_summary_i2a_action()

		self.assertEqual(result["status"], "waiting_for_model")
		self.assertEqual(result["reason"], "enabled_json_model_required")
