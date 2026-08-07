import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from frappe_whatsapp_core.calling import calling_workspace, get_call_permission
from frappe_whatsapp_core.groups import group_workspace, send_group_message
from frappe_whatsapp_core.materializer import (
	get_or_create_channel,
	get_or_create_group_identity,
	materialize_call,
	materialize_group_event,
	materialize_status,
)
from frappe_whatsapp_core.mcp_tools import call_tool


class TestGroupsAndCalling(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")

	@patch("frappe_whatsapp_core.groups._accounts")
	@patch("frappe_whatsapp_core.groups._account", return_value="Hub Account")
	@patch("frappe_whatsapp_core.groups._call")
	def test_group_workspace_and_send_use_durable_core_queue(self, call, account, accounts):
		accounts.return_value = [{
			"account_name": "Hub Account", "display_name": "Primary", "channel": "CHANNEL-1",
		}]
		call.return_value = {"data": [{"id": "GROUP-1"}]}
		workspace = group_workspace()
		with (
			patch("frappe_whatsapp_core.groups.get_or_create_group_identity") as identity,
			patch("frappe_whatsapp_core.groups.get_or_create_conversation") as conversation,
			patch("frappe_whatsapp_core.groups.frappe.get_cached_doc"),
			patch("frappe_whatsapp_core.groups.queue_text_internal") as queue_text,
		):
			identity.return_value = frappe._dict(name="GROUP-IDENTITY")
			conversation.return_value = frappe._dict(name="GROUP-CONVERSATION")
			queue_text.return_value = frappe._dict(name="MSG-1", delivery_status="Queued")
			sent = send_group_message("Hub Account", "GROUP-1", "text", {"body": "Hello"})
		self.assertEqual(workspace["data"][0]["id"], "GROUP-1")
		self.assertTrue(workspace["available"])
		self.assertEqual(sent["conversation"], "GROUP-CONVERSATION")
		self.assertEqual(sent["message"].delivery_status, "Queued")
		queue_text.assert_called_once_with(
			"GROUP-CONVERSATION", "Hello", source="Core Group UI",
		)

	@patch("frappe_whatsapp_core.groups._workspace_failure")
	@patch("frappe_whatsapp_core.groups._accounts", side_effect=frappe.ValidationError("Hub unavailable"))
	def test_group_workspace_returns_empty_state_without_hub(self, accounts, failure):
		failure.return_value = {"available": False, "data": [], "error": "Hub unavailable"}
		result = group_workspace()
		self.assertFalse(result["available"])
		self.assertEqual(result["data"], [])

	@patch("frappe_whatsapp_core.calling._workspace_failure")
	@patch("frappe_whatsapp_core.calling._accounts", side_effect=frappe.ValidationError("Hub unavailable"))
	@patch("frappe_whatsapp_core.calling.frappe.get_all", return_value=[{"call_id": "CALL-LOCAL"}])
	def test_calling_workspace_keeps_local_history_without_hub(self, get_all, accounts, failure):
		failure.return_value = {
			"available": False,
			"calls": [{"call_id": "CALL-LOCAL"}],
			"error": "Hub unavailable",
		}
		result = calling_workspace()
		self.assertFalse(result["available"])
		self.assertEqual(result["calls"][0]["call_id"], "CALL-LOCAL")

	@patch("frappe_whatsapp_core.groups._accounts")
	@patch("frappe_whatsapp_core.groups._account", return_value="Hub Account")
	def test_group_media_upload_is_durable_core_message(self, account, accounts):
		accounts.return_value = [{
			"account_name": "Hub Account", "display_name": "Primary", "channel": "CHANNEL-1",
		}]
		with (
			patch("frappe_whatsapp_core.groups.get_or_create_group_identity") as identity,
			patch("frappe_whatsapp_core.groups.get_or_create_conversation") as conversation,
			patch("frappe_whatsapp_core.groups.frappe.get_cached_doc"),
			patch("frappe_whatsapp_core.groups.upload_media") as upload_media,
			patch("frappe_whatsapp_core.groups.queue_rich") as queue_rich,
		):
			identity.return_value = frappe._dict(name="GROUP-IDENTITY")
			conversation.return_value = frappe._dict(name="GROUP-CONVERSATION")
			upload_media.return_value = {"media_id": "MEDIA-1", "filename": "proof.pdf"}
			queue_rich.return_value = frappe._dict(name="MSG-2", delivery_status="Queued")
			result = send_group_message(
				"Hub Account", "GROUP-1", "document", {"file_url": "/private/files/proof.pdf"},
			)
		self.assertEqual(result["message"].delivery_status, "Queued")
		upload_media.assert_called_once_with("GROUP-CONVERSATION", "/private/files/proof.pdf")
		queue_rich.assert_called_once_with(
			"GROUP-CONVERSATION",
			"document",
			{"id": "MEDIA-1", "filename": "proof.pdf"},
			source="Core Group UI",
		)

	@patch("frappe_whatsapp_core.calling._resolve_account_name", return_value="Hub Account")
	@patch("frappe_whatsapp_core.calling._call", return_value={"data": [{"permission": "granted"}]})
	def test_call_permission_uses_hub(self, call, resolve):
		result = get_call_permission("Hub Account", user_wa_id="919876543210")
		self.assertEqual(result["data"][0]["permission"], "granted")
		self.assertEqual(call.call_args.args[0:2], ("calling", "get_call_permission"))

	def test_group_identity_and_call_are_first_class(self):
		one = get_or_create_group_identity("GROUP-1")
		two = get_or_create_group_identity("GROUP-1")
		self.assertEqual(one.name, two.name)
		self.assertEqual(one.normalized_value, "group:GROUP-1")
		channel = get_or_create_channel("CALL-PHONE", "CALL-WABA")
		event = frappe.get_doc({
			"doctype": "WhatsApp Core Event",
			"event_id": "CALL-EVENT-1",
			"status": "Pending",
			"event_type": "call:connect",
			"direction": "Inbound",
			"payload": json.dumps({"calls": [{"id": "CALL-1"}]}),
		}).insert(ignore_permissions=True)
		created = materialize_call(event, channel, {
			"id": "CALL-1", "event": "connect", "from": "919876543210",
			"timestamp": "1785900000", "session": {"sdp_type": "offer", "sdp": "v=0"},
		})
		self.assertEqual(created["status"], "created")
		self.assertEqual(frappe.db.get_value("WhatsApp Core Call", "CALL-1", "status"), "connect")

	def test_group_webhooks_project_members_and_participant_receipts(self):
		channel = get_or_create_channel("GROUP-PHONE", "GROUP-WABA")
		event = frappe.get_doc({
			"doctype": "WhatsApp Core Event",
			"event_id": "GROUP-EVENT-1",
			"status": "Pending",
			"event_type": "group_participants_update",
			"direction": "Inbound",
			"payload": "{}",
		}).insert(ignore_permissions=True)
		projected = materialize_group_event(event, channel, {
			"group_id": "GROUP-2",
			"type": "group_participants_add",
			"added_participants": [{"wa_id": "919876543210"}],
		})
		self.assertEqual(projected["status"], "created")
		self.assertEqual(
			frappe.db.get_value(
				"WhatsApp Core Group Member",
				{"group": "GROUP-2", "participant_id": "919876543210"},
				"status",
			),
			"Active",
		)
		receipt = materialize_status(channel, {
			"id": "WAMID-GROUP-1",
			"status": "read",
			"recipient_id": "GROUP-2",
			"recipient_type": "group",
			"participant_recipient_id": "919876543210",
			"timestamp": "1785900001",
		}, event=event)
		self.assertEqual(receipt["kind"], "group_receipt")
		self.assertEqual(
			frappe.db.get_value("WhatsApp Core Group Receipt", receipt["name"], "status"),
			"Read",
		)

	def test_call_recording_and_transcript_webhooks_update_one_call(self):
		channel = get_or_create_channel("ARTIFACT-PHONE", "ARTIFACT-WABA")
		event = frappe.get_doc({
			"doctype": "WhatsApp Core Event",
			"event_id": "CALL-ARTIFACT-EVENT-1",
			"status": "Pending",
			"event_type": "calls",
			"direction": "Inbound",
			"payload": "{}",
		}).insert(ignore_permissions=True)
		materialize_call(event, channel, {
			"id": "CALL-ARTIFACT-1",
			"event": "call_recording_available",
			"from_user_id": "BSUID-1",
			"call_recording": {"audio": {
				"id": "MEDIA-AUDIO-1", "mime_type": "audio/ogg; codecs=opus",
				"sha256": "audio-hash", "url": "https://example.test/audio",
			}},
		})
		materialize_call(event, channel, {
			"id": "CALL-ARTIFACT-1",
			"event": "call_transcription_available",
			"call_transcript": {"document": {
				"id": "MEDIA-JSON-1", "mime_type": "application/json",
				"sha256": "json-hash", "url": "https://example.test/transcript",
			}},
		})
		call = frappe.get_doc("WhatsApp Core Call", "CALL-ARTIFACT-1")
		self.assertEqual(call.remote_user_id, "BSUID-1")
		self.assertEqual(call.recording_media_id, "MEDIA-AUDIO-1")
		self.assertEqual(call.transcript_media_id, "MEDIA-JSON-1")

	@patch("frappe_whatsapp_core.mcp_tools.whatsapp_delete_group")
	def test_mcp_destructive_group_action_requires_confirmation(self, delete_group):
		with self.assertRaises(frappe.ValidationError):
			call_tool("whatsapp.delete_group", {
				"account_name": "Hub Account",
				"group_id": "GROUP-1",
				"confirmation": "NO",
			})
		call_tool("whatsapp.delete_group", {
			"account_name": "Hub Account",
			"group_id": "GROUP-1",
			"confirmation": "DELETE",
		})
		delete_group.assert_called_once_with("Hub Account", "GROUP-1")

	@patch("frappe_whatsapp_core.outbound.queue_rich")
	def test_mcp_rich_reply_uses_core_queue(self, queue_rich):
		queue_rich.return_value = {"name": "MSG-1", "delivery_status": "Queued"}
		result = call_tool("whatsapp.send_rich_message", {
			"conversation": "CONV-1",
			"message_type": "sticker",
			"payload": {"id": "MEDIA-1"},
		})
		self.assertEqual(result["delivery_status"], "Queued")
		queue_rich.assert_called_once_with(
			"CONV-1", "sticker", {"id": "MEDIA-1"}, "", source="External AI",
		)

	@patch("frappe_whatsapp_core.mcp_tools.whatsapp_send_call_button")
	def test_mcp_call_button_exposes_calling_surface(self, send_call_button):
		send_call_button.return_value = {"success": True}
		result = call_tool("whatsapp.send_call_button", {
			"account_name": "Hub Account",
			"body_text": "Call us",
			"to_number": "+919876543210",
		})
		self.assertTrue(result["success"])
		send_call_button.assert_called_once_with(
			account_name="Hub Account",
			body_text="Call us",
			to_number="+919876543210",
		)
