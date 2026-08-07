import json
import uuid
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import now_datetime

from frappe_whatsapp_core.materializer import (
	get_or_create_channel,
	get_or_create_conversation,
	get_or_create_identity,
)
from frappe_whatsapp_core.mcp_tools import TOOL_DEFINITIONS, call_tool
from frappe_whatsapp_core.mcp_transport import _dispatch, _safe_audit_value
from frappe_whatsapp_core.topics import (
	list_topics,
	unclassified_messages,
	upsert_topic,
)


class TestConversationTopics(FrappeTestCase):
	def setUp(self):
		suffix = str(uuid.uuid4().int)[-12:]
		self.channel = get_or_create_channel(f"TOPIC-{suffix}", "WABA-TOPIC")
		self.conversation = get_or_create_conversation(
			self.channel,
			get_or_create_identity(f"91{suffix[-10:]}"),
		)
		self.other_conversation = get_or_create_conversation(
			self.channel,
			get_or_create_identity(f"92{suffix[-10:]}"),
		)
		self.first_message = self._message(
			self.conversation.name,
			f"{suffix}-first",
		)
		self.second_message = self._message(
			self.conversation.name,
			f"{suffix}-second",
		)
		self.other_message = self._message(
			self.other_conversation.name,
			f"{suffix}-other",
		)

	def _message(self, conversation, message_key):
		return frappe.get_doc({
			"doctype": "WhatsApp Core Message",
			"message_key": message_key,
			"conversation": conversation,
			"channel": self.channel.name,
			"provider_message_id": f"wamid.{message_key}",
			"direction": "Inbound",
			"message_type": "text",
			"body": message_key,
			"content": json.dumps({"body": message_key}),
			"provider_timestamp": now_datetime(),
			"delivery_status": "Received",
		}).insert(ignore_permissions=True)

	def test_topic_is_idempotent_and_messages_are_exclusive(self):
		topic = upsert_topic(
			self.conversation.name,
			"Credit note request",
			"Customer reported damaged goods and requested a credit note.",
			category="Complaint",
			confidence=92,
			message_names=[self.first_message.name, self.second_message.name],
		)
		repeated = upsert_topic(
			self.conversation.name,
			"Credit note request",
			message_names=[self.first_message.name],
			topic_name=topic.name,
		)
		self.assertEqual(repeated.message_count, 2)
		self.assertEqual(list_topics(self.conversation.name)[0]["message_count"], 2)

		with self.assertRaises(frappe.ValidationError):
			upsert_topic(
				self.conversation.name,
				"Another topic",
				message_names=[self.first_message.name],
			)

	def test_topic_change_notifies_ai_queue_sessions(self):
		with patch("frappe_whatsapp_core.topics.frappe.publish_realtime") as publish:
			topic = upsert_topic(
				self.conversation.name,
				"Realtime topic",
				message_names=[self.first_message.name],
			)
		publish.assert_any_call(
			"whatsapp_core_topic",
			{
				"topic": topic.name,
				"conversation": self.conversation.name,
				"status": "Open",
			},
			after_commit=True,
		)

	def test_topic_rejects_cross_conversation_message(self):
		with self.assertRaises(frappe.ValidationError):
			upsert_topic(
				self.conversation.name,
				"Invalid topic",
				message_names=[self.other_message.name],
			)

	def test_unclassified_queue_can_be_scoped_to_conversation(self):
		upsert_topic(
			self.conversation.name,
			"One classified message",
			message_names=[self.first_message.name],
		)
		rows = unclassified_messages(
			limit=10,
			conversation=self.conversation.name,
		)
		self.assertEqual(
			[row.name for row in rows],
			[self.second_message.name],
		)

	def test_mcp_contract_exposes_topic_tools(self):
		tool_names = {tool["name"] for tool in TOOL_DEFINITIONS}
		self.assertIn("whatsapp.list_unclassified_messages", tool_names)
		self.assertIn("whatsapp.upsert_topic", tool_names)
		self.assertIn("whatsapp.list_conversation_topics", tool_names)
		self.assertIn("whatsapp.get_conversation", tool_names)
		self.assertIn("whatsapp.search_parties", tool_names)
		self.assertIn("whatsapp.bind_party", tool_names)
		self.assertIn("whatsapp.send_reply", tool_names)

	def test_mcp_conversation_snapshot_has_messages_and_topics(self):
		upsert_topic(
			self.conversation.name,
			"Test topic",
			message_names=[self.first_message.name],
		)

		snapshot = call_tool(
			"whatsapp.get_conversation",
			{
				"conversation": self.conversation.name,
				"message_limit": 10,
			},
		)

		self.assertEqual(
			snapshot["conversation"]["name"],
			self.conversation.name,
		)
		self.assertEqual(len(snapshot["messages"]), 2)
		self.assertEqual(snapshot["topics"][0]["title"], "Test topic")

	def test_mcp_json_rpc_call_is_structured_and_audited(self):
		with patch("frappe_whatsapp_core.mcp_transport.frappe.publish_realtime") as publish:
			response = _dispatch({
				"jsonrpc": "2.0",
				"id": 7,
				"method": "tools/call",
				"params": {
					"name": "whatsapp.list_unclassified_messages",
					"arguments": {
						"conversation": self.conversation.name,
						"limit": 2,
					},
				},
			})
		self.assertEqual(response["id"], 7)
		self.assertFalse(response["result"]["isError"])
		self.assertEqual(
			len(response["result"]["structuredContent"]),
			2,
		)
		self.assertTrue(
			frappe.db.exists(
				"WhatsApp Core MCP Invocation",
				{"tool_name": "whatsapp.list_unclassified_messages"},
			)
		)
		mcp_calls = [
			call for call in publish.call_args_list if call.args[0] == "whatsapp_core_mcp_invocation"
		]
		self.assertEqual(len(mcp_calls), 1)
		self.assertTrue(mcp_calls[0].kwargs["after_commit"])

	def test_mcp_audit_redacts_credentials_and_large_transport_payloads(self):
		value = _safe_audit_value({
			"access_token": "secret-token",
			"nested": {"api_secret": "secret", "business_public_key": "public"},
			"sdp": "v=0\nprivate-network-details",
			"file_content_b64": "AAAA",
		})
		self.assertEqual(value["access_token"], "[redacted]")
		self.assertEqual(value["nested"]["api_secret"], "[redacted]")
		self.assertEqual(value["nested"]["business_public_key"], "public")
		self.assertTrue(value["sdp"].startswith("[redacted "))
		self.assertTrue(value["file_content_b64"].startswith("[redacted "))
