import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, now_datetime

from frappe_whatsapp_core.mcp_tools import TOOL_DEFINITIONS
from frappe_whatsapp_core.workspace_api import (
	get_conversation,
	list_conversations,
	list_messages,
	send_text,
	upsert_team,
)


class TestWorkspaceAPI(FrappeTestCase):
	def setUp(self):
		super().setUp()
		suffix = frappe.generate_hash(length=8).lower()
		self.channel = frappe.get_doc({
			"doctype": "WhatsApp Core Channel",
			"channel_key": f"meta:workspace-{suffix}",
			"display_name": "Workspace Test",
			"provider": "meta",
			"phone_number_id": f"workspace-{suffix}",
			"enabled": 1,
		}).insert(ignore_permissions=True)
		self.identity = frappe.get_doc({
			"doctype": "WhatsApp Core Identity",
			"identity_key": f"workspace-identity-{suffix}",
			"identity_type": "WhatsApp",
			"normalized_value": f"9198{suffix}",
			"display_value": f"Workspace User {suffix}",
			"provider": "meta",
			"status": "Active",
			"attributes": json.dumps({"source": "test"}),
		}).insert(ignore_permissions=True)
		now = now_datetime()
		self.conversation = frappe.get_doc({
			"doctype": "WhatsApp Core Conversation",
			"conversation_key": f"{self.channel.name}:{self.identity.name}",
			"channel": self.channel.name,
			"remote_identity": self.identity.name,
			"status": "Open",
			"last_inbound_at": now,
			"last_message_at": now,
		}).insert(ignore_permissions=True)
		self.messages = []
		for index in range(2):
			timestamp = add_to_date(now, seconds=index)
			self.messages.append(
				frappe.get_doc({
					"doctype": "WhatsApp Core Message",
					"message_key": f"workspace-message-{suffix}-{index}",
					"conversation": self.conversation.name,
					"channel": self.channel.name,
					"provider_message_id": f"wamid.workspace.{suffix}.{index}",
					"direction": "Inbound",
					"message_type": "text",
					"body": f"Message {index}",
					"content": json.dumps({"text": {"body": f"Message {index}"}}),
					"provider_timestamp": timestamp,
					"delivery_status": "Received",
				}).insert(ignore_permissions=True)
			)
		self.conversation.last_message_at = self.messages[-1].provider_timestamp
		self.conversation.save(ignore_permissions=True)

	def test_conversation_and_message_pagination_contract(self):
		result = list_conversations(search=self.identity.display_value, limit=10)
		self.assertTrue(
			any(row.name == self.conversation.name for row in result["rows"])
		)
		detail = get_conversation(self.conversation.name)
		self.assertEqual(detail["identity"]["name"], self.identity.name)

		page = list_messages(self.conversation.name, limit=1)
		self.assertEqual(len(page["rows"]), 1)
		self.assertTrue(page["has_more"])
		self.assertEqual(page["rows"][0].body, "Message 1")

	def test_team_and_outbound_hook_contracts(self):
		team = upsert_team(
			team_name=f"Workspace Team {frappe.generate_hash(length=6)}",
			members=[{"user": "Administrator", "team_role": "Manager"}],
		)
		self.assertEqual(team["members"][0]["user"], "Administrator")

		with patch(
			"frappe_whatsapp_core.workspace_api._outbound_handler"
		) as outbound_handler:
			sender = outbound_handler.return_value
			sender.return_value = {"name": "queued-message"}
			result = send_text(self.conversation.name, "Hello")
			self.assertEqual(result["name"], "queued-message")
			sender.assert_called_once_with(self.conversation.name, "Hello")

	def test_mcp_manifest_covers_operator_and_management_surfaces(self):
		names = {tool["name"] for tool in TOOL_DEFINITIONS}
		self.assertTrue({
			"whatsapp.list_conversations",
			"whatsapp.list_messages",
			"whatsapp.send_text",
			"whatsapp.send_template",
			"whatsapp.list_teams",
			"whatsapp.upsert_team",
			"whatsapp.list_campaigns",
			"whatsapp.list_flows",
		}.issubset(names))
