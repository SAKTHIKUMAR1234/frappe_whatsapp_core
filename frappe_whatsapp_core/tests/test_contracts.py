import unittest
from unittest.mock import patch

from frappe_whatsapp_core.api import describe_payload, payload_fingerprint, receive_batch


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
