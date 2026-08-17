import json
import unittest
from inspect import Parameter, signature
from pathlib import Path
from unittest.mock import patch

import frappe

from frappe_whatsapp_core.api import (
	IMMEDIATE_STATUS_BATCH_SIZE,
	MAX_RECEIVE_BATCH_SIZE,
	_apply_outbound_result,
	describe_payload,
	payload_fingerprint,
	receive_batch,
	receive_outbound_results,
)
from frappe_whatsapp_core.dispatcher import (
	_get_locked_core_event_rows,
	_has_orphan_status,
	_lock_status_projection_rows,
	_process_status_event_batch,
	enqueue_event_batch,
	enqueue_event_rows_by_lane,
	enqueue_orphan_status_retry,
	enqueue_waiting_status_events,
	process_event_batch,
	retry_orphan_status_events,
	retry_failed_events,
	retry_stale_events,
	wake_waiting_status_events,
)
from frappe_whatsapp_core.outbound import _mark_sent


class TestPayloadContract(unittest.TestCase):
	@patch("frappe_whatsapp_core.dispatcher.enqueue_event_batch")
	@patch("frappe_whatsapp_core.dispatcher.frappe.db.sql")
	@patch("frappe_whatsapp_core.dispatcher.frappe.get_all", return_value=["EVENT-1"])
	def test_provider_binding_revives_exhausted_orphan_receipt(
		self, get_all, db_sql, enqueue_batch
	):
		count = enqueue_waiting_status_events(
			["wamid.1"], enqueue_after_commit=False
		)

		self.assertEqual(count, 1)
		self.assertNotIn("attempts", get_all.call_args.kwargs["filters"])
		db_sql.assert_not_called()
		enqueue_batch.assert_called_once_with(["EVENT-1"], enqueue_after_commit=True)

	@patch("frappe_whatsapp_core.dispatcher.frappe.db.sql")
	@patch("frappe_whatsapp_core.dispatcher.frappe.get_all")
	@patch("frappe_whatsapp_core.dispatcher.frappe.enqueue")
	def test_provider_binding_defers_event_wake_to_fresh_transaction(
		self, enqueue, get_all, db_sql
	):
		count = enqueue_waiting_status_events(["wamid.1", "wamid.1"])

		self.assertEqual(count, 0)
		get_all.assert_not_called()
		db_sql.assert_not_called()
		enqueue.assert_called_once_with(
			"frappe_whatsapp_core.dispatcher.wake_waiting_status_events",
			queue="short",
			enqueue_after_commit=True,
			provider_ids=["wamid.1"],
		)

	@patch("frappe_whatsapp_core.dispatcher.time.sleep")
	@patch("frappe_whatsapp_core.dispatcher.frappe.db.rollback")
	@patch("frappe_whatsapp_core.dispatcher._wake_waiting_status_events")
	def test_provider_binding_wake_retries_after_checkread(
		self, wake, rollback, sleep
	):
		wake.side_effect = [
			frappe.QueryDeadlockError("synthetic checkread"),
			2,
		]

		count = wake_waiting_status_events(["wamid.1"])

		self.assertEqual(count, 2)
		self.assertEqual(wake.call_count, 2)
		rollback.assert_called_once_with()
		sleep.assert_called_once()

	@patch("frappe_whatsapp_core.dispatcher.enqueue_waiting_status_events")
	@patch("frappe_whatsapp_core.outbound._publish_status")
	@patch("frappe_whatsapp_core.outbound._reconcile_campaign_message")
	@patch("frappe_whatsapp_core.outbound.frappe.db.get_value")
	@patch("frappe_whatsapp_core.outbound.frappe.clear_document_cache")
	@patch("frappe_whatsapp_core.outbound.frappe.db.sql")
	def test_send_result_cannot_regress_read_callback(
		self, db_sql, _clear, get_value, reconcile, publish, wake
	):
		get_value.return_value = frappe._dict(
			name="MSG-1",
			conversation="CONV-1",
			delivery_status="Read",
			provider_message_id="wamid.1",
		)

		_mark_sent(frappe._dict(name="MSG-1"), "wamid.1")

		self.assertIn("WHEN delivery_status = 'Queued' THEN 'Sent'", db_sql.call_args.args[0])
		self.assertEqual(publish.call_args.args[0].delivery_status, "Read")
		reconcile.assert_called_once_with("MSG-1")
		wake.assert_called_once_with(["wamid.1"], enqueue_after_commit=True)

	@patch("frappe_whatsapp_core.api.enqueue_campaign_refresh_for_messages")
	@patch("frappe_whatsapp_core.api.publish_message_changes")
	@patch(
		"frappe_whatsapp_core.api.frappe.get_all",
		return_value=[frappe._dict(name="MSG-EXISTING", provider_message_id="wamid.collision")],
	)
	@patch("frappe_whatsapp_core.api.frappe.clear_document_cache")
	@patch("frappe_whatsapp_core.api.frappe.db.bulk_update")
	@patch(
		"frappe_whatsapp_core.api.frappe.db.sql",
		return_value=[frappe._dict(
			name="MSG-NEW",
			idempotency_key="new-result",
			conversation="CONV-1",
			delivery_status="Queued",
			provider_message_id="local:new",
			failure=None,
		)],
	)
	@patch(
		"frappe_whatsapp_core.api.frappe.db.get_value",
		return_value=frappe._dict(
			name="MSG-NEW",
			conversation="CONV-1",
			delivery_status="Failed",
			provider_message_id="local:new",
		),
	)
	def test_provider_id_collision_is_terminal_failure_not_callback_error(
		self, _get_value, _db_sql, bulk_update, _clear, _get_all, publish, refresh
	):
		result = _apply_outbound_result(
			idempotency_key="new-result",
			status="sent",
			success=1,
			meta_message_id="wamid.collision",
			status_code=200,
		)

		self.assertEqual(result["status"], "applied")
		self.assertEqual(result["delivery_status"], "Failed")
		update = bulk_update.call_args.args[1]["MSG-NEW"]
		self.assertEqual(update["provider_message_id"], "local:new")
		self.assertEqual(json.loads(update["failure"])["code"], "provider_message_id_collision")
		publish.assert_called_once()
		refresh.assert_called_once_with(["MSG-NEW"])

	def test_orphan_status_is_deferred_until_provider_result_arrives(self):
		self.assertTrue(_has_orphan_status([
			{"kind": "status", "status": "orphan", "provider_message_id": "wamid.1"},
		]))
		self.assertFalse(_has_orphan_status([
			{"kind": "status", "status": "updated", "name": "MSG-1"},
		]))

	def test_receive_batch_acceptance_limit_matches_relay_contract(self):
		with self.assertRaises(frappe.ValidationError):
			receive_batch([{}] * (MAX_RECEIVE_BATCH_SIZE + 1))

	def test_message_description(self):
		payload = {
			"entry": [{
				"changes": [{
					"field": "messages",
					"value": {
						"metadata": {"phone_number_id": "PHONE-1"},
						"messages": [{"id": "wamid.1", "from": "919999999999", "type": "text"}],
					},
				}],
			}],
		}
		self.assertEqual(
			describe_payload(payload),
			{
				"event_type": "message:text",
				"channel_key": "PHONE-1",
				"external_id": "wamid.1",
				"conversation_key": "919999999999",
			},
		)

	def test_fingerprint_ignores_key_order(self):
		self.assertEqual(payload_fingerprint({"a": 1, "b": 2}), payload_fingerprint({"b": 2, "a": 1}))

	@patch("frappe_whatsapp_core.api.enqueue_event_batch")
	@patch("frappe_whatsapp_core.api.process_event_batch")
	@patch("frappe_whatsapp_core.api.frappe.db.bulk_insert")
	@patch("frappe_whatsapp_core.api.frappe.get_all", return_value=[])
	def test_inbound_message_batch_is_durably_queued_after_ingress_commit(
		self, _get_all, bulk_insert, process_batch, enqueue_batch
	):
		payloads = [
			{"entry": [{"changes": [{"field": "messages", "value": {
				"metadata": {"phone_number_id": "PHONE-1"},
				"messages": [{"id": f"wamid.{index}", "from": "919999999999", "type": "text"}],
			}}]}]}
			for index in range(3)
		]
		result = receive_batch(payloads)
		self.assertEqual(result["inserted"], 3)
		self.assertEqual(result["status"], "queued")
		self.assertEqual(result["immediate"], 0)
		self.assertEqual(result["deferred"], 3)
		bulk_insert.assert_called_once()
		process_batch.assert_not_called()
		enqueue_batch.assert_called_once()
		self.assertEqual(len(enqueue_batch.call_args.args[0]), 3)
		self.assertTrue(enqueue_batch.call_args.kwargs["enqueue_after_commit"])
		self.assertEqual(
			enqueue_batch.call_args.kwargs["serialization_key"],
			"919999999999",
		)

	@patch("frappe_whatsapp_core.api.enqueue_event_batch")
	@patch("frappe_whatsapp_core.api.process_event_batch")
	@patch("frappe_whatsapp_core.api.frappe.db.bulk_insert")
	@patch("frappe_whatsapp_core.api.frappe.get_all", return_value=[])
	def test_small_status_batch_is_projected_immediately(
		self, _get_all, bulk_insert, process_batch, enqueue_batch
	):
		process_batch.return_value = [
			{"event_id": f"event-{index}", "status": "completed"}
			for index in range(3)
		]
		payloads = [{
			"entry": [{"changes": [{"field": "messages", "value": {
				"metadata": {"phone_number_id": "PHONE-1"},
				"statuses": [{
					"id": f"wamid.{index}",
					"recipient_id": "919999999999",
					"status": "read",
				}],
			}}]}],
		} for index in range(3)]

		result = receive_batch(payloads)

		self.assertEqual(result["status"], "processed")
		self.assertEqual(result["immediate"], 3)
		self.assertEqual(result["deferred"], 0)
		bulk_insert.assert_called_once()
		process_batch.assert_called_once()
		enqueue_batch.assert_not_called()

	@patch("frappe_whatsapp_core.api.enqueue_event_batch")
	@patch("frappe_whatsapp_core.api.process_event_batch")
	@patch("frappe_whatsapp_core.api.frappe.db.bulk_insert")
	@patch("frappe_whatsapp_core.api.frappe.get_all", return_value=[])
	def test_large_status_batch_stays_deferred(
		self, _get_all, bulk_insert, process_batch, enqueue_batch
	):
		payloads = [{
			"entry": [{"changes": [{"field": "messages", "value": {
				"metadata": {"phone_number_id": "PHONE-1"},
				"statuses": [{
					"id": f"wamid.{index}",
					"recipient_id": "919999999999",
					"status": "read",
				}],
			}}]}],
		} for index in range(IMMEDIATE_STATUS_BATCH_SIZE + 1)]

		result = receive_batch(payloads)

		self.assertEqual(result["immediate"], 0)
		self.assertEqual(result["deferred"], IMMEDIATE_STATUS_BATCH_SIZE + 1)
		bulk_insert.assert_called_once()
		process_batch.assert_not_called()
		enqueue_batch.assert_called_once()

	@patch("frappe_whatsapp_core.dispatcher.frappe.enqueue")
	def test_single_event_enqueue_uses_deadlock_safe_batch_job(self, enqueue):
		from frappe_whatsapp_core.dispatcher import enqueue_event

		enqueue_event("event-1", enqueue_after_commit=True)
		enqueue.assert_called_once_with(
			"frappe_whatsapp_core.dispatcher.process_event_batch",
			queue="short",
			enqueue_after_commit=True,
			event_ids=["event-1"],
			serialization_key=None,
		)

	@patch("frappe_whatsapp_core.dispatcher.enqueue_event_rows_by_lane")
	@patch(
		"frappe_whatsapp_core.dispatcher.frappe.get_all",
		return_value=[frappe._dict(name="FAILED-1", event_type="message:text", conversation_key="chat-1")],
	)
	@patch("frappe_whatsapp_core.dispatcher.frappe.db.sql", return_value=[])
	def test_periodic_failure_retry_does_not_compete_for_pending_events(
		self, db_sql, get_all, enqueue_rows
	):
		self.assertEqual(retry_failed_events(), 1)
		self.assertEqual(get_all.call_args.kwargs["filters"]["status"], "Failed")
		enqueue_rows.assert_called_once_with(
			[frappe._dict(name="FAILED-1", event_type="message:text", conversation_key="chat-1")],
			enqueue_after_commit=True,
		)

	@patch("frappe_whatsapp_core.dispatcher.enqueue_event_rows_by_lane")
	@patch("frappe_whatsapp_core.dispatcher.enqueue_event_batch")
	@patch("frappe_whatsapp_core.dispatcher.frappe.get_all", return_value=[])
	@patch(
		"frappe_whatsapp_core.dispatcher.frappe.db.sql",
		side_effect=[["STALE-STATUS-1"], None],
	)
	def test_periodic_failure_retry_recovers_exhausted_timestamp_mismatch(
		self, db_sql, get_all, enqueue_batch, enqueue_rows
	):
		self.assertEqual(retry_failed_events(), 1)
		self.assertIn("TimestampMismatchError", db_sql.call_args_list[0].args[0])
		self.assertIn("Document has been modified", db_sql.call_args_list[0].args[0])
		self.assertIn("attempts = 0", db_sql.call_args_list[1].args[0])
		enqueue_batch.assert_called_once_with(
			["STALE-STATUS-1"], enqueue_after_commit=True,
		)
		enqueue_rows.assert_not_called()

	@patch("frappe_whatsapp_core.dispatcher.enqueue_event_batch")
	def test_repair_queue_preserves_conversation_lanes(self, enqueue_batch):
		enqueue_event_rows_by_lane([
			frappe._dict(name="human-1", event_type="message:text", conversation_key="chat-1"),
			frappe._dict(name="human-2", event_type="message:image", conversation_key="chat-1"),
			frappe._dict(name="human-3", event_type="call:voice", conversation_key="chat-2"),
			frappe._dict(name="status-1", event_type="status:read", conversation_key="chat-1"),
		], enqueue_after_commit=True)

		self.assertEqual(enqueue_batch.call_count, 3)
		enqueue_batch.assert_any_call(
			["human-1", "human-2"],
			enqueue_after_commit=True,
			serialization_key="chat-1",
		)
		enqueue_batch.assert_any_call(
			["human-3"],
			enqueue_after_commit=True,
			serialization_key="chat-2",
		)
		enqueue_batch.assert_any_call(["status-1"], enqueue_after_commit=True)

	@patch("frappe_whatsapp_core.dispatcher.frappe.enqueue")
	def test_dispatcher_chunks_realtime_work_at_one_hundred(self, enqueue):
		enqueue_event_batch([f"event-{index}" for index in range(205)], enqueue_after_commit=True)
		self.assertEqual(enqueue.call_count, 3)
		self.assertEqual([len(call.kwargs["event_ids"]) for call in enqueue.call_args_list], [100, 100, 5])
		self.assertTrue(all(call.kwargs["enqueue_after_commit"] for call in enqueue.call_args_list))

	@patch("frappe_whatsapp_core.dispatcher.frappe.enqueue")
	def test_orphan_status_retry_is_after_commit_with_bounded_backoff(self, enqueue):
		enqueue_orphan_status_retry(["event-1", "event-1", "event-2"], attempt=3)
		enqueue.assert_called_once_with(
			"frappe_whatsapp_core.dispatcher.retry_orphan_status_events",
			queue="short",
			enqueue_after_commit=True,
			event_ids=["event-1", "event-2"],
			delay_seconds=1.0,
		)

	@patch("frappe_whatsapp_core.dispatcher.process_event_batch", return_value=[{"status": "completed"}])
	@patch("frappe_whatsapp_core.dispatcher.time.sleep")
	@patch("frappe_whatsapp_core.dispatcher.frappe.db.commit")
	def test_orphan_status_retry_runs_in_fresh_job(self, commit, sleep, process_batch):
		result = retry_orphan_status_events(["event-1"], delay_seconds=99)
		sleep.assert_called_once_with(2.0)
		commit.assert_called_once_with()
		process_batch.assert_called_once_with(["event-1"])
		self.assertEqual(result, [{"status": "completed"}])

	@patch("frappe_whatsapp_core.dispatcher.enqueue_event_rows_by_lane")
	@patch("frappe_whatsapp_core.dispatcher.frappe.db.sql")
	@patch(
		"frappe_whatsapp_core.dispatcher.frappe.get_all",
		return_value=[
			frappe._dict(name="event-1", event_type="message:text", conversation_key="chat-1"),
			frappe._dict(name="event-2", event_type="message:text", conversation_key="chat-1"),
		],
	)
	def test_stale_event_recovery_conditionally_requeues_after_commit(
		self, _get_all, db_sql, enqueue_rows
	):
		result = retry_stale_events()

		self.assertEqual(result, {"requeued": 2})
		self.assertIn("status IN ('Pending', 'Queued')", db_sql.call_args.args[0])
		enqueue_rows.assert_called_once_with(
			[
				frappe._dict(name="event-1", event_type="message:text", conversation_key="chat-1"),
				frappe._dict(name="event-2", event_type="message:text", conversation_key="chat-1"),
			],
			enqueue_after_commit=True,
		)

	@patch("frappe_whatsapp_core.dispatcher.publish_batch_notice")
	@patch("frappe_whatsapp_core.dispatcher.publish_message_changes")
	@patch("frappe_whatsapp_core.dispatcher.frappe.get_all", return_value=[])
	@patch("frappe_whatsapp_core.dispatcher.process_event")
	def test_empty_event_batch_does_not_emit_inbox_refresh(
		self, process, _get_all, publish_changes, publish_notice
	):
		process.return_value = {"status": "completed", "projections": []}
		result = process_event_batch(["event-1", "event-2"])

		self.assertEqual(len(result), 2)
		publish_changes.assert_called_once_with([])
		publish_notice.assert_called_once_with([])

	@patch("frappe_whatsapp_core.dispatcher._process_status_event_batch")
	@patch(
		"frappe_whatsapp_core.dispatcher.frappe.get_all",
		return_value=["event-1", "event-2"],
	)
	def test_pure_status_batch_uses_bulk_fast_lane(self, _get_all, status_batch):
		status_batch.return_value = [
			{"event_id": "event-1", "status": "completed"},
			{"event_id": "event-2", "status": "completed"},
		]

		result = process_event_batch(["event-1", "event-2"])

		self.assertEqual(len(result), 2)
		status_batch.assert_called_once_with(["event-1", "event-2"])

	@patch("frappe_whatsapp_core.dispatcher.time.sleep")
	@patch("frappe_whatsapp_core.dispatcher.frappe.db.rollback")
	@patch("frappe_whatsapp_core.dispatcher._process_status_event_batch")
	@patch(
		"frappe_whatsapp_core.dispatcher.frappe.get_all",
		return_value=["event-1"],
	)
	def test_status_batch_retries_the_whole_transaction_after_deadlock(
		self, _get_all, status_batch, rollback, sleep
	):
		status_batch.side_effect = [
			frappe.QueryDeadlockError("synthetic deadlock"),
			[{"event_id": "event-1", "status": "completed"}],
		]

		result = process_event_batch(["event-1"])

		self.assertEqual(result[0]["status"], "completed")
		self.assertEqual(status_batch.call_count, 2)
		rollback.assert_called_once_with()
		sleep.assert_called_once()

	@patch("frappe_whatsapp_core.dispatcher.time.sleep")
	@patch("frappe_whatsapp_core.dispatcher.frappe.db.rollback")
	@patch("frappe_whatsapp_core.dispatcher._process_status_event_batch")
	@patch(
		"frappe_whatsapp_core.dispatcher.frappe.get_all",
		return_value=["event-1"],
	)
	def test_status_batch_retries_the_whole_transaction_after_stale_identity(
		self, _get_all, status_batch, rollback, sleep
	):
		status_batch.side_effect = [
			frappe.TimestampMismatchError("synthetic stale identity"),
			[{"event_id": "event-1", "status": "completed"}],
		]

		result = process_event_batch(["event-1"])

		self.assertEqual(result[0]["status"], "completed")
		self.assertEqual(status_batch.call_count, 2)
		rollback.assert_called_once_with()
		sleep.assert_called_once()

	@patch("frappe_whatsapp_core.dispatcher.frappe.db.sql")
	@patch("frappe_whatsapp_core.dispatcher.frappe.get_all")
	def test_status_fast_lane_locks_messages_in_order(self, get_all, db_sql):
		get_all.return_value = ["MSG-1"]
		events = [frappe._dict(payload=json.dumps({
			"entry": [{"changes": [{"value": {"statuses": [{"id": "wamid.1"}]}}]}],
		}))]

		message_names = _lock_status_projection_rows(events)

		self.assertEqual(message_names, ["MSG-1"])
		self.assertEqual(db_sql.call_count, 1)
		self.assertIn("ORDER BY name", db_sql.call_args_list[0].args[0])
		self.assertIn("FOR UPDATE", db_sql.call_args_list[0].args[0])

	@patch("frappe_whatsapp_core.dispatcher.frappe.db.sql")
	def test_status_fast_lane_locks_events_before_projection(self, db_sql):
		db_sql.return_value = [
			frappe._dict(name="EVENT-1", status="Pending"),
			frappe._dict(name="EVENT-2", status="Completed"),
		]

		events = _get_locked_core_event_rows(["EVENT-2", "EVENT-1", "EVENT-1"])

		self.assertEqual([row.name for row in events], ["EVENT-1", "EVENT-2"])
		self.assertEqual(
			db_sql.call_args.args[1]["event_ids"],
			["EVENT-1", "EVENT-2"],
		)
		self.assertIn("ORDER BY name", db_sql.call_args.args[0])
		self.assertIn("FOR UPDATE", db_sql.call_args.args[0])
		self.assertTrue(db_sql.call_args.kwargs["as_dict"])

	@patch("frappe_whatsapp_core.dispatcher._publish_batch_refresh")
	@patch("frappe_whatsapp_core.dispatcher.frappe.db.sql")
	@patch("frappe_whatsapp_core.dispatcher.frappe.db.savepoint")
	@patch(
		"frappe_whatsapp_core.dispatcher.materialize_event",
		return_value=[{"kind": "status", "status": "updated", "name": "MSG-1"}],
	)
	@patch("frappe_whatsapp_core.dispatcher._lock_status_projection_rows")
	@patch("frappe_whatsapp_core.dispatcher._get_locked_core_event_rows")
	def test_status_fast_lane_recovers_exhausted_failed_orphan(
		self,
		locked_events,
		_lock_messages,
		materialize,
		_savepoint,
		db_sql,
		_publish,
	):
		locked_events.return_value = [frappe._dict(
			name="EVENT-1",
			payload="{}",
			status="Failed",
			attempts=6,
		)]

		result = _process_status_event_batch(["EVENT-1"])

		self.assertEqual(result[0]["status"], "completed")
		materialize.assert_called_once()
		self.assertEqual(db_sql.call_count, 1)
		self.assertIn("status = 'Completed'", db_sql.call_args.args[0])
		self.assertIn("error = ''", db_sql.call_args.args[0])
		self.assertEqual(db_sql.call_args.args[1]["event_ids"], ["EVENT-1"])

	@patch("frappe_whatsapp_core.dispatcher._publish_batch_refresh")
	@patch("frappe_whatsapp_core.dispatcher.frappe.db.sql")
	@patch("frappe_whatsapp_core.dispatcher.materialize_event")
	@patch("frappe_whatsapp_core.dispatcher._lock_status_projection_rows")
	@patch("frappe_whatsapp_core.dispatcher._get_locked_core_event_rows")
	def test_status_fast_lane_duplicate_completed_event_is_noop(
		self,
		locked_events,
		_lock_messages,
		materialize,
		db_sql,
		_publish,
	):
		locked_events.return_value = [frappe._dict(
			name="EVENT-1",
			payload="{}",
			status="Completed",
			attempts=1,
		)]

		result = _process_status_event_batch(["EVENT-1"])

		self.assertEqual(result, [{"event_id": "EVENT-1", "status": "completed"}])
		materialize.assert_not_called()
		db_sql.assert_not_called()

	@patch("frappe_whatsapp_core.dispatcher._publish_batch_refresh")
	@patch("frappe_whatsapp_core.dispatcher.frappe.db.set_value")
	@patch("frappe_whatsapp_core.dispatcher.frappe.get_traceback", return_value="bad status")
	@patch("frappe_whatsapp_core.dispatcher.frappe.db.rollback")
	@patch("frappe_whatsapp_core.dispatcher.frappe.db.savepoint")
	@patch("frappe_whatsapp_core.dispatcher.materialize_event", side_effect=ValueError("bad"))
	@patch("frappe_whatsapp_core.dispatcher._lock_status_projection_rows")
	@patch("frappe_whatsapp_core.dispatcher._get_locked_core_event_rows")
	def test_status_fast_lane_failure_increments_existing_attempt_count(
		self,
		locked_events,
		_lock_messages,
		_materialize,
		_savepoint,
		_rollback,
		_traceback,
		set_value,
		_publish,
	):
		locked_events.return_value = [frappe._dict(
			name="EVENT-1", payload="{}", status="Pending", attempts=3,
		)]

		result = _process_status_event_batch(["EVENT-1"])

		self.assertEqual(result, [{"event_id": "EVENT-1", "status": "failed"}])
		set_value.assert_called_once_with(
			"WhatsApp Core Event",
			"EVENT-1",
			{"status": "Failed", "error": "bad status", "attempts": 4},
			update_modified=False,
		)

	def test_core_event_external_id_has_search_index(self):
		schema_path = (
			Path(__file__).resolve().parents[1]
			/ "frappe_whatsapp_core"
			/ "doctype"
			/ "whatsapp_core_event"
			/ "whatsapp_core_event.json"
		)
		fields = json.loads(schema_path.read_text())["fields"]
		external_id = next(
			field for field in fields if field.get("fieldname") == "external_id"
		)

		self.assertEqual(external_id.get("search_index"), 1)

	@patch("frappe_whatsapp_core.ai_summaries.enqueue_summary_for_messages")
	@patch("frappe_whatsapp_core.dispatcher.publish_batch_notice")
	@patch("frappe_whatsapp_core.dispatcher.publish_message_changes")
	@patch("frappe_whatsapp_core.dispatcher.frappe.get_all")
	@patch("frappe_whatsapp_core.dispatcher.process_event")
	def test_event_batch_emits_permission_scoped_message_delta(
		self, process, get_all, publish_changes, publish_notice, enqueue_summary
	):
		process.return_value = {
			"status": "completed",
			"projections": [{"kind": "message", "status": "created", "name": "MSG-1"}],
		}
		get_all.return_value = [{
			"name": "MSG-1",
			"conversation": "CONV-1",
			"direction": "Inbound",
			"message_type": "image",
			"body": "Proof",
			"content": json.dumps({"image": {"id": "MEDIA-1"}}),
		}]

		process_event_batch(["event-1"])

		publish_changes.assert_called_once_with([
			{"kind": "message", "status": "created", "name": "MSG-1"}
		])
		publish_notice.assert_called_once_with(["message"])
		self.assertFalse(
			any(call.args and call.args[0] == "WhatsApp Core Message" for call in get_all.call_args_list)
		)
		enqueue_summary.assert_called_once_with(
			["MSG-1"],
			enqueue_after_commit=True,
		)

	@patch("frappe_whatsapp_core.api.publish_message_changes")
	@patch("frappe_whatsapp_core.api.frappe.get_all", return_value=[])
	@patch("frappe_whatsapp_core.api._apply_outbound_result_batch")
	@patch("frappe_whatsapp_core.permissions.frappe.get_roles", return_value=["System Manager"])
	def test_outbound_result_batch_accepts_relay_provider_metadata(
		self, _get_roles, apply_result, _get_all, publish
	):
		apply_result.return_value = [{"status": "applied", "message": "MSG-1"}]
		result = receive_outbound_results(
			[
				{
					"idempotency_key": "key-1",
					"status": "failed",
					"meta_error": {"code": 131047},
					"response": {"error": "failed"},
					"updated_at": "2026-08-07T10:00:00Z",
				}
			]
		)

		self.assertEqual(result["count"], 1)
		apply_result.assert_called_once()
		self.assertEqual(apply_result.call_args.args[0][0]["meta_error"]["code"], 131047)
		publish.assert_called_once()

	@patch("frappe_whatsapp_core.api.publish_message_changes")
	@patch("frappe_whatsapp_core.api.frappe.get_all", return_value=[])
	@patch("frappe_whatsapp_core.api._apply_outbound_result_batch")
	@patch("frappe_whatsapp_core.permissions.frappe.get_roles", return_value=["System Manager"])
	def test_outbound_result_contract_accepts_forty_results(
		self, _get_roles, apply_result, _get_all, publish
	):
		results = [
			{
				"idempotency_key": f"batch-result-{index}",
				"status": "sent",
				"success": 1,
				"meta_message_id": f"wamid.batch-{index}",
			}
			for index in range(40)
		]
		apply_result.return_value = [
			{"status": "applied", "message": f"MSG-{index}"}
			for index in range(40)
		]

		response = receive_outbound_results(results)

		self.assertEqual(response["count"], 40)
		self.assertEqual(len(apply_result.call_args.args[0]), 40)
		publish.assert_called_once()

	@patch("frappe_whatsapp_core.api.random.uniform", return_value=0)
	@patch("frappe_whatsapp_core.api.time.sleep")
	@patch("frappe_whatsapp_core.api.frappe.db.rollback")
	@patch("frappe_whatsapp_core.api._receive_outbound_results_once")
	@patch("frappe_whatsapp_core.permissions.frappe.get_roles", return_value=["System Manager"])
	def test_outbound_result_window_retries_complete_transaction_after_deadlock(
		self,
		_get_roles,
		apply_once,
		rollback,
		sleep,
		_uniform,
	):
		applied = {"status": "applied", "count": 1, "results": []}
		apply_once.side_effect = [frappe.QueryDeadlockError("deadlock"), applied]
		results = [{"idempotency_key": "key-1", "status": "sent", "success": 1}]

		self.assertEqual(receive_outbound_results(results), applied)
		self.assertEqual(apply_once.call_count, 2)
		rollback.assert_called_once_with()
		sleep.assert_called_once()

	def test_outbound_result_handler_tolerates_provider_metadata(self):
		parameters = signature(__import__("frappe_whatsapp_core.api", fromlist=["_apply_outbound_result"])._apply_outbound_result).parameters
		self.assertTrue(any(parameter.kind == Parameter.VAR_KEYWORD for parameter in parameters.values()))

	@patch("frappe_whatsapp_core.api.publish_message_changes")
	@patch("frappe_whatsapp_core.api.frappe.get_all")
	@patch("frappe_whatsapp_core.permissions.frappe.get_roles", return_value=["System Manager"])
	def test_outbound_result_batch_acknowledges_control_operations(
		self, _get_roles, get_all, publish
	):
		result = receive_outbound_results([
			{
				"idempotency_key": "read:wamid.inbound",
				"status": "sent",
				"success": 1,
			}
		])

		self.assertEqual(result["count"], 0)
		self.assertEqual(result["ignored"], 1)
		self.assertEqual(result["results"][0]["reason"], "control_operation")
		get_all.assert_not_called()
		publish.assert_not_called()

	@patch("frappe_whatsapp_core.api.enqueue_campaign_refresh_for_messages")
	@patch("frappe_whatsapp_core.api.publish_message_changes")
	@patch(
		"frappe_whatsapp_core.api.frappe.get_all",
		side_effect=[
			[],
			[
				frappe._dict(
					name="MSG-QUEUED",
					conversation="CONV-2",
					delivery_status="Sent",
					provider_message_id="wamid.sent",
				),
			],
		],
	)
	@patch("frappe_whatsapp_core.api.frappe.clear_document_cache")
	@patch("frappe_whatsapp_core.api.frappe.db.bulk_update")
	@patch("frappe_whatsapp_core.api.frappe.db.sql")
	@patch("frappe_whatsapp_core.permissions.frappe.get_roles", return_value=["System Manager"])
	def test_outbound_result_batch_uses_one_monotonic_bulk_update(
		self,
		_get_roles,
		db_sql,
		bulk_update,
		_clear_cache,
		_get_all,
		publish,
		refresh,
	):
		db_sql.return_value = [
			frappe._dict(
				name="MSG-READ",
				idempotency_key="result-read",
				delivery_status="Read",
				conversation="CONV-1",
				provider_message_id="wamid.read",
				failure=None,
			),
			frappe._dict(
				name="MSG-QUEUED",
				idempotency_key="result-sent",
				delivery_status="Queued",
				conversation="CONV-2",
				provider_message_id="local:result-sent",
				failure=None,
			),
		]

		result = receive_outbound_results([
			{
				"idempotency_key": "result-read",
				"status": "failed",
				"success": 0,
				"error": "late failure",
			},
			{
				"idempotency_key": "result-sent",
				"status": "sent",
				"success": 1,
				"meta_message_id": "wamid.sent",
			},
		])

		self.assertEqual(result["count"], 1)
		self.assertEqual(result["unchanged"], 1)
		updates = bulk_update.call_args.args[1]
		self.assertNotIn("MSG-READ", updates)
		self.assertEqual(updates["MSG-QUEUED"]["delivery_status"], "Sent")
		self.assertEqual(updates["MSG-QUEUED"]["provider_message_id"], "wamid.sent")
		self.assertEqual(result["results"][0]["delivery_status"], "Read")
		self.assertEqual(result["results"][0]["status"], "noop")
		refresh.assert_called_once_with(["MSG-QUEUED"])
		publish.assert_called_once()
		publish.assert_called_once_with([
			{"kind": "status", "status": "updated", "name": "MSG-QUEUED"}
		])

	@patch("frappe_whatsapp_core.api.enqueue_campaign_refresh_for_messages")
	@patch("frappe_whatsapp_core.api.publish_message_changes")
	@patch(
		"frappe_whatsapp_core.api.frappe.get_all",
		side_effect=[
			[],
			[frappe._dict(
				name="MSG-1",
				conversation="CONV-1",
				delivery_status="Sent",
				provider_message_id="wamid.final",
			)],
		],
	)
	@patch("frappe_whatsapp_core.api.frappe.clear_document_cache")
	@patch("frappe_whatsapp_core.api.frappe.db.bulk_update")
	@patch(
		"frappe_whatsapp_core.api.frappe.db.sql",
		return_value=[frappe._dict(
			name="MSG-1",
			idempotency_key="result-1",
			conversation="CONV-1",
			delivery_status="Queued",
			provider_message_id="local:result-1",
			failure=None,
		)],
	)
	@patch("frappe_whatsapp_core.permissions.frappe.get_roles", return_value=["System Manager"])
	def test_duplicate_result_key_is_coalesced_to_last_batch_observation(
		self,
		_get_roles,
		_db_sql,
		bulk_update,
		_clear,
		_get_all,
		_publish,
		_refresh,
	):
		result = receive_outbound_results([
			{
				"idempotency_key": "result-1",
				"status": "failed",
				"success": 0,
				"error": "stale retry",
			},
			{
				"idempotency_key": "result-1",
				"status": "sent",
				"success": 1,
				"meta_message_id": "wamid.final",
			},
		])

		self.assertEqual(result["count"], 1)
		self.assertEqual(result["ignored"], 1)
		self.assertEqual(result["results"][0]["reason"], "superseded_in_batch")
		self.assertEqual(result["results"][1]["status"], "applied")
		self.assertEqual(
			bulk_update.call_args.args[1]["MSG-1"]["delivery_status"],
			"Sent",
		)
