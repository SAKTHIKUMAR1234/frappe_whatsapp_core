import json
import unittest
from inspect import Parameter, signature
from unittest.mock import patch

import frappe

from frappe_whatsapp_core.api import (
	MAX_RECEIVE_BATCH_SIZE,
	_apply_outbound_result,
	describe_payload,
	payload_fingerprint,
	receive_batch,
	receive_outbound_results,
)
from frappe_whatsapp_core.dispatcher import (
	_has_orphan_status,
	_lock_status_projection_rows,
	enqueue_event_batch,
	enqueue_orphan_status_retry,
	enqueue_waiting_status_events,
	process_event_batch,
	retry_orphan_status_events,
	retry_stale_events,
)
from frappe_whatsapp_core.outbound import _mark_sent


class TestPayloadContract(unittest.TestCase):
	@patch("frappe_whatsapp_core.dispatcher.enqueue_event_batch")
	@patch("frappe_whatsapp_core.dispatcher.frappe.db.sql")
	@patch("frappe_whatsapp_core.dispatcher.frappe.get_all", return_value=["EVENT-1"])
	def test_provider_binding_revives_exhausted_orphan_receipt(
		self, get_all, db_sql, enqueue_batch
	):
		count = enqueue_waiting_status_events(["wamid.1"])

		self.assertEqual(count, 1)
		self.assertNotIn("attempts", get_all.call_args.kwargs["filters"])
		self.assertIn("attempts = 0", db_sql.call_args.args[0])
		enqueue_batch.assert_called_once_with(["EVENT-1"], enqueue_after_commit=True)

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
	@patch("frappe_whatsapp_core.api.frappe.publish_realtime")
	@patch("frappe_whatsapp_core.api.frappe.get_doc")
	@patch("frappe_whatsapp_core.api.frappe.db.get_value")
	@patch("frappe_whatsapp_core.api.frappe.db.exists", return_value=False)
	def test_provider_id_collision_is_terminal_failure_not_callback_error(
		self, _exists, get_value, get_doc, publish, refresh
	):
		get_value.side_effect = ["MSG-NEW", "MSG-EXISTING"]
		message = frappe._dict(
			name="MSG-NEW",
			conversation="CONV-1",
			delivery_status="Queued",
			provider_message_id="local:new",
			failure=None,
			save=lambda **_kwargs: None,
		)
		get_doc.return_value = message

		result = _apply_outbound_result(
			idempotency_key="new-result",
			status="sent",
			success=1,
			meta_message_id="wamid.collision",
			status_code=200,
		)

		self.assertEqual(result["status"], "applied")
		self.assertEqual(result["delivery_status"], "Failed")
		self.assertEqual(message.provider_message_id, "local:new")
		self.assertEqual(json.loads(message.failure)["code"], "provider_message_id_collision")
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
	def test_inbound_message_batch_is_projected_immediately(
		self, _get_all, bulk_insert, process_batch, enqueue_batch
	):
		process_batch.return_value = [
			{"event_id": f"event-{index}", "status": "completed"}
			for index in range(3)
		]
		payloads = [
			{"entry": [{"changes": [{"field": "messages", "value": {
				"metadata": {"phone_number_id": "PHONE-1"},
				"messages": [{"id": f"wamid.{index}", "from": "919999999999", "type": "text"}],
			}}]}]}
			for index in range(3)
		]
		result = receive_batch(payloads)
		self.assertEqual(result["inserted"], 3)
		self.assertEqual(result["status"], "processed")
		self.assertEqual(result["immediate"], 3)
		self.assertEqual(result["deferred"], 0)
		bulk_insert.assert_called_once()
		process_batch.assert_called_once()
		self.assertEqual(len(process_batch.call_args.args[0]), 3)
		enqueue_batch.assert_not_called()

	@patch("frappe_whatsapp_core.api.enqueue_event_batch")
	@patch("frappe_whatsapp_core.api.process_event_batch")
	@patch("frappe_whatsapp_core.api.frappe.db.bulk_insert")
	@patch("frappe_whatsapp_core.api.frappe.get_all", return_value=[])
	def test_status_batch_stays_deferred(
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
		} for index in range(3)]

		result = receive_batch(payloads)

		self.assertEqual(result["immediate"], 0)
		self.assertEqual(result["deferred"], 3)
		bulk_insert.assert_called_once()
		process_batch.assert_not_called()
		enqueue_batch.assert_called_once()
		self.assertEqual(len(enqueue_batch.call_args.args[0]), 3)

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
	def test_orphan_status_retry_runs_in_fresh_job(self, sleep, process_batch):
		result = retry_orphan_status_events(["event-1"], delay_seconds=99)
		sleep.assert_called_once_with(2.0)
		process_batch.assert_called_once_with(["event-1"])
		self.assertEqual(result, [{"status": "completed"}])

	@patch("frappe_whatsapp_core.dispatcher.enqueue_event_batch")
	@patch("frappe_whatsapp_core.dispatcher.frappe.db.sql")
	@patch(
		"frappe_whatsapp_core.dispatcher.frappe.get_all",
		return_value=["event-1", "event-2"],
	)
	def test_stale_event_recovery_conditionally_requeues_after_commit(
		self, _get_all, db_sql, enqueue_batch
	):
		result = retry_stale_events()

		self.assertEqual(result, {"requeued": 2})
		self.assertIn("status IN ('Pending', 'Queued')", db_sql.call_args.args[0])
		enqueue_batch.assert_called_once_with(
			["event-1", "event-2"],
			enqueue_after_commit=True,
		)

	@patch("frappe_whatsapp_core.dispatcher.frappe.publish_realtime")
	@patch("frappe_whatsapp_core.dispatcher.frappe.get_all", return_value=[])
	@patch("frappe_whatsapp_core.dispatcher.process_event")
	def test_event_batch_emits_one_after_commit_refresh(self, process, _get_all, publish):
		process.return_value = {"status": "completed", "projections": []}
		result = process_event_batch(["event-1", "event-2"])

		self.assertEqual(len(result), 2)
		publish.assert_called_once()
		self.assertEqual(publish.call_args.args[0], "whatsapp_core_batch_committed")
		self.assertTrue(publish.call_args.kwargs["after_commit"])

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

	@patch("frappe_whatsapp_core.dispatcher.frappe.publish_realtime")
	@patch("frappe_whatsapp_core.dispatcher.frappe.get_all")
	@patch("frappe_whatsapp_core.dispatcher.process_event")
	def test_event_batch_includes_compact_message_deltas(self, process, get_all, publish):
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

		payload = publish.call_args.args[1]
		self.assertEqual(payload["kinds"], ["message"])
		self.assertEqual(payload["conversations"], ["CONV-1"])
		self.assertEqual(payload["message_changes"][0]["message"]["name"], "MSG-1")
		self.assertIn(
			"message_media.download_message_media",
			payload["message_changes"][0]["message"]["media_url"],
		)
		self.assertEqual(payload["message_changes"][0]["status"], "created")

	@patch("frappe_whatsapp_core.api.frappe.publish_realtime")
	@patch("frappe_whatsapp_core.api.frappe.get_all", return_value=[])
	@patch("frappe_whatsapp_core.api._apply_outbound_result")
	@patch("frappe_whatsapp_core.permissions.frappe.get_roles", return_value=["System Manager"])
	def test_outbound_result_batch_accepts_relay_provider_metadata(
		self, _get_roles, apply_result, _get_all, publish
	):
		apply_result.return_value = {"status": "applied", "message": "MSG-1"}
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
		publish.assert_called_once()

	def test_outbound_result_handler_tolerates_provider_metadata(self):
		parameters = signature(__import__("frappe_whatsapp_core.api", fromlist=["_apply_outbound_result"])._apply_outbound_result).parameters
		self.assertTrue(any(parameter.kind == Parameter.VAR_KEYWORD for parameter in parameters.values()))

	@patch("frappe_whatsapp_core.api.frappe.publish_realtime")
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
	@patch("frappe_whatsapp_core.api.frappe.publish_realtime")
	@patch(
		"frappe_whatsapp_core.api.frappe.get_all",
		side_effect=[
			[],
			[],
			[
				frappe._dict(
					name="MSG-READ",
					conversation="CONV-1",
					delivery_status="Read",
					provider_message_id="wamid.read",
				),
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
			),
			frappe._dict(
				name="MSG-QUEUED",
				idempotency_key="result-sent",
				delivery_status="Queued",
				conversation="CONV-2",
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

		self.assertEqual(result["count"], 2)
		updates = bulk_update.call_args.args[1]
		self.assertEqual(updates["MSG-READ"]["delivery_status"], "Read")
		self.assertEqual(updates["MSG-QUEUED"]["delivery_status"], "Sent")
		self.assertEqual(updates["MSG-QUEUED"]["provider_message_id"], "wamid.sent")
		self.assertEqual(result["results"][0]["delivery_status"], "Read")
		refresh.assert_called_once_with(["MSG-READ", "MSG-QUEUED"])
		publish.assert_called_once()
		payload = publish.call_args.args[1]
		self.assertEqual(payload["kinds"], ["status"])
		self.assertEqual(len(payload["message_changes"]), 2)
		self.assertEqual(payload["message_changes"][1]["message"].delivery_status, "Sent")
