from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch

from frappe_whatsapp_core import conversation_reads, message_reactions


class TestConversationReads(TestCase):
	@patch("frappe_whatsapp_core.conversation_reads.frappe.get_roles", return_value=["System Manager"])
	@patch("frappe_whatsapp_core.conversation_reads.assert_conversation_access")
	@patch("frappe_whatsapp_core.conversation_reads.frappe.has_permission")
	@patch("frappe_whatsapp_core.conversation_reads.now", return_value="2026-08-10 02:00:00")
	@patch("frappe_whatsapp_core.conversation_reads.frappe.enqueue")
	@patch("frappe_whatsapp_core.conversation_reads._latest_inbound_provider_message")
	@patch("frappe_whatsapp_core.conversation_reads.frappe.new_doc")
	@patch("frappe_whatsapp_core.conversation_reads.frappe.db.exists", return_value=False)
	@patch("frappe_whatsapp_core.conversation_reads.frappe.db.get_value", return_value="CONV-1")
	def test_mark_read_persists_operator_cursor_and_queues_provider_receipt(
		self,
		_get_value,
		_exists,
		new_doc,
		latest,
		enqueue,
		_now,
		_has_permission,
		_assert_access,
		_get_roles,
	):
		doc = MagicMock()
		new_doc.return_value = doc
		latest.return_value = SimpleNamespace(channel="CHANNEL-1", provider_message_id="wamid.1")

		with patch.object(conversation_reads.frappe, "publish_realtime") as publish_realtime:
			result = conversation_reads.mark_conversation_read("CONV-1", "MSG-1")

		self.assertEqual(result["last_read_message"], "MSG-1")
		self.assertEqual(doc.conversation, "CONV-1")
		self.assertEqual(doc.last_read_at, "2026-08-10 02:00:00")
		doc.save.assert_called_once_with(ignore_permissions=True)
		publish_realtime.assert_called_once_with(
			"whatsapp_core_conversation_read",
			{
				"conversation": "CONV-1",
				"user": result["user"],
				"last_read_message": "MSG-1",
				"last_read_at": "2026-08-10 02:00:00",
			},
			after_commit=True,
		)
		enqueue.assert_called_once_with(
			"frappe_whatsapp_core.conversation_reads.sync_provider_read",
			queue="short",
			enqueue_after_commit=True,
			channel="CHANNEL-1",
			message_id="wamid.1",
		)

	@patch("frappe_whatsapp_core.conversation_reads.frappe.get_roles", return_value=["System Manager"])
	@patch("frappe_whatsapp_core.conversation_reads.assert_conversation_access")
	@patch("frappe_whatsapp_core.conversation_reads.frappe.has_permission")
	@patch("frappe_whatsapp_core.conversation_reads.frappe.db.get_value", return_value="OTHER-CONV")
	def test_mark_read_rejects_cursor_from_another_conversation(
		self, _get_value, _has_permission, _assert_access, _get_roles
	):
		with self.assertRaises(Exception) as context:
			conversation_reads.mark_conversation_read("CONV-1", "MSG-OTHER")
		self.assertIn("does not belong", str(context.exception))

	@patch("frappe_whatsapp_core.conversation_reads.frappe.get_roles", return_value=["System Manager"])
	@patch("frappe_whatsapp_core.conversation_reads.assert_conversation_access")
	@patch("frappe_whatsapp_core.conversation_reads.frappe.has_permission")
	@patch("frappe_whatsapp_core.conversation_reads._latest_inbound_provider_message", return_value=None)
	def test_typing_is_not_sent_without_an_inbound_provider_message(
		self, _latest, _has_permission, _assert_access, _get_roles
	):
		self.assertEqual(
			conversation_reads.show_typing("CONV-1"),
			{"sent": False, "reason": "No inbound provider message"},
		)

	@patch("frappe_whatsapp_core.hub_client.mark_message_read")
	@patch("frappe_whatsapp_core.conversation_reads.frappe.get_roles", return_value=["System Manager"])
	@patch("frappe_whatsapp_core.conversation_reads.assert_conversation_access")
	@patch("frappe_whatsapp_core.conversation_reads.frappe.has_permission")
	@patch("frappe_whatsapp_core.conversation_reads._latest_inbound_provider_message")
	def test_typing_targets_latest_inbound_provider_message(
		self, latest, _has_permission, _assert_access, _get_roles, mark_read
	):
		latest.return_value = SimpleNamespace(channel="CHANNEL-1", provider_message_id="wamid.2")

		result = conversation_reads.show_typing("CONV-1")

		self.assertTrue(result["sent"])
		mark_read.assert_called_once_with("CHANNEL-1", "wamid.2", typing_indicator=True)


class TestMessageReactions(TestCase):
	def test_reaction_parser_accepts_direct_nested_and_rejects_invalid_payloads(self):
		self.assertEqual(
			message_reactions.reaction_from_content('{"reaction":{"message_id":"wamid.1","emoji":"👍"}}')["emoji"],
			"👍",
		)
		self.assertEqual(
			message_reactions.reaction_from_content(
				{"payload": {"reaction": {"message_id": "wamid.1", "emoji": "✅"}}}
			)["emoji"],
			"✅",
		)
		self.assertEqual(message_reactions.reaction_from_content("not-json"), {})

	@patch("frappe_whatsapp_core.message_reactions.frappe.get_all")
	def test_reactions_are_folded_into_target_and_removal_clears_actor_state(self, get_all):
		get_all.side_effect = [
			[
				SimpleNamespace(
					name="REACTION-1", provider_message_id="reaction.1", direction="Inbound",
					content='{"reaction":{"message_id":"wamid.target","emoji":"👍"}}',
					owner=None, provider_timestamp="2026-08-10 02:00:00", creation="2026-08-10 02:00:00",
				),
				SimpleNamespace(
					name="REACTION-2", provider_message_id="reaction.2", direction="Inbound",
					content='{"reaction":{"message_id":"wamid.target","emoji":""}}',
					owner=None, provider_timestamp="2026-08-10 02:01:00", creation="2026-08-10 02:01:00",
				),
				SimpleNamespace(
					name="REACTION-3", provider_message_id="reaction.3", direction="Outbound",
					content='{"reaction":{"message_id":"wamid.target","emoji":"✅"}}',
					owner="agent@example.test", provider_timestamp="2026-08-10 02:02:00", creation="2026-08-10 02:02:00",
				),
			],
			[SimpleNamespace(name="agent@example.test", full_name="Test Agent")],
		]
		messages = [{"provider_message_id": "wamid.target", "body": "Hello"}]

		message_reactions.attach_message_reactions(messages, "CONV-1")

		self.assertEqual(len(messages[0]["reactions"]), 1)
		self.assertEqual(messages[0]["reactions"][0]["emoji"], "✅")
		self.assertEqual(messages[0]["reactions"][0]["actor"], "Test Agent")

	@patch("frappe_whatsapp_core.message_reactions.frappe.get_all")
	def test_empty_or_unaddressable_messages_do_not_query_reactions(self, get_all):
		message_reactions.attach_message_reactions([], "CONV-1")
		message_reactions.attach_message_reactions([{"body": "No provider id"}], "CONV-1")
		get_all.assert_not_called()
