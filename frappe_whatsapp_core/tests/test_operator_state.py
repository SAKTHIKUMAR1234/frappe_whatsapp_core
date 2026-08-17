from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from frappe_whatsapp_core import conversation_reads, message_reactions


class TestConversationReads(TestCase):
	def test_provider_read_lookup_ignores_legacy_non_meta_ids(self):
		with patch.object(
			conversation_reads.frappe.db,
			"sql",
			return_value=[],
		) as query:
			self.assertIsNone(
				conversation_reads._latest_inbound_provider_message("CONV-1")
			)
		self.assertIn("provider_message_id LIKE 'wamid.%%'", query.call_args.args[0])

	def test_reader_display_name_never_falls_back_to_email(self):
		self.assertEqual(
			conversation_reads._reader_display_name(
				{"first_name": "Sakthi", "last_name": "Kumar", "full_name": "Wrong"},
				"sakthi@example.test",
			),
			"Sakthi Kumar",
		)
		self.assertEqual(
			conversation_reads._reader_display_name({}, "missing@example.test"),
			"Team member",
		)

	@patch("frappe_whatsapp_core.conversation_reads.message_readers")
	def test_exact_read_ledger_is_projected_onto_each_loaded_message(self, readers):
		messages = [
			SimpleNamespace(name="MSG-1", provider_timestamp="2026-08-10 01:00:00", creation="1"),
			SimpleNamespace(name="MSG-2", provider_timestamp="2026-08-10 02:00:00", creation="2"),
		]
		readers.return_value = {
			"MSG-1": [{"user": "early@example.test"}],
			"MSG-2": [{"user": "latest@example.test"}],
		}

		conversation_reads.attach_message_readers(messages)

		self.assertEqual(messages[0].read_by, [{"user": "early@example.test"}])
		self.assertEqual(messages[1].read_by, [{"user": "latest@example.test"}])
		readers.assert_called_once_with(["MSG-1", "MSG-2"])

	@patch("frappe_whatsapp_core.conversation_reads.frappe.get_roles", return_value=["System Manager"])
	@patch("frappe_whatsapp_core.conversation_reads.assert_conversation_access")
	@patch("frappe_whatsapp_core.conversation_reads.frappe.has_permission")
	@patch("frappe_whatsapp_core.conversation_reads._advance_conversation_cursor")
	@patch("frappe_whatsapp_core.conversation_reads._record_message_reads")
	@patch("frappe_whatsapp_core.conversation_reads.frappe.get_all")
	def test_visible_message_batch_records_exact_rows_and_advances_one_cursor(
		self,
		get_all,
		record_reads,
		advance_cursor,
		_has_permission,
		_assert_access,
		_get_roles,
	):
		get_all.return_value = [
			SimpleNamespace(name="MSG-1", provider_timestamp="2026-08-10 01:00:00", creation="1"),
			SimpleNamespace(name="MSG-2", provider_timestamp="2026-08-10 02:00:00", creation="2"),
		]
		record_reads.return_value = ["MSG-1", "MSG-2"]
		advance_cursor.return_value = {
			"conversation": "CONV-1",
			"last_read_message": "MSG-2",
		}

		result = conversation_reads.mark_messages_read(
			"CONV-1",
			["MSG-1", "MSG-2", "MSG-1"],
		)

		self.assertEqual(result["processed"], 2)
		self.assertEqual(result["recorded"], 2)
		record_reads.assert_called_once()
		advance_cursor.assert_called_once()
		self.assertEqual(advance_cursor.call_args.args[1].name, "MSG-2")
		self.assertEqual(get_all.call_args.kwargs["limit_page_length"], 2)

	@patch("frappe_whatsapp_core.conversation_reads.now_datetime", return_value="2026-08-10 03:00:00")
	@patch("frappe_whatsapp_core.conversation_reads.frappe.enqueue")
	@patch("frappe_whatsapp_core.conversation_reads._latest_inbound_provider_message")
	def test_atomic_cursor_upsert_queues_provider_receipt_inside_read_window(
		self,
		latest,
		enqueue,
		_now,
	):
		target = SimpleNamespace(
			name="MSG-1",
			provider_timestamp="2026-08-10 02:00:00",
			creation="2026-08-10 02:00:01",
		)
		latest.return_value = SimpleNamespace(channel="CHANNEL-1", provider_message_id="wamid.1")
		read_row = SimpleNamespace(
			conversation="CONV-1",
			user=conversation_reads.frappe.session.user,
			last_read_message="MSG-1",
			last_read_at="2026-08-10 02:00:00",
			last_read_creation="2026-08-10 02:00:01",
		)
		existing_cursor = SimpleNamespace(name="READ-1", read_key="legacy-read-key")
		with (
			patch.object(
				conversation_reads.frappe.db,
				"sql",
				side_effect=[None, [1]],
			) as db_sql,
			patch.object(
				conversation_reads.frappe.db,
				"get_value",
				side_effect=[existing_cursor, read_row],
			),
			patch.object(conversation_reads, "publish_conversation_read") as publish_read,
		):
			result = conversation_reads._advance_conversation_cursor(
				"CONV-1", target, ["MSG-1"]
			)

		self.assertEqual(result["last_read_message"], "MSG-1")
		self.assertEqual(result["messages"], ["MSG-1"])
		self.assertIn("ON DUPLICATE KEY UPDATE", db_sql.call_args_list[0].args[0])
		publish_read.assert_called_once_with(result)
		latest.assert_called_once_with("CONV-1", at_or_before=target)
		enqueue.assert_called_once_with(
			"frappe_whatsapp_core.conversation_reads.sync_provider_read",
			queue="short",
			enqueue_after_commit=True,
			channel="CHANNEL-1",
			message_id="wamid.1",
		)

	@patch("frappe_whatsapp_core.conversation_reads.now_datetime", return_value="2026-08-10 03:00:00")
	@patch("frappe_whatsapp_core.conversation_reads.frappe.enqueue")
	@patch("frappe_whatsapp_core.conversation_reads._latest_inbound_provider_message")
	def test_already_read_cursor_does_not_publish_or_repeat_provider_receipt(
		self,
		latest,
		enqueue,
		_now,
	):
		target = SimpleNamespace(
			name="MSG-1",
			provider_timestamp="2026-08-10 02:00:00",
			creation="2026-08-10 02:00:01",
		)
		read_row = SimpleNamespace(
			conversation="CONV-1",
			user=conversation_reads.frappe.session.user,
			last_read_message="MSG-1",
			last_read_at="2026-08-10 02:00:00",
			last_read_creation="2026-08-10 02:00:01",
		)
		existing_cursor = SimpleNamespace(name="READ-1", read_key="legacy-read-key")
		with (
			patch.object(conversation_reads.frappe.db, "sql", side_effect=[None, [0]]),
			patch.object(
				conversation_reads.frappe.db,
				"get_value",
				side_effect=[existing_cursor, read_row],
			),
			patch.object(conversation_reads, "publish_conversation_read") as publish_read,
		):
			result = conversation_reads._advance_conversation_cursor("CONV-1", target, [])

		self.assertEqual(result["last_read_message"], "MSG-1")
		latest.assert_not_called()
		enqueue.assert_not_called()
		publish_read.assert_not_called()

	@patch("frappe_whatsapp_core.conversation_reads.frappe.db.sql")
	def test_provider_receipt_query_is_bounded_by_exact_cursor(self, db_sql):
		db_sql.return_value = [
			SimpleNamespace(channel="CHANNEL-1", provider_message_id="wamid.before")
		]
		target = SimpleNamespace(
			name="MSG-20",
			provider_timestamp="2026-08-10 02:00:00",
			creation="2026-08-10 02:00:01",
		)

		result = conversation_reads._latest_inbound_provider_message(
			"CONV-1", at_or_before=target
		)

		self.assertEqual(result.provider_message_id, "wamid.before")
		query, values = db_sql.call_args.args[:2]
		self.assertIn("name <= %(read_message)s", query)
		self.assertIn("message_type != 'reaction'", query)
		self.assertEqual(values["read_message"], "MSG-20")

	@patch("frappe_whatsapp_core.conversation_reads.frappe.get_roles", return_value=["System Manager"])
	@patch("frappe_whatsapp_core.conversation_reads.assert_conversation_access")
	@patch("frappe_whatsapp_core.conversation_reads.frappe.has_permission")
	@patch(
		"frappe_whatsapp_core.conversation_reads.frappe.db.get_value",
		return_value=SimpleNamespace(
			conversation="OTHER-CONV",
			provider_timestamp="2026-08-10 02:00:00",
			creation="2026-08-10 02:00:01",
		),
	)
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
