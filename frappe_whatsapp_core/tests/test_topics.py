import json
import uuid

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import now_datetime

from frappe_whatsapp_core.materializer import (
	get_or_create_channel,
	get_or_create_conversation,
	get_or_create_identity,
)
from frappe_whatsapp_core.mcp_tools import TOOL_DEFINITIONS
from frappe_whatsapp_core.mcp_transport import _dispatch
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
			get_or_create_identity(f"9100{suffix}"),
		)
		self.other_conversation = get_or_create_conversation(
			self.channel,
			get_or_create_identity(f"9200{suffix}"),
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

	def test_mcp_json_rpc_call_is_structured_and_audited(self):
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
