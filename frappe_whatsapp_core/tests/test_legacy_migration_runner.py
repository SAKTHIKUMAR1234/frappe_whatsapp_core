from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from frappe_whatsapp_core.legacy_migration_runner import (
	_adapter_paths,
	migrate_installed_legacy_whatsapp,
	preview_installed_legacy_whatsapp,
)


class TestLegacyMigrationRunner(FrappeTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")

	@patch("frappe_whatsapp_core.legacy_migration_runner.frappe.get_hooks")
	def test_adapter_paths_are_flattened_and_deduplicated(self, get_hooks):
		get_hooks.return_value = ["example.one", ["example.two", "example.one"]]
		self.assertEqual(_adapter_paths(), ["example.one", "example.two"])

	@patch("frappe_whatsapp_core.legacy_migration_runner._adapter_call")
	@patch("frappe_whatsapp_core.legacy_migration_runner._adapter_paths")
	def test_preview_aggregates_registered_adapters(self, paths, adapter_call):
		paths.return_value = ["example.migration"]
		adapter_call.return_value = {
			"adapter": "example.migration",
			"migration_ready": True,
		}

		result = preview_installed_legacy_whatsapp()

		self.assertTrue(result["migration_ready"])
		self.assertTrue(result["source_is_read_only"])

	@patch("frappe_whatsapp_core.legacy_migration_runner._adapter_call")
	@patch("frappe_whatsapp_core.legacy_migration_runner._adapter_paths")
	def test_migrate_requires_every_reconciliation_to_pass(self, paths, adapter_call):
		paths.return_value = ["example.one", "example.two"]
		adapter_call.side_effect = [
			{"adapter": "example.one", "reconciliation_ok": True},
			{"adapter": "example.two", "reconciliation_ok": False},
		]

		result = migrate_installed_legacy_whatsapp(250, 1)

		self.assertFalse(result["reconciliation_ok"])
		self.assertTrue(result["rerun_safe"])
		self.assertEqual(adapter_call.call_count, 2)
