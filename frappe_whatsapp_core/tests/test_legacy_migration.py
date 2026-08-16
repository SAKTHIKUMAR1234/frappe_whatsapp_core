from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from frappe_whatsapp_core.legacy_migration import (
	_approval_status,
	_campaign_status,
	_delivery_status,
	_direction,
	_migrate_channels,
	_legacy_key,
	_legacy_message_content,
	_local_media_url,
	_media_reference_result,
	_migration_reconciliation,
	_percent_value,
	_provider_id,
	_reattach_legacy_files,
	_recipient_status,
	legacy_source_plan,
)


class TestLegacyMigrationContract(FrappeTestCase):
	def test_channel_migration_creates_one_idempotent_account_mapping(self):
		suffix = frappe.generate_hash(length=8).lower()
		account_name = f"legacy-account-{suffix}"
		config = {
			"source_key": "legacy-test",
			"channels": [{
				"source_name": account_name,
				"phone_number_id": f"legacy-phone-{suffix}",
				"waba_id": f"legacy-waba-{suffix}",
				"enabled": 1,
			}],
		}

		first = _migrate_channels(config)
		second = _migrate_channels(config)

		self.assertEqual(first[account_name].name, second[account_name].name)
		mappings = frappe.get_all(
			"WhatsApp Core Hub Account",
			filters={
				"parent": "WhatsApp Core Settings",
				"parenttype": "WhatsApp Core Settings",
				"parentfield": "accounts",
				"account_name": account_name,
				"channel": first[account_name].name,
			},
			pluck="name",
		)
		self.assertEqual(len(mappings), 1)
		self.assertEqual(first[account_name]._legacy_hub_account_name, account_name)

	def test_absolute_legacy_file_url_is_normalized_to_the_local_file_namespace(self):
		source = {"local_media_fields": ["media_url"]}
		self.assertEqual(
			_local_media_url(
				source,
				{
					"media_url": "https://sihma.org/files/Receipt%20April.pdf?download=1#page=1"
				},
			),
			"/files/Receipt April.pdf",
		)
		self.assertEqual(
			_local_media_url(source, {"media_url": "/private/files/voice.ogg?download=1"}),
			"/private/files/voice.ogg",
		)

	@patch("frappe_whatsapp_core.legacy_migration.frappe.db.exists", return_value=True)
	def test_legacy_template_document_keeps_a_core_media_descriptor(self, _exists):
		content = _legacy_message_content(
			{"source_key": "sihma"},
			{
				"doctype": "Sihma WhatsApp Message",
				"local_media_fields": ["media_url"],
				"content_fields": {
					"file_name": "file_name",
					"mime_type": "mime_type",
					"template_name": "template_name",
				},
			},
			frappe._dict(
				{
					"name": "LEGACY-TEMPLATE",
					"media_url": "https://sihma.org/files/Receipt.pdf",
					"file_name": "Receipt.pdf",
					"mime_type": "application/pdf",
					"template_name": "sihma_receipt",
				}
			),
			"template",
		)

		self.assertEqual(content["payload"]["filename"], "Receipt.pdf")
		self.assertEqual(content["payload"]["local_file_url"], "/files/Receipt.pdf")
		self.assertNotIn("id", content["payload"])
		self.assertEqual(_media_reference_result(content, existing=False), "inserted")
		self.assertEqual(_media_reference_result(content, existing=True), "existing")

	@patch("frappe_whatsapp_core.legacy_migration.frappe.db.exists", return_value=False)
	def test_missing_legacy_blob_is_audited_without_a_broken_media_link(self, _exists):
		content = _legacy_message_content(
			{"source_key": "sihma"},
			{
				"doctype": "Sihma WhatsApp Message",
				"local_media_fields": ["media_url"],
				"content_fields": {"file_name": "file_name"},
			},
			frappe._dict(
				{
					"name": "MISSING-TEMPLATE",
					"media_url": "https://sihma.org/files/missing.pdf",
					"file_name": "missing.pdf",
				}
			),
			"template",
		)

		self.assertNotIn("payload", content)
		self.assertEqual(content["legacy_missing_file_url"], "/files/missing.pdf")

	@patch("frappe_whatsapp_core.legacy_migration.frappe.db.set_value")
	@patch(
		"frappe_whatsapp_core.legacy_migration.frappe.get_all",
		return_value=["FILE-1"],
	)
	def test_legacy_file_attachment_is_repointed_without_changing_the_blob(
		self, get_all, set_value
	):
		result = _reattach_legacy_files(
			{"doctype": "Legacy Message"},
			frappe._dict(name="LEGACY-1"),
			"CORE-1",
		)

		get_all.assert_called_once_with(
			"File",
			filters={
				"attached_to_doctype": "Legacy Message",
				"attached_to_name": "LEGACY-1",
			},
			pluck="name",
			limit_page_length=1000,
		)
		set_value.assert_called_once_with(
			"File",
			"FILE-1",
			{
				"attached_to_doctype": "WhatsApp Core Message",
				"attached_to_name": "CORE-1",
			},
			update_modified=False,
		)
		self.assertEqual(result, {"reattached": 1, "already_attached": 0})

	def test_direction_and_status_are_normalized_across_legacy_apps(self):
		self.assertEqual(_direction("inbound"), "Inbound")
		self.assertEqual(_direction("Outbound"), "Outbound")
		self.assertEqual(_delivery_status("Inbound", "read"), "Received")
		self.assertEqual(_delivery_status("Outbound", "delivered"), "Delivered")
		self.assertEqual(_delivery_status("Outbound", None), "Queued")
		self.assertEqual(_approval_status("pending"), "IN_REVIEW")
		self.assertEqual(_campaign_status("Processing"), "Paused")
		self.assertEqual(_recipient_status("Pending"), "Prepared")
		self.assertEqual(_percent_value(0.84), 84)
		self.assertEqual(_percent_value(84), 84)

	def test_import_keys_are_deterministic_and_namespaced(self):
		first = _legacy_key("sihma", "WhatsApp Campaign", "WA-CAMP-1")
		second = _legacy_key("sihma", "WhatsApp Campaign", "WA-CAMP-1")
		other = _legacy_key("pasarai", "WhatsApp Campaign", "WA-CAMP-1")
		self.assertEqual(first, second)
		self.assertNotEqual(first, other)
		self.assertTrue(first.startswith("legacy."))

	@patch("frappe_whatsapp_core.legacy_migration.legacy_source_plan")
	def test_reconciliation_counts_each_existing_record_once(self, plan):
		plan.return_value = {
			"source_channels": 1,
			"eligible_contacts": 2,
			"source_messages": 3,
			"source_media_files": 1,
			"source_templates": 1,
			"source_campaigns": 1,
			"source_campaign_recipients": 2,
			"source_categories": 1,
			"source_category_assignments": 2,
		}
		result = {
			"channels": 1,
			"contacts": 2,
			"messages_existing": 3,
			"media_files_existing": 1,
			"templates_existing": 1,
			"campaigns_existing": 1,
			"campaign_recipients_existing": 2,
			"categories_existing": 1,
			"category_assignments_existing": 2,
		}

		reconciliation = _migration_reconciliation({}, result)

		self.assertTrue(all(item["ok"] for item in reconciliation.values()))
		self.assertEqual(reconciliation["category_assignments"]["processed"], 2)

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
			"template": {"doctype": "Legacy Template"},
			"campaign": {
				"doctype": "Legacy Campaign",
				"recipient": {"doctype": "Legacy Campaign Recipient"},
			},
			"category": {
				"doctype": "Legacy Category",
				"assignment": {
					"doctype": "Legacy Category Assignment",
					"message_doctype": "Legacy Message",
				},
			},
		}
		validate.return_value = config
		get_all.return_value = ["919000000000", "", None]
		count.side_effect = [25, 4, 3, 40, 6, 70, 20]

		plan = legacy_source_plan(config)

		self.assertEqual(plan["source_contacts"], 3)
		self.assertEqual(plan["eligible_contacts"], 1)
		self.assertEqual(plan["source_messages"], 25)
		self.assertEqual(plan["source_media_files"], 0)
		self.assertEqual(plan["source_templates"], 4)
		self.assertEqual(plan["source_campaigns"], 3)
		self.assertEqual(plan["source_campaign_recipients"], 40)
		self.assertEqual(plan["source_categories"], 6)
		self.assertEqual(plan["source_category_assignments"], 70)
		self.assertEqual(plan["core_messages_from_source"], 20)
		self.assertIn("AI runtime queues and model settings", plan["excluded"])
		self.assertIn("templates and component definitions", plan["included"])
		self.assertTrue(plan["migration_ready"])
		self.assertEqual(plan["blockers"], [])
		self.assertTrue(plan["source_is_read_only"])
		self.assertTrue(plan["rerun_safe"])
		self.assertIn("read markers", " ".join(plan["warnings"]))

	@patch("frappe_whatsapp_core.legacy_migration._validated_config")
	@patch("frappe_whatsapp_core.legacy_migration._resolved_channel_sources", return_value=([], False))
	@patch("frappe_whatsapp_core.legacy_migration.frappe.get_all")
	@patch("frappe_whatsapp_core.legacy_migration.frappe.db.count")
	def test_plan_blocks_migration_without_a_configured_channel(
		self, count, get_all, _resolve, validate
	):
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

	@patch("frappe_whatsapp_core.legacy_migration._validated_config")
	@patch("frappe_whatsapp_core.legacy_migration._resolved_channel_sources")
	@patch("frappe_whatsapp_core.legacy_migration.frappe.get_all")
	@patch("frappe_whatsapp_core.legacy_migration.frappe.db.count")
	def test_plan_uses_unambiguous_core_channel_fallback(
		self, count, get_all, resolve, validate
	):
		config = {
			"source_key": "example",
			"channels": [{"source_name": "default", "phone_number_id": ""}],
			"contact": {"doctype": "Legacy Contact", "phone_field": "phone"},
			"message": {"doctype": "Legacy Message"},
		}
		validate.return_value = config
		resolve.return_value = ([{"source_name": "default", "phone_number_id": "core-1"}], True)
		get_all.return_value = ["919000000000"]
		count.side_effect = [1, 0]

		plan = legacy_source_plan(config)

		self.assertTrue(plan["migration_ready"])
		self.assertEqual(plan["source_channels"], 1)
		self.assertIn("sole enabled", " ".join(plan["warnings"]))
