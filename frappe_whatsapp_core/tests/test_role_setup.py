from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, call, patch

import frappe

from frappe_whatsapp_core import setup


class TestCoreRoleSetup(TestCase):
	@patch("frappe_whatsapp_core.setup._migrate_legacy_roles")
	@patch("frappe_whatsapp_core.setup.frappe.get_doc")
	@patch("frappe_whatsapp_core.setup.frappe.db.exists")
	def test_missing_roles_are_created_before_legacy_migration(self, exists, get_doc, migrate):
		exists.side_effect = lambda doctype, name: name == "WhatsApp User"
		created = MagicMock()
		get_doc.return_value = created

		setup.ensure_core_roles()

		self.assertEqual(get_doc.call_count, 5)
		created.insert.assert_has_calls([
			call(ignore_permissions=True),
			call(ignore_permissions=True),
			call(ignore_permissions=True),
			call(ignore_permissions=True),
			call(ignore_permissions=True),
		])
		migrate.assert_called_once_with()

	@patch("frappe_whatsapp_core.setup.frappe.clear_cache")
	@patch("frappe_whatsapp_core.setup.frappe.delete_doc")
	@patch("frappe_whatsapp_core.setup.frappe.get_all")
	@patch("frappe_whatsapp_core.setup.frappe.db.set_value")
	@patch("frappe_whatsapp_core.setup.frappe.db.delete")
	@patch("frappe_whatsapp_core.setup.frappe.db.exists")
	def test_legacy_roles_are_deduplicated_migrated_or_disabled(
		self, exists, db_delete, set_value, get_all, delete_doc, clear_cache
	):
		rows = {
			"WhatsApp Core Admin": [SimpleNamespace(
				name="ROLE-ROW-1", parent="manager@example.test",
				parenttype="User", parentfield="roles",
			)],
			"WhatsApp Core Manager": [SimpleNamespace(
				name="ROLE-ROW-2", parent="second@example.test",
				parenttype="User", parentfield="roles",
			)],
		}
		get_all.side_effect = lambda _doctype, filters, **_kwargs: rows.get(filters["role"], [])

		def exists_side_effect(doctype, value):
			if doctype == "Has Role":
				return value["parent"] == "manager@example.test"
			if doctype == "Role":
				return value in {"WhatsApp Core Admin", "WhatsApp Core Manager"}
			return False

		exists.side_effect = exists_side_effect
		delete_doc.side_effect = [None, frappe.LinkExistsError("linked")]

		setup._migrate_legacy_roles()

		db_delete.assert_called_once_with("Has Role", {"name": "ROLE-ROW-1"})
		set_value.assert_any_call(
			"Has Role", "ROLE-ROW-2", "role", "WhatsApp Manager", update_modified=False
		)
		set_value.assert_any_call(
			"Role", "WhatsApp Core Manager", "disabled", 1, update_modified=False
		)
		clear_cache.assert_called_once_with()
