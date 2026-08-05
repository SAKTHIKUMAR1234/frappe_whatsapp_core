import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from frappe_whatsapp_core.hub_client import mark_message_read
from frappe_whatsapp_core.outbound import _message_payload, _validate_rich_payload


class TestRichMessages(FrappeTestCase):
	def test_media_and_quoted_reply_payload_cannot_override_recipient(self):
		content = {
			"payload": {
				"link": "https://cdn.example.test/invoice.pdf",
				"caption": "Invoice",
				"context_message_id": "wamid.reply",
			}
		}
		message = SimpleNamespace(
			message_type="document",
			body="Invoice",
			content=json.dumps(content),
		)
		payload = _message_payload(message, "919876543210")
		self.assertEqual(payload["to"], "919876543210")
		self.assertEqual(payload["document"]["caption"], "Invoice")
		self.assertEqual(payload["context"]["message_id"], "wamid.reply")
		self.assertNotIn("context_message_id", payload["document"])

	def test_contacts_and_native_flow_are_supported(self):
		contacts = _validate_rich_payload(
			"contacts",
			{"contacts": [{"name": {"formatted_name": "Customer"}}]},
		)
		message = SimpleNamespace(
			message_type="contacts",
			body="[Contact]",
			content=json.dumps({"payload": contacts}),
		)
		payload = _message_payload(message, "14155550100")
		self.assertIsInstance(payload["contacts"], list)

		flow = _validate_rich_payload(
			"interactive",
			{
				"type": "flow",
				"body": {"text": "Complete the form"},
				"action": {
					"name": "flow",
					"parameters": {"flow_id": "123", "flow_cta": "Open"},
				},
			},
		)
		self.assertEqual(flow["type"], "flow")

	def test_transport_fields_are_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			_validate_rich_payload(
				"image",
				{"id": "MEDIA", "to": "attacker-controlled"},
			)


class TestProviderPresence(FrappeTestCase):
	@patch("frappe_whatsapp_core.hub_client.call_management")
	@patch("frappe_whatsapp_core.hub_client.get_settings")
	def test_read_and_typing_use_mapped_account(self, get_settings, call_management):
		settings = MagicMock()
		settings.get_account_name.return_value = "Hub Account"
		get_settings.return_value = settings
		call_management.return_value = {"success": True}

		result = mark_message_read("Channel", "wamid.inbound", typing_indicator=True)
		self.assertTrue(result["success"])
		self.assertEqual(call_management.call_args.args[1]["account_name"], "Hub Account")
		self.assertEqual(call_management.call_args.args[1]["typing_indicator"], 1)
