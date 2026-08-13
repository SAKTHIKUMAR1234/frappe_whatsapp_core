import base64
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import now_datetime

from frappe_whatsapp_core.conversation_reads import mark_messages_read
from frappe_whatsapp_core.mcp_tools import TOOL_DEFINITIONS, manifest
from frappe_whatsapp_core.message_media import (
	cache_message_media_batch,
	download_message_media,
	enqueue_message_media_cache,
)
from frappe_whatsapp_core.workspace_api import (
	_outbound_handler,
	add_team_member,
	get_conversation,
	list_conversations,
	list_messages,
	remove_team_member,
	send_text,
	team_member_page,
	team_workspace,
	upsert_team,
)


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
		self.assertNotIn("automation-flows", boot["modules"])
		self.assertIn("ai-queue", boot["modules"])

	def test_flow_user_has_mcp_authoring_without_a_duplicate_visual_builder(self):
		from frappe_whatsapp_core import frontend_api

		with patch.object(frontend_api.frappe, "get_roles", return_value=["WhatsApp Flow User"]):
			boot = frontend_api.bootstrap()
		self.assertTrue(boot["authorized"])
		self.assertTrue(boot["can_build_flows"])
		self.assertFalse(boot["can_manage"])
		self.assertEqual(boot["default_module"], "access-denied")
		self.assertEqual(boot["modules"], [])

	def test_flow_user_mcp_manifest_stops_at_approval(self):
		from frappe_whatsapp_core import mcp_tools

		with patch.object(mcp_tools.frappe, "get_roles", return_value=["WhatsApp Flow User"]):
			tool_names = {tool["name"] for tool in manifest()["tools"]}
		self.assertIn("whatsapp.create_automation_flow", tool_names)
		self.assertIn("whatsapp.request_automation_flow_approval", tool_names)
		self.assertNotIn("whatsapp.publish_automation_flow", tool_names)
		self.assertNotIn("whatsapp.send_text", tool_names)

	def test_authenticated_user_without_core_role_gets_no_modules(self):
		from frappe_whatsapp_core import frontend_api

		with patch.object(frontend_api.frappe, "get_roles", return_value=["Desk User"]):
			boot = frontend_api.bootstrap()
		self.assertTrue(boot["authenticated"])
		self.assertFalse(boot["authorized"])
		self.assertEqual(boot["default_module"], "access-denied")
		self.assertEqual(boot["modules"], [])

	def test_user_cannot_enter_management_api(self):
		from frappe_whatsapp_core import permissions
		from frappe_whatsapp_core.frontend_api import dashboard

		with patch.object(permissions.frappe, "get_roles", return_value=["WhatsApp User"]):
			with self.assertRaises(frappe.PermissionError):
				dashboard()

	def test_manager_onboarding_status_is_secret_free(self):
		from frappe_whatsapp_core import frontend_api

		settings = SimpleNamespace(
			accounts=[SimpleNamespace(channel="Core Channel", account_name="Hub Account", is_default=1)]
		)
		transport = {
			"enabled": True,
			"outbound_enabled": True,
			"hub_url": "https://hub.example.test",
			"relay_url": "https://relay.example.test",
			"credentials_configured": True,
		}
		with (
			patch.object(frontend_api.frappe, "get_roles", return_value=["WhatsApp Manager"]),
			patch.object(frontend_api.frappe, "get_single", return_value=settings),
			patch.object(frontend_api, "connection_status", return_value=transport),
			patch.object(frontend_api.frappe.local, "site", "core.example.test"),
		):
			result = frontend_api.onboarding_status()
		self.assertEqual(result["site"], "core.example.test")
		self.assertEqual(result["transport"], transport)
		self.assertEqual(result["accounts"][0]["account_name"], "Hub Account")
		self.assertNotIn("secret", frappe.as_json(result).lower())

	def test_user_has_no_management_doctype_permissions(self):
		for doctype in (
			"WhatsApp Core Group",
			"WhatsApp Core Group Member",
			"WhatsApp Core Group Receipt",
			"WhatsApp Core Flow Response",
		):
			roles = {row.role for row in frappe.get_meta(doctype).permissions}
			self.assertNotIn("WhatsApp User", roles, doctype)


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
		# Provider callbacks can share both timestamp fields. The message name is
		# the final stable keyset component and must prevent gaps between pages.
		shared_creation = self.messages[0].creation
		frappe.db.set_value(
			"WhatsApp Core Message",
			self.messages[1].name,
			"creation",
			shared_creation,
			update_modified=False,
		)
		self.messages[1].creation = shared_creation
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
			before_name=page["next_before_name"],
			limit=1,
		)
		self.assertEqual(older["rows"][0].body, "Message 0")

		from frappe_whatsapp_core.inbox import conversation

		inbox_page = conversation(self.conversation.name, message_limit=1)
		self.assertEqual(inbox_page["messages"][0].body, "Message 0")
		self.assertEqual(inbox_page["resume_message"], self.messages[0].name)
		self.assertFalse(inbox_page["message_page"]["has_more"])
		self.assertTrue(inbox_page["message_page"]["has_more_newer"])

	@patch(
		"frappe_whatsapp_core.conversation_reads._latest_inbound_provider_message",
		return_value=None,
	)
	def test_exact_message_reads_are_idempotent_and_drive_unread_count(self, _latest):
		first = mark_messages_read(
			self.conversation.name,
			[message.name for message in self.messages],
		)
		second = mark_messages_read(
			self.conversation.name,
			[message.name for message in self.messages],
		)

		self.assertEqual(first["processed"], 2)
		self.assertEqual(first["recorded"], 2)
		self.assertEqual(second["recorded"], 0)
		page = list_messages(self.conversation.name, limit=20)
		for message in page["rows"]:
			self.assertIn(
				frappe.session.user,
				[reader["user"] for reader in message.read_by],
			)
		conversation_row = next(
			row
			for row in list_conversations(search=self.identity.display_value, limit=10)["rows"]
			if row.name == self.conversation.name
		)
		self.assertEqual(conversation_row.unread_count, 0)

	def test_inbound_reactions_do_not_inflate_unread_count(self):
		frappe.get_doc({
			"doctype": "WhatsApp Core Message",
			"message_key": f"reaction-{frappe.generate_hash(length=8)}",
			"conversation": self.conversation.name,
			"channel": self.channel.name,
			"provider_message_id": f"wamid.reaction.{frappe.generate_hash(length=8)}",
			"direction": "Inbound",
			"message_type": "reaction",
			"body": "👍",
			"content": json.dumps({
				"reaction": {
					"message_id": self.messages[0].provider_message_id,
					"emoji": "👍",
				},
			}),
			"provider_timestamp": now_datetime(),
			"delivery_status": "Received",
		}).insert(ignore_permissions=True)

		conversation_row = next(
			row
			for row in list_conversations(search=self.identity.display_value, limit=10)["rows"]
			if row.name == self.conversation.name
		)
		self.assertEqual(conversation_row.unread_count, 2)

	def test_reply_includes_original_message_preview_outside_page(self):
		reply = frappe.get_doc({
			"doctype": "WhatsApp Core Message",
			"message_key": f"workspace-reply-{frappe.generate_hash(length=8)}",
			"conversation": self.conversation.name,
			"channel": self.channel.name,
			"provider_message_id": f"wamid.reply.{frappe.generate_hash(length=8)}",
			"direction": "Outbound",
			"message_type": "text",
			"body": "Reply body",
			"content": json.dumps({"context_message_id": self.messages[0].provider_message_id}),
			"provider_timestamp": now_datetime(),
			"delivery_status": "Sent",
		}).insert(ignore_permissions=True)

		page = list_messages(self.conversation.name, limit=1)
		self.assertEqual(page["rows"][0].name, reply.name)
		self.assertEqual(page["rows"][0].quoted_message["name"], self.messages[0].name)
		self.assertEqual(page["rows"][0].quoted_message["body"], "Message 0")
		self.assertNotIn("provider_message_id", page["rows"][0].quoted_message)

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
			file_name="invoice.pdf",
			content_type="application/pdf",
			get=lambda key: "application/pdf" if key == "content_type" else None,
			get_content=lambda: b"pdf-content",
		)

		download_message_media(media.name)

		self.assertEqual(call_management.call_args.args[1]["account_name"], "ACCOUNT-1")
		self.assertEqual(call_management.call_args.args[1]["media_id"], "MEDIA-DOC")
		self.assertEqual(frappe.local.response.filecontent, b"pdf-content")
		self.assertEqual(frappe.local.response.display_content_as, "attachment")
		save_file.assert_called_once()
		self.assertEqual(save_file.call_args.kwargs["is_private"], 1)

	@patch("frappe_whatsapp_core.message_media._cached_file")
	def test_image_media_can_be_forced_to_download(self, cached_file):
		media = frappe.get_doc({
			"doctype": "WhatsApp Core Message",
			"message_key": f"workspace-image-download-{frappe.generate_hash(length=8)}",
			"conversation": self.conversation.name,
			"channel": self.channel.name,
			"provider_message_id": f"wamid.image.{frappe.generate_hash(length=8)}",
			"direction": "Inbound",
			"message_type": "image",
			"body": "Photo",
			"content": json.dumps({"image": {"id": "MEDIA-IMAGE"}}),
			"provider_timestamp": now_datetime(),
			"delivery_status": "Received",
		}).insert(ignore_permissions=True)
		cached_file.return_value = SimpleNamespace(
			file_name="photo.png",
			content_type="image/png",
			get=lambda key: "image/png" if key == "content_type" else None,
			get_content=lambda: b"image-content",
		)

		download_message_media(media.name, download=1)

		self.assertEqual(frappe.local.response.display_content_as, "attachment")
		self.assertEqual(frappe.local.response.content_type, "image/png")

	@patch("frappe_whatsapp_core.message_media.frappe.enqueue")
	def test_new_media_cache_jobs_are_bounded_and_after_commit(self, enqueue):
		enqueue_message_media_cache(
			[f"message-{index}" for index in range(205)],
			enqueue_after_commit=True,
		)
		self.assertEqual(enqueue.call_count, 3)
		self.assertEqual(
			[len(call.kwargs["message_names"]) for call in enqueue.call_args_list],
			[100, 100, 5],
		)
		self.assertTrue(all(call.kwargs["enqueue_after_commit"] for call in enqueue.call_args_list))

	@patch("frappe_whatsapp_core.message_media.frappe.log_error")
	@patch("frappe_whatsapp_core.message_media.cache_message_media")
	def test_media_cache_batch_keeps_other_files_when_one_fails(self, cache, log_error):
		cache.side_effect = [SimpleNamespace(name="FILE-1"), RuntimeError("expired")]
		result = cache_message_media_batch(["MESSAGE-1", "MESSAGE-2"])
		self.assertEqual(result["stored"], [{"message": "MESSAGE-1", "file": "FILE-1"}])
		self.assertEqual(result["failed"], ["MESSAGE-2"])
		log_error.assert_called_once()

	@patch("frappe_whatsapp_core.outbound._queue_message")
	@patch("frappe_whatsapp_core.outbound._local_media_file")
	def test_outbound_media_file_is_attached_to_optimistic_message(self, local_file, queue):
		from frappe_whatsapp_core.outbound import queue_rich

		file_doc = MagicMock()
		file_doc.file_url = "/private/files/proof.jpg"
		local_file.return_value = file_doc
		queue.return_value = SimpleNamespace(name="MESSAGE-OUT")

		message = queue_rich(
			self.conversation.name,
			"image",
			{"id": "META-MEDIA-1"},
			local_file_url=file_doc.file_url,
		)

		self.assertEqual(message.name, "MESSAGE-OUT")
		self.assertEqual(queue.call_args.args[3]["payload"]["local_file_url"], file_doc.file_url)
		self.assertEqual(file_doc.attached_to_doctype, "WhatsApp Core Message")
		self.assertEqual(file_doc.attached_to_name, "MESSAGE-OUT")
		file_doc.save.assert_called_once_with(ignore_permissions=True)

	def test_local_media_reference_is_never_sent_to_meta(self):
		from frappe_whatsapp_core.outbound import _message_payload

		message = SimpleNamespace(
			message_type="image",
			body="Proof",
			content=json.dumps({
				"payload": {
					"id": "META-MEDIA-1",
					"local_file_url": "/private/files/proof.jpg",
				}
			}),
		)
		payload = _message_payload(message, "919999999999")
		self.assertEqual(payload["image"], {"id": "META-MEDIA-1"})

	def test_team_and_outbound_hook_contracts(self):
		team = upsert_team(
			team_name=f"Workspace Team {frappe.generate_hash(length=6)}",
			icon="building-2",
			members=[{"user": "Administrator", "team_role": "Manager"}],
		)
		self.assertEqual(team["members"][0]["user"], "Administrator")
		self.assertEqual(team["icon"], "building-2")
		workspace = team_workspace()
		self.assertTrue(any(row["name"] == team["name"] for row in workspace["teams"]))
		self.assertEqual(workspace["users"], [])
		self.assertEqual(workspace["contacts"], [])
		page = team_member_page(team["name"], limit=1)
		self.assertEqual(page["rows"][0]["user"], "Administrator")
		upsert_team(team_name=team["name"], description="Metadata-only edit")
		self.assertEqual(team_member_page(team["name"])["rows"][0]["user"], "Administrator")
		remove_team_member(team["name"], "Administrator")
		self.assertEqual(team_member_page(team["name"])["rows"], [])
		add_team_member(team["name"], "Administrator", "Manager")
		self.assertEqual(team_member_page(team["name"])["rows"][0]["team_role"], "Manager")

		with patch(
			"frappe_whatsapp_core.workspace_api._outbound_handler"
		) as outbound_handler:
			sender = outbound_handler.return_value
			sender.return_value = {"name": "queued-message"}
			result = send_text(self.conversation.name, "Hello")
			self.assertEqual(result["name"], "queued-message")
			sender.assert_called_once_with(self.conversation.name, "Hello")

	def test_inbox_and_outbound_enforce_team_scope(self):
		from frappe_whatsapp_core.inbox import conversation, conversations
		from frappe_whatsapp_core.outbound import queue_text

		team = upsert_team(
			team_name=f"Restricted Team {frappe.generate_hash(length=6)}",
			members=[{"user": "Administrator", "team_role": "Agent"}],
		)
		frappe.db.set_value(
			"WhatsApp Core Conversation",
			self.conversation.name,
			{"assigned_team": team["name"], "assigned_user": None},
		)
		original_user = frappe.session.user
		frappe.local.session.user = "unassigned@example.com"
		try:
			with patch(
				"frappe_whatsapp_core.permissions.frappe.get_roles",
				return_value=["WhatsApp User"],
			):
				self.assertNotIn(
					self.conversation.name,
					[row["name"] for row in conversations(limit=500)],
				)
				with self.assertRaises(frappe.PermissionError):
					conversation(self.conversation.name)
				with self.assertRaises(frappe.PermissionError):
					queue_text(self.conversation.name, "Not allowed")
		finally:
			frappe.local.session.user = original_user

	def test_inbox_and_outbound_enforce_direct_user_assignment(self):
		from frappe_whatsapp_core.inbox import conversation, conversations
		from frappe_whatsapp_core.outbound import queue_text

		frappe.db.set_value(
			"WhatsApp Core Conversation",
			self.conversation.name,
			{"assigned_team": None, "assigned_user": "other-agent@example.com"},
		)
		original_user = frappe.session.user
		frappe.local.session.user = "unassigned@example.com"
		try:
			with patch(
				"frappe_whatsapp_core.permissions.frappe.get_roles",
				return_value=["WhatsApp User"],
			):
				self.assertNotIn(
					self.conversation.name,
					[row["name"] for row in conversations(limit=500)],
				)
				with self.assertRaises(frappe.PermissionError):
					conversation(self.conversation.name)
				with self.assertRaises(frappe.PermissionError):
					queue_text(self.conversation.name, "Not allowed")
		finally:
			frappe.local.session.user = original_user

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
