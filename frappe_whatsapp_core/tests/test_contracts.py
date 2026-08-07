import unittest
from inspect import Parameter, signature
from unittest.mock import patch

from frappe_whatsapp_core.api import (
	describe_payload,
	payload_fingerprint,
	receive_batch,
	receive_outbound_results,
)
from frappe_whatsapp_core.dispatcher import enqueue_event_batch, process_event_batch


class TestPayloadContract(unittest.TestCase):
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
	@patch("frappe_whatsapp_core.api.frappe.db.bulk_insert")
	@patch("frappe_whatsapp_core.api.frappe.get_all", return_value=[])
	def test_batch_uses_one_bulk_insert(self, _get_all, bulk_insert, enqueue_batch):
		payloads = [
			{"entry": [{"changes": [{"field": "messages", "value": {
				"metadata": {"phone_number_id": "PHONE-1"},
				"messages": [{"id": f"wamid.{index}", "from": "919999999999", "type": "text"}],
			}}]}]}
			for index in range(3)
		]
		result = receive_batch(payloads)
		self.assertEqual(result["inserted"], 3)
		bulk_insert.assert_called_once()
		enqueue_batch.assert_called_once()

	@patch("frappe_whatsapp_core.dispatcher.frappe.enqueue")
	def test_dispatcher_chunks_realtime_work_at_one_hundred(self, enqueue):
		enqueue_event_batch([f"event-{index}" for index in range(205)], enqueue_after_commit=True)
		self.assertEqual(enqueue.call_count, 3)
		self.assertEqual([len(call.kwargs["event_ids"]) for call in enqueue.call_args_list], [100, 100, 5])
		self.assertTrue(all(call.kwargs["enqueue_after_commit"] for call in enqueue.call_args_list))

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
