from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase

from frappe_whatsapp_core.legacy_migration import (
	_delivery_status,
	_direction,
	_provider_id,
	legacy_source_plan,
)


class TestLegacyMigrationContract(FrappeTestCase):
	def test_direction_and_status_are_normalized_across_legacy_apps(self):
		self.assertEqual(_direction("inbound"), "Inbound")
		self.assertEqual(_direction("Outbound"), "Outbound")
		self.assertEqual(_delivery_status("Inbound", "read"), "Received")
		self.assertEqual(_delivery_status("Outbound", "delivered"), "Delivered")
		self.assertEqual(_delivery_status("Outbound", None), "Queued")

	def test_missing_provider_id_uses_stable_source_key(self):
		source = {"doctype": "Legacy Message", "provider_id_fields": ["meta_id"]}
		row = {"name": "MSG-1", "meta_id": ""}
		self.assertEqual(
			_provider_id("example", source, row),
			"legacy:example:Legacy Message:MSG-1",
		)

	@patch("frappe_whatsapp_core.legacy_migration._validated_config")
	@patch("frappe_whatsapp_core.legacy_migration.frappe.get_all")
	@patch("frappe_whatsapp_core.legacy_migration.frappe.db.count")
	def test_plan_excludes_operational_legacy_records(self, count, get_all, validate):
		config = {
			"source_key": "example",
			"channels": [{"phone_number_id": "phone-1"}],
			"contact": {"doctype": "Legacy Contact", "phone_field": "phone"},
			"message": {"doctype": "Legacy Message"},
		}
		validate.return_value = config
		get_all.return_value = ["919000000000", "", None]
		count.side_effect = [25, 20]

		plan = legacy_source_plan(config)

		self.assertEqual(plan["source_contacts"], 3)
		self.assertEqual(plan["eligible_contacts"], 1)
		self.assertEqual(plan["source_messages"], 25)
		self.assertEqual(plan["core_messages_from_source"], 20)
		self.assertIn("AI queues", plan["excluded"])
		self.assertTrue(plan["migration_ready"])
		self.assertEqual(plan["blockers"], [])
		self.assertTrue(plan["source_is_read_only"])

	@patch("frappe_whatsapp_core.legacy_migration._validated_config")
	@patch("frappe_whatsapp_core.legacy_migration.frappe.get_all")
	@patch("frappe_whatsapp_core.legacy_migration.frappe.db.count")
	def test_plan_blocks_migration_without_a_configured_channel(self, count, get_all, validate):
		validate.return_value = {
			"source_key": "example",
			"channels": [{"source_name": "Legacy account", "phone_number_id": ""}],
			"contact": {"doctype": "Legacy Contact", "phone_field": "phone"},
			"message": {"doctype": "Legacy Message"},
		}
		get_all.return_value = ["919000000000"]
		count.side_effect = [1, 0]

		plan = legacy_source_plan(validate.return_value)

		self.assertFalse(plan["migration_ready"])
		self.assertIn("phone number ID", plan["blockers"][0])
