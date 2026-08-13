import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from frappe_whatsapp_core.hub_client import mark_message_read
from frappe_whatsapp_core.outbound import _message_payload, _validate_rich_payload, upload_media


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

	def test_group_payload_preserves_group_recipient_type(self):
		message = SimpleNamespace(
			message_type="text",
			body="Hello group",
			content=json.dumps({"body": "Hello group"}),
		)
		payload = _message_payload(message, "GROUP-ID", recipient_type="group")
		self.assertEqual(payload["recipient_type"], "group")
		self.assertEqual(payload["to"], "GROUP-ID")

	@patch("frappe_whatsapp_core.outbound.call_management")
	@patch("frappe_whatsapp_core.outbound.get_settings")
	@patch("frappe_whatsapp_core.outbound.assert_conversation_access")
	@patch("frappe_whatsapp_core.permissions.frappe.get_roles", return_value=["WhatsApp User"])
	@patch("frappe_whatsapp_core.outbound.frappe.has_permission")
	@patch("frappe_whatsapp_core.outbound.frappe.db.get_value", return_value="FILE-1")
	@patch("frappe_whatsapp_core.outbound.frappe.get_doc")
	def test_core_media_upload_uses_filename_mime_type(
		self,
		get_doc,
		_get_value,
		_has_permission,
		_get_roles,
		_assert_access,
		get_settings,
		call_management,
	):
		get_doc.side_effect = [
			SimpleNamespace(channel="CHANNEL-1"),
			SimpleNamespace(
				file_name="photo.webp",
				file_url="/private/files/photo.webp",
				get_content=lambda: b"image-bytes",
			),
		]
		settings = MagicMock()
		settings.relay_url = ""
		settings.get_account_name.return_value = "Hub Account"
		get_settings.return_value = settings
		call_management.return_value = {"success": True, "media_id": "MEDIA-1"}

		result = upload_media("CONVERSATION-1", "/private/files/photo.webp")

		self.assertEqual(result["media_id"], "MEDIA-1")
		self.assertEqual(call_management.call_args.args[1]["content_type"], "image/webp")


class TestProviderPresence(FrappeTestCase):
	@patch("frappe_whatsapp_core.hub_client.send_raw")
	@patch("frappe_whatsapp_core.hub_client.get_settings")
	def test_read_and_typing_use_direct_relay_data_plane(self, get_settings, send_raw):
		settings = MagicMock()
		settings.relay_url = "https://relay.example.test"
		get_settings.return_value = settings
		send_raw.return_value = {
			"accepted": True,
			"result": {"success": True, "status": "queued"},
		}

		result = mark_message_read("Channel", "wamid.inbound", typing_indicator=True)

		self.assertTrue(result["success"])
		payload = send_raw.call_args.args[1]
		self.assertEqual(payload["status"], "read")
		self.assertEqual(payload["typing_indicator"], {"type": "text"})
		self.assertTrue(send_raw.call_args.args[2].startswith("typing:wamid.inbound:"))
