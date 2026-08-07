import base64
import json
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import now_datetime

from frappe_whatsapp_core.mcp_tools import TOOL_DEFINITIONS
from frappe_whatsapp_core.workspace_api import (
	_outbound_handler,
	get_conversation,
	list_conversations,
	list_messages,
	send_text,
	upsert_team,
)
from frappe_whatsapp_core.message_media import download_message_media


class TestCoreRoleBoundary(FrappeTestCase):
	def test_user_bootstrap_exposes_inbox_only(self):
		from frappe_whatsapp_core import frontend_api

		with patch.object(frontend_api.frappe, "get_roles", return_value=["WhatsApp User"]):
			boot = frontend_api.bootstrap()
		self.assertFalse(boot["can_manage"])
		self.assertEqual(boot["default_module"], "inbox")
		self.assertEqual(boot["modules"], ["inbox"])

	def test_manager_bootstrap_exposes_management_modules(self):
		from frappe_whatsapp_core import frontend_api

		with patch.object(frontend_api.frappe, "get_roles", return_value=["WhatsApp Manager"]):
			boot = frontend_api.bootstrap()
		self.assertTrue(boot["can_manage"])
		self.assertEqual(boot["default_module"], "dashboard")
		self.assertIn("campaigns", boot["modules"])
		self.assertIn("flows", boot["modules"])
		self.assertIn("ai-queue", boot["modules"])

	def test_user_cannot_enter_management_api(self):
		from frappe_whatsapp_core import permissions
		from frappe_whatsapp_core.frontend_api import dashboard

		with patch.object(permissions.frappe, "get_roles", return_value=["WhatsApp User"]):
			with self.assertRaises(frappe.PermissionError):
				dashboard()


class TestWorkspaceAPI(FrappeTestCase):
	def setUp(self):
		super().setUp()
		suffix = frappe.generate_hash(length=8).lower()
		self.channel = frappe.get_doc({
			"doctype": "WhatsApp Core Channel",
			"channel_key": f"meta:workspace-{suffix}",
			"display_name": "Workspace Test",
			"provider": "meta",
			"phone_number_id": f"workspace-{suffix}",
			"enabled": 1,
		}).insert(ignore_permissions=True)
		self.identity = frappe.get_doc({
			"doctype": "WhatsApp Core Identity",
			"identity_key": f"workspace-identity-{suffix}",
			"identity_type": "WhatsApp",
			"normalized_value": f"9198{suffix}",
			"display_value": f"Workspace User {suffix}",
			"provider": "meta",
			"status": "Active",
			"attributes": json.dumps({"source": "test"}),
		}).insert(ignore_permissions=True)
		now = now_datetime()
		self.conversation = frappe.get_doc({
			"doctype": "WhatsApp Core Conversation",
			"conversation_key": f"{self.channel.name}:{self.identity.name}",
			"channel": self.channel.name,
			"remote_identity": self.identity.name,
			"status": "Open",
			"last_inbound_at": now,
			"last_message_at": now,
		}).insert(ignore_permissions=True)
		self.messages = []
		for index in range(2):
			timestamp = now
			self.messages.append(
				frappe.get_doc({
					"doctype": "WhatsApp Core Message",
					"message_key": f"workspace-message-{suffix}-{index}",
					"conversation": self.conversation.name,
					"channel": self.channel.name,
					"provider_message_id": f"wamid.workspace.{suffix}.{index}",
					"direction": "Inbound",
					"message_type": "text",
					"body": f"Message {index}",
					"content": json.dumps({"text": {"body": f"Message {index}"}}),
					"provider_timestamp": timestamp,
					"delivery_status": "Received",
				}).insert(ignore_permissions=True)
			)
		self.conversation.last_message_at = self.messages[-1].provider_timestamp
		self.conversation.save(ignore_permissions=True)

	def test_conversation_and_message_pagination_contract(self):
		result = list_conversations(search=self.identity.display_value, limit=10)
		self.assertTrue(
			any(row.name == self.conversation.name for row in result["rows"])
		)
		detail = get_conversation(self.conversation.name)
		self.assertEqual(detail["identity"]["name"], self.identity.name)

		page = list_messages(self.conversation.name, limit=1)
		self.assertEqual(len(page["rows"]), 1)
		self.assertTrue(page["has_more"])
		self.assertEqual(page["rows"][0].body, "Message 1")
		older = list_messages(
			self.conversation.name,
			before=page["next_before"],
			before_creation=page["next_before_creation"],
			limit=1,
		)
		self.assertEqual(older["rows"][0].body, "Message 0")

		from frappe_whatsapp_core.inbox import conversation

		inbox_page = conversation(self.conversation.name, message_limit=1)
		self.assertEqual(inbox_page["messages"][0].body, "Message 1")
		self.assertTrue(inbox_page["message_page"]["has_more"])

	def test_inbound_media_is_exposed_through_authenticated_core_url(self):
		media = frappe.get_doc({
			"doctype": "WhatsApp Core Message",
			"message_key": f"workspace-media-{frappe.generate_hash(length=8)}",
			"conversation": self.conversation.name,
			"channel": self.channel.name,
			"provider_message_id": f"wamid.media.{frappe.generate_hash(length=8)}",
			"direction": "Inbound",
			"message_type": "image",
			"body": "Photo",
			"content": json.dumps({"type": "image", "image": {"id": "MEDIA-1"}}),
			"provider_timestamp": now_datetime(),
			"delivery_status": "Received",
		}).insert(ignore_permissions=True)

		page = list_messages(self.conversation.name, limit=20)
		row = next(item for item in page["rows"] if item.name == media.name)
		self.assertIn("message_media.download_message_media", row.media_url)
		self.assertIn(media.name, row.media_url)

	@patch("frappe_whatsapp_core.message_media.save_file")
	@patch("frappe_whatsapp_core.message_media.call_management")
	@patch("frappe_whatsapp_core.message_media.get_settings")
	def test_message_media_download_uses_channel_mapping_and_private_cache(
		self, get_settings, call_management, save_file
	):
		media = frappe.get_doc({
			"doctype": "WhatsApp Core Message",
			"message_key": f"workspace-download-{frappe.generate_hash(length=8)}",
			"conversation": self.conversation.name,
			"channel": self.channel.name,
			"provider_message_id": f"wamid.download.{frappe.generate_hash(length=8)}",
			"direction": "Inbound",
			"message_type": "document",
			"body": "Invoice",
			"content": json.dumps({
				"type": "document",
				"document": {"id": "MEDIA-DOC", "filename": "invoice.pdf"},
			}),
			"provider_timestamp": now_datetime(),
			"delivery_status": "Received",
		}).insert(ignore_permissions=True)
		settings = SimpleNamespace(get_account_name=lambda channel: "ACCOUNT-1")
		get_settings.return_value = settings
		call_management.return_value = {
			"success": True,
			"content_b64": base64.b64encode(b"pdf-content").decode(),
			"mime_type": "application/pdf",
		}
		save_file.return_value = SimpleNamespace(
			file_name="invoice.pdf", content_type="application/pdf"
		)

		download_message_media(media.name)

		self.assertEqual(call_management.call_args.args[1]["account_name"], "ACCOUNT-1")
		self.assertEqual(call_management.call_args.args[1]["media_id"], "MEDIA-DOC")
		self.assertEqual(frappe.local.response.filecontent, b"pdf-content")
		self.assertEqual(frappe.local.response.display_content_as, "attachment")
		save_file.assert_called_once()
		self.assertEqual(save_file.call_args.kwargs["is_private"], 1)

	def test_team_and_outbound_hook_contracts(self):
		team = upsert_team(
			team_name=f"Workspace Team {frappe.generate_hash(length=6)}",
			members=[{"user": "Administrator", "team_role": "Manager"}],
		)
		self.assertEqual(team["members"][0]["user"], "Administrator")

		with patch(
			"frappe_whatsapp_core.workspace_api._outbound_handler"
		) as outbound_handler:
			sender = outbound_handler.return_value
			sender.return_value = {"name": "queued-message"}
			result = send_text(self.conversation.name, "Hello")
			self.assertEqual(result["name"], "queued-message")
			sender.assert_called_once_with(self.conversation.name, "Hello")

	def test_outbound_handler_uses_core_defaults_without_adapter_hooks(self):
		from frappe_whatsapp_core.outbound import queue_template, queue_text

		with patch(
			"frappe_whatsapp_core.workspace_api.frappe.get_hooks",
			return_value=[],
		):
			self.assertIs(
				_outbound_handler("whatsapp_core_outbound_text_sender"),
				queue_text,
			)
			self.assertIs(
				_outbound_handler("whatsapp_core_outbound_template_sender"),
				queue_template,
			)

	def test_outbound_handler_rejects_ambiguous_adapter_hooks(self):
		with patch(
			"frappe_whatsapp_core.workspace_api.frappe.get_hooks",
			return_value=["adapter.one", "adapter.two"],
		):
			with self.assertRaises(frappe.ValidationError):
				_outbound_handler("whatsapp_core_outbound_text_sender")

	def test_mcp_manifest_covers_operator_and_management_surfaces(self):
		all_names = [tool["name"] for tool in TOOL_DEFINITIONS]
		names = set(all_names)
		self.assertEqual(len(all_names), len(names))
		self.assertTrue({
			"whatsapp.list_conversations",
			"whatsapp.list_messages",
			"whatsapp.send_text",
			"whatsapp.send_rich_message",
			"whatsapp.send_template",
			"whatsapp.mark_conversation_read",
			"whatsapp.show_typing",
			"whatsapp.toggle_message_bookmark",
			"whatsapp.list_teams",
			"whatsapp.upsert_team",
			"whatsapp.list_campaigns",
			"whatsapp.prepare_campaign",
			"whatsapp.authorize_campaign",
			"whatsapp.revoke_campaign_authorization",
			"whatsapp.schedule_campaign",
			"whatsapp.cancel_campaign",
			"whatsapp.list_flows",
			"whatsapp.update_flow",
			"whatsapp.deprecate_flow",
			"whatsapp.delete_flow",
			"whatsapp.migrate_flows",
			"whatsapp.get_flow_public_key",
			"whatsapp.set_flow_public_key",
			"whatsapp.create_group",
			"whatsapp.update_group",
			"whatsapp.update_group_picture",
			"whatsapp.delete_group",
			"whatsapp.list_group_join_requests",
			"whatsapp.decide_group_join_requests",
			"whatsapp.remove_group_participants",
			"whatsapp.pin_group_message",
			"whatsapp.get_call_settings",
			"whatsapp.update_call_settings",
			"whatsapp.call_action",
		}.issubset(names))
