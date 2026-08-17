import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from frappe_whatsapp_core.calling import (
	calling_workspace,
	get_call_permission,
	send_call_button,
	update_call_settings,
)
from frappe_whatsapp_core.groups import (
	_sync_group_summaries,
	group_activity,
	group_workspace,
	pin_group_message,
	send_group_invite_template,
	send_group_message,
)
from frappe_whatsapp_core.identity import get_or_create_identity
from frappe_whatsapp_core.materializer import (
	get_or_create_channel,
	get_or_create_group_identity,
	materialize_call,
	materialize_group_event,
	materialize_status,
)
from frappe_whatsapp_core.mcp_tools import call_tool
from frappe_whatsapp_core.naming import name_by_key


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
		self.assertIn("contacts", workspace)
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
	@patch("frappe_whatsapp_core.calling.contact_options", return_value=[{"identity": "CONTACT-1"}])
	def test_calling_workspace_keeps_local_history_without_hub(
		self, contacts, get_all, accounts, failure
	):
		failure.return_value = {
			"available": False,
			"calls": [{"call_id": "CALL-LOCAL"}],
			"contacts": [{"identity": "CONTACT-1"}],
			"error": "Hub unavailable",
		}
		result = calling_workspace()
		self.assertFalse(result["available"])
		self.assertEqual(result["calls"][0]["call_id"], "CALL-LOCAL")
		self.assertEqual(result["contacts"][0]["identity"], "CONTACT-1")

	@patch("frappe_whatsapp_core.calling._resolve_account_name", return_value="Hub Account")
	@patch("frappe_whatsapp_core.calling._call", return_value={"success": True})
	def test_calling_settings_normalize_meta_visibility(self, hub_call, resolve):
		result = update_call_settings(
			"Hub Account",
			{"status": "enabled", "call_icon_visibility": "disable_all"},
		)
		self.assertTrue(result["success"])
		hub_call.assert_called_once_with("calling", "update_call_settings", {
			"account_name": "Hub Account",
			"calling": {"status": "ENABLED", "call_icon_visibility": "DISABLE_ALL"},
		})

	@patch("frappe_whatsapp_core.calling._resolve_account_name", return_value="Hub Account")
	@patch("frappe_whatsapp_core.calling._call", return_value={"success": True})
	def test_calling_settings_omit_meta_not_set_sentinel(self, hub_call, resolve):
		update_call_settings(
			"Hub Account",
			'{"status":"DISABLED","call_icon_visibility":"NOT_SET"}',
		)
		self.assertNotIn(
			"call_icon_visibility", hub_call.call_args.args[2]["calling"]
		)

	@patch("frappe_whatsapp_core.calling._resolve_account_name", return_value="Hub Account")
	def test_calling_settings_reject_unknown_meta_visibility(self, resolve):
		with self.assertRaises(frappe.ValidationError):
			update_call_settings(
				"Hub Account",
				{"status": "ENABLED", "call_icon_visibility": "SHOW_SOMETIMES"},
			)

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
			upload_media.return_value = {
				"media_id": "MEDIA-1",
				"filename": "proof.pdf",
				"file_url": "/private/files/proof.pdf",
			}
			queue_rich.return_value = frappe._dict(name="MSG-2", delivery_status="Queued")
			result = send_group_message(
				"Hub Account", "GROUP-1", "document", {"file_url": "/private/files/proof.pdf"},
			)
		self.assertEqual(result["message"].delivery_status, "Queued")
		upload_media.assert_called_once_with(
			"GROUP-CONVERSATION", "/private/files/proof.pdf", "document",
		)
		queue_rich.assert_called_once_with(
			"GROUP-CONVERSATION",
			"document",
			{"id": "MEDIA-1", "filename": "proof.pdf"},
			source="Core Group UI",
			local_file_url="/private/files/proof.pdf",
		)

	@patch("frappe_whatsapp_core.groups._accounts")
	@patch("frappe_whatsapp_core.groups._account", return_value="Hub Account")
	def test_group_invite_uses_selected_core_contact(self, account, accounts):
		identity = get_or_create_identity("919876543219", resolve=False)
		accounts.return_value = [{
			"account_name": "Hub Account", "display_name": "Primary", "channel": "CHANNEL-1",
		}]
		with (
			patch("frappe_whatsapp_core.groups.get_or_create_conversation") as conversation,
			patch("frappe_whatsapp_core.groups.frappe.get_cached_doc"),
			patch("frappe_whatsapp_core.groups.queue_template_internal") as queue_template,
		):
			conversation.return_value = frappe._dict(name="GROUP-INVITE-CONVERSATION")
			queue_template.return_value = frappe._dict(name="MSG-INVITE")
			result = send_group_invite_template(
				"Hub Account",
				"GROUP-1",
				"group_invite",
				identity=identity.name,
			)
		self.assertEqual(result["conversation"], "GROUP-INVITE-CONVERSATION")
		queue_template.assert_called_once()

	@patch("frappe_whatsapp_core.groups._account", return_value="Hub Account")
	@patch("frappe_whatsapp_core.groups.send_account_raw", return_value={"success": True})
	def test_group_bsuid_invite_and_pin_use_direct_relay(self, relay_send, account):
		send_group_invite_template(
			"Hub Account", "GROUP-1", "group_invite",
			recipient="US.Customer1", idempotency_key="invite-1",
		)
		invite = relay_send.call_args_list[0]
		self.assertEqual(invite.args[1]["recipient"], "US.Customer1")
		self.assertEqual(invite.args[2], "invite-1")

		pin_group_message("Hub Account", "GROUP-1", "wamid.1", "pin", 7)
		pin = relay_send.call_args_list[1]
		self.assertEqual(pin.args[1]["type"], "pin")
		self.assertEqual(pin.args[1]["pin"]["expiration_days"], 7)

	@patch("frappe_whatsapp_core.calling._resolve_account_name", return_value="Hub Account")
	@patch("frappe_whatsapp_core.calling.relay_get_call_permission", return_value={"data": [{"permission": "granted"}]})
	def test_call_permission_uses_relay(self, relay_permission, resolve):
		result = get_call_permission("Hub Account", user_wa_id="919876543210")
		self.assertEqual(result["data"][0]["permission"], "granted")
		relay_permission.assert_called_once_with(
			"Hub Account", user_wa_id="919876543210", recipient=None,
		)

	@patch("frappe_whatsapp_core.calling.resolve_recipient_phone", return_value="919876543219")
	@patch("frappe_whatsapp_core.calling._resolve_account_name", return_value="Hub Account")
	@patch("frappe_whatsapp_core.calling.relay_get_call_permission", return_value={"data": []})
	def test_call_permission_resolves_selected_core_contact(self, relay_permission, resolve, phone):
		get_call_permission("Hub Account", identity="CONTACT-1")
		phone.assert_called_once_with(
			"CONTACT-1", context={"operation": "get_call_permission"}
		)
		relay_permission.assert_called_once_with(
			"Hub Account", user_wa_id="919876543219", recipient=None,
		)

	@patch("frappe_whatsapp_core.calling.resolve_recipient_phone", return_value="919876543219")
	@patch("frappe_whatsapp_core.calling._resolve_account_name", return_value="Hub Account")
	@patch("frappe_whatsapp_core.calling.send_account_raw", return_value={"success": True})
	def test_call_invitation_resolves_selected_core_contact(self, relay_send, resolve, phone):
		send_call_button("Hub Account", "Call us", identity="CONTACT-1")
		payload = relay_send.call_args.args[1]
		self.assertEqual(payload["to"], "919876543219")
		self.assertNotIn("recipient", payload)
		self.assertEqual(payload["interactive"]["type"], "voice_call")

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
		self.assertEqual(
			frappe.db.get_value("WhatsApp Core Call", created["name"], "status"),
			"connect",
		)

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
		group_name = projected["name"]
		self.assertEqual(
			frappe.db.get_value(
				"WhatsApp Core Group Member",
				{"group": group_name, "participant_id": "919876543210"},
				"status",
			),
			"Active",
		)
		bsuid = "US.GroupReceipt1"
		receipt = materialize_status(channel, {
			"id": "WAMID-GROUP-1",
			"status": "read",
			"recipient_id": "GROUP-2",
			"recipient_type": "group",
			"recipient_participant_user_id": bsuid,
			"recipient_participant_parent_user_id": "US.ENT.GroupReceiptParent1",
			"timestamp": "1785900001",
		}, event=event, contact={
			"user_id": bsuid,
			"parent_user_id": "US.ENT.GroupReceiptParent1",
			"profile": {"username": "group_reader"},
		})
		self.assertEqual(receipt["kind"], "group_receipt")
		self.assertEqual(
			frappe.db.get_value("WhatsApp Core Group Receipt", receipt["name"], "status"),
			"Read",
		)
		self.assertEqual(
			frappe.db.get_value("WhatsApp Core Group Receipt", receipt["name"], "participant_id"),
			bsuid,
		)

	def test_group_subject_labels_inbox_and_activity_exposes_provider_messages(self):
		channel = get_or_create_channel("GROUP-SUBJECT-PHONE", "GROUP-SUBJECT-WABA")
		event = frappe.get_doc({
			"doctype": "WhatsApp Core Event",
			"event_id": "GROUP-SUBJECT-EVENT-1",
			"status": "Pending",
			"event_type": "group_create",
			"direction": "Inbound",
			"payload": "{}",
		}).insert(ignore_permissions=True)
		materialize_group_event(event, channel, {
			"group_id": "GROUP-SUBJECT-1",
			"type": "group_create",
			"subject": "Retail Support Team",
			"description": "Retailer group",
		})
		identity = get_or_create_group_identity("GROUP-SUBJECT-1")
		self.assertEqual(identity.display_value, "Retail Support Team")
		conversation = frappe.get_doc({
			"doctype": "WhatsApp Core Conversation",
			"conversation_key": "GROUP-SUBJECT-CONVERSATION-1",
			"channel": channel.name,
			"remote_identity": identity.name,
			"status": "Open",
			"last_message_at": frappe.utils.now_datetime(),
		}).insert(ignore_permissions=True)
		frappe.get_doc({
			"doctype": "WhatsApp Core Message",
			"message_key": "GROUP-SUBJECT-MESSAGE-1",
			"idempotency_key": "GROUP-SUBJECT-IDEMPOTENCY-1",
			"conversation": conversation.name,
			"channel": channel.name,
			"provider_message_id": "wamid.group.subject.1",
			"direction": "Outbound",
			"message_type": "text",
			"body": "Group update",
			"content": {"body": "Group update"},
			"provider_timestamp": frappe.utils.now_datetime(),
			"delivery_status": "Delivered",
		}).insert(ignore_permissions=True)
		frappe.get_doc({
			"doctype": "WhatsApp Core Message",
			"message_key": "GROUP-SUBJECT-MESSAGE-LOCAL",
			"idempotency_key": "GROUP-SUBJECT-IDEMPOTENCY-LOCAL",
			"conversation": conversation.name,
			"channel": channel.name,
			"provider_message_id": "local:11111111-1111-4111-8111-111111111111",
			"direction": "Outbound",
			"message_type": "text",
			"body": "Queued group update",
			"content": {"body": "Queued group update"},
			"provider_timestamp": frappe.utils.add_to_date(
				frappe.utils.now_datetime(), seconds=1
			),
			"delivery_status": "Queued",
		}).insert(ignore_permissions=True)
		activity = group_activity("GROUP-SUBJECT-1")
		self.assertEqual(activity["conversation"], conversation.name)
		self.assertEqual(activity["messages"][0]["delivery_status"], "Queued")
		self.assertEqual(activity["messages"][1]["provider_message_id"], "wamid.group.subject.1")

	def test_group_list_sync_labels_preexisting_groups_before_webhook(self):
		channel = get_or_create_channel("GROUP-LIST-PHONE", "GROUP-LIST-WABA")
		_sync_group_summaries(
			"Hub Account",
			[{
				"id": "GROUP-LIST-1",
				"subject": "Distributor Updates",
				"description": "Announcements",
				"status": "ACTIVE",
				"total_participant_count": 24,
			}],
			[{"account_name": "Hub Account", "channel": channel.name}],
		)
		group = frappe.get_doc(
			"WhatsApp Core Group",
			name_by_key("WhatsApp Core Group", "GROUP-LIST-1"),
		)
		identity = get_or_create_group_identity(group.group_id)
		self.assertEqual(group.participant_count, 24)
		self.assertEqual(identity.display_value, "Distributor Updates")

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
			"from_user_id": "US.CallArtifact1",
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
		call = frappe.get_doc(
			"WhatsApp Core Call",
			name_by_key("WhatsApp Core Call", "CALL-ARTIFACT-1"),
		)
		self.assertEqual(call.remote_user_id, "US.CallArtifact1")
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
