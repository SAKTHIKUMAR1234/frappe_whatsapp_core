import json
import uuid
from pathlib import Path
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import now_datetime

from frappe_whatsapp_core.frontend_api import (
	_validated_hub_account_mappings,
	ai_queue_workspace,
	classify_messages,
	connectors_workspace,
	contact_source_doctypes,
	contact_source_fields,
	discover_hub_accounts,
	health_workspace,
	polls_workspace,
	save_contact_source,
	save_ai_summary_settings,
	settings_workspace,
)
from frappe_whatsapp_core.materializer import (
	get_or_create_channel,
	get_or_create_conversation,
	get_or_create_identity,
)


class TestFrontendWorkspaces(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.suffix = str(uuid.uuid4().int)[-12:]

	def test_ai_queue_classifies_selected_messages(self):
		channel = get_or_create_channel(f"UI-{self.suffix}", "WABA-UI")
		conversation = get_or_create_conversation(
			channel,
			get_or_create_identity(f"93{self.suffix[-10:]}"),
		)
		message = frappe.get_doc({
			"doctype": "WhatsApp Core Message",
			"message_key": f"ui-message-{self.suffix}",
			"conversation": conversation.name,
			"channel": channel.name,
			"provider_message_id": f"wamid.ui.{self.suffix}",
			"direction": "Inbound",
			"message_type": "text",
			"body": "Damaged goods need a credit note",
			"content": "{}",
			"provider_timestamp": now_datetime(),
			"delivery_status": "Received",
		}).insert(ignore_permissions=True)

		before = ai_queue_workspace(limit=250)
		self.assertIn(message.name, {row.name for row in before["messages"]})

		topic = classify_messages(
			conversation.name,
			"Credit note request",
			[message.name],
			category="Complaint",
		)
		self.assertEqual(topic.source, "Manual")

		after = ai_queue_workspace(limit=250)
		self.assertNotIn(message.name, {row.name for row in after["messages"]})

	def test_connector_registry_reports_real_contracts(self):
		workspace = connectors_workspace()
		self.assertTrue(workspace["mcp_endpoint"].endswith("mcp_transport.handle"))
		self.assertGreaterEqual(workspace["metrics"]["mcp_tools"], 1)
		self.assertIn("case.create", workspace["flow_actions"])
		self.assertEqual(
			{row["label"] for row in workspace["extension_points"]},
			{
				"Party resolution",
				"Party search",
				"Outbound preflight",
				"Campaign preflight",
				"Campaign sender",
			},
		)

	def test_poll_workspace_is_derived_from_question_nodes(self):
		flow = frappe.get_doc({
			"doctype": "WhatsApp Core Flow",
			"flow_key": f"ui.poll.{self.suffix}",
			"title": "UI Poll",
			"status": "Draft",
			"enabled": 1,
			"draft_graph": json.dumps({
				"schema_version": 1,
				"triggers": [],
				"nodes": [
					{"id": "start", "type": "start", "config": {}},
					{
						"id": "choice",
						"type": "ask_choice",
						"config": {
							"message": "Choose one",
							"answer_key": "choice",
							"options": [
								{"label": "Yes", "value": "yes"},
								{"label": "No", "value": "no"},
							],
						},
					},
					{"id": "end", "type": "end", "config": {}},
				],
				"edges": [],
			}),
		}).insert(ignore_permissions=True)

		workspace = polls_workspace()
		row = next(item for item in workspace["flows"] if item["name"] == flow.name)
		self.assertEqual(row["question_count"], 1)
		self.assertEqual(row["choice_count"], 1)

	def test_health_and_settings_use_site_local_records(self):
		health = health_workspace()
		self.assertEqual(
			set(health["metrics"]),
			{
				"pending_events",
				"failed_events",
				"failed_flow_steps",
				"failed_messages",
			},
		)
		settings = settings_workspace()
		self.assertEqual(settings["site"], frappe.local.site)
		self.assertIn("ai_summary", settings)
		self.assertIn("i2a_actions", settings)
		self.assertEqual(
			set(settings["inventory"]),
			{
				"identities",
				"verified_bindings",
				"conversations",
				"messages",
			},
		)

	def test_ai_summary_settings_require_a_frappe_tools_action(self):
		with self.assertRaises(frappe.ValidationError):
			save_ai_summary_settings(enabled=1, action="Missing I2A Action")

		settings = save_ai_summary_settings(
			enabled=0,
			action="",
			batch_size=0,
			max_media_mb=99,
		)
		self.assertFalse(settings["ai_summary"]["enabled"])
		self.assertEqual(settings["ai_summary"]["batch_size"], 100)
		self.assertEqual(settings["ai_summary"]["max_media_mb"], 50)

	@patch("frappe_whatsapp_core.frontend_api.call_management")
	def test_hub_account_discovery_returns_only_integration_options(self, call_management):
		call_management.return_value = {
			"accounts": [{"name": "Primary Account", "verified_name": "Essdee"}]
		}
		self.assertEqual(discover_hub_accounts()[0]["name"], "Primary Account")
		call_management.assert_called_once_with(
			"frappe_whatsapp_integration.frappe_whatsapp_hub.api.onboarding.list_site_accounts"
		)

	def test_hub_account_mappings_reject_duplicates_and_normalize_default(self):
		channel = get_or_create_channel(f"SETTINGS-{self.suffix}", f"WABA-{self.suffix}")
		rows = _validated_hub_account_mappings([
			{"channel": channel.name, "account_name": "Primary Account", "is_default": 0}
		])
		self.assertTrue(rows[0]["is_default"])
		with self.assertRaises(frappe.ValidationError):
			_validated_hub_account_mappings([
				{"channel": channel.name, "account_name": "Primary Account"},
				{"channel": channel.name, "account_name": "Secondary Account"},
			])

	def test_contact_source_configuration_uses_real_doctype_fields(self):
		doctypes = contact_source_doctypes(search="User")
		self.assertIn("User", {row.name for row in doctypes})
		fields = contact_source_fields("User")
		self.assertIn("mobile_no", {row["value"] for row in fields["phone_fields"]})
		source = save_contact_source({
			"source_key": f"ui.user.{self.suffix}",
			"display_name": "UI Users",
			"source_doctype": "User",
			"phone_field": "mobile_no",
			"display_name_field": "full_name",
			"enabled": 1,
			"auto_resolve": 1,
			"priority": 50,
		})
		self.assertEqual(source.source_doctype, "User")
		self.assertIn(source.name, {row.name for row in settings_workspace()["contact_sources"]})

	def test_router_preserves_both_public_whatsapp_entry_points(self):
		router = (
			Path(__file__).resolve().parents[2] / "core_ui" / "src" / "router.js"
		).read_text()
		self.assertIn("window.location.pathname.startsWith('/whatsapp_core')", router)
		self.assertIn(": '/whatsapp/'", router)

	def test_realtime_uses_the_dev_socketio_port(self):
		realtime = (
			Path(__file__).resolve().parents[2]
			/ "core_ui"
			/ "src"
			/ "services"
			/ "realtime.js"
		).read_text()
		self.assertIn("boot.developer_mode && boot.socketio_port", realtime)
		self.assertIn("origin.port = String(boot.socketio_port)", realtime)

		from frappe_whatsapp_core.www.whatsapp_core import get_context

		context = frappe._dict()
		with patch.object(frappe.sessions, "get_csrf_token", return_value="csrf-test"):
			get_context(context)
		self.assertEqual(context.boot["socketio_port"], frappe.conf.get("socketio_port") or 9000)
