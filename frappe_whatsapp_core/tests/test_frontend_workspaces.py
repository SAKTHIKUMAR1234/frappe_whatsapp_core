import json
import uuid

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import now_datetime

from frappe_whatsapp_core.frontend_api import (
	ai_queue_workspace,
	classify_messages,
	connectors_workspace,
	health_workspace,
	polls_workspace,
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
		self.assertEqual(
			set(settings["inventory"]),
			{
				"identities",
				"verified_bindings",
				"conversations",
				"messages",
			},
		)
