from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import now_datetime

from frappe_whatsapp_core.conversation_presence import (
	_presence_key,
	update_conversation_presence,
)
from frappe_whatsapp_core.conversation_reads import mark_conversation_read
from frappe_whatsapp_core.customer_workspace import (
	attach_read_coverage,
	create_contact_folder,
	inbox_navigation,
	operations_dashboard,
	set_contact_folder,
)
from frappe_whatsapp_core.identity import contact_options
from frappe_whatsapp_core.inbox import (
	business_filter_options,
	business_filter_schema,
	conversation_page,
	conversation_unread_counts,
	conversations,
)
from frappe_whatsapp_core.internal_comments import (
	add_comment,
	collaboration_notifications,
	comment_page,
	delete_comment,
	mark_collaboration_notification_read,
	update_comment,
	work_item_assignees,
)
from frappe_whatsapp_core.permissions import assert_call_access, assert_conversation_access
from frappe_whatsapp_core.realtime import (
	conversation_recipients,
	publish_call_changes,
	publish_conversation_presence,
	publish_message_changes,
)
from frappe_whatsapp_core.template_catalog import sync_template_projection
from frappe_whatsapp_core.workspace_api import upsert_team


class TestTeamContactAccess(FrappeTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		suffix = frappe.generate_hash(length=10).lower()
		self.member = self._user(f"team-member-{suffix}@example.com")
		self.outsider = self._user(f"team-outsider-{suffix}@example.com")
		self.identity = self._identity(f"categorized-{suffix}")
		self.uncategorized = self._identity(f"uncategorized-{suffix}")
		self.conversation = self._conversation(self.identity, suffix)
		self.open_conversation = self._conversation(self.uncategorized, f"open-{suffix}")
		self.account = f"team-account-{suffix}"
		settings = frappe.get_single("WhatsApp Core Settings")
		settings.set("accounts", [{
			"channel": self.conversation.channel,
			"account_name": self.account,
			"is_default": 1,
		}])
		settings.save(ignore_permissions=True)
		self.team = upsert_team(
			team_name=f"Access Team {suffix}",
			icon="headphones",
			members=[{"user": self.member, "enabled": 1}],
			contacts=[{"identity": self.identity.name, "enabled": 1}],
		)

	def tearDown(self):
		frappe.set_user("Administrator")
		super().tearDown()

	def test_team_member_can_open_categorized_contact(self):
		frappe.set_user(self.member)
		assert_conversation_access(self.conversation.name)
		row = next(row for row in conversations() if row["name"] == self.conversation.name)
		self.assertEqual(row["contact_teams"][0]["name"], self.team["name"])
		self.assertEqual(row["contact_teams"][0]["icon"], "headphones")

	def test_non_member_cannot_open_or_enumerate_categorized_contact(self):
		frappe.set_user(self.outsider)
		with self.assertRaises(frappe.PermissionError):
			assert_conversation_access(self.conversation.name)
		options = contact_options(search=self.identity.display_value, limit=20)
		self.assertNotIn(self.identity.name, {row["identity"] for row in options})

	def test_generic_doctype_queries_cannot_bypass_team_scope(self):
		frappe.set_user("Administrator")
		message = frappe.get_doc({
			"doctype": "WhatsApp Core Message",
			"message_key": f"team-secret-{frappe.generate_hash(length=10).lower()}",
			"provider_message_id": f"wamid.team-secret-{frappe.generate_hash(length=10).lower()}",
			"conversation": self.conversation.name,
			"channel": self.conversation.channel,
			"remote_identity": self.identity.name,
			"direction": "Inbound",
			"message_type": "Text",
			"body": "private team message",
			"content": {"text": {"body": "private team message"}},
			"provider_timestamp": now_datetime(),
			"delivery_status": "Received",
		}).insert(ignore_permissions=True)

		frappe.set_user(self.outsider)
		self.assertFalse(
			frappe.has_permission(
				"WhatsApp Core Conversation", "read", doc=self.conversation
			)
		)
		self.assertFalse(
			frappe.has_permission("WhatsApp Core Message", "read", doc=message)
		)
		self.assertNotIn(
			self.conversation.name,
			frappe.get_list("WhatsApp Core Conversation", pluck="name"),
		)
		self.assertNotIn(
			message.name,
			frappe.get_list("WhatsApp Core Message", pluck="name"),
		)

	def test_template_queries_hide_non_sendable_records_from_operators(self):
		frappe.set_user("Administrator")
		approved = sync_template_projection({
			"account_name": self.account,
			"name": f"approved_{frappe.generate_hash(length=8).lower()}",
			"language": "en",
			"status": "APPROVED",
		})["name"]
		draft = sync_template_projection({
			"account_name": self.account,
			"name": f"draft_{frappe.generate_hash(length=8).lower()}",
			"language": "en",
			"status": "IN_REVIEW",
		})["name"]

		frappe.set_user(self.outsider)
		visible = set(frappe.get_list("WhatsApp Core Template", pluck="name"))
		self.assertIn(approved, visible)
		self.assertNotIn(draft, visible)
		self.assertFalse(
			frappe.has_permission(
				"WhatsApp Core Template",
				"read",
				doc=frappe.get_doc("WhatsApp Core Template", draft),
			)
		)

	def test_user_without_team_can_open_uncategorized_contact(self):
		frappe.set_user(self.outsider)
		assert_conversation_access(self.open_conversation.name)
		options = contact_options(search=self.uncategorized.display_value, limit=20)
		self.assertIn(self.uncategorized.name, {row["identity"] for row in options})

	def test_team_member_cannot_open_or_enumerate_uncategorized_contact(self):
		frappe.set_user(self.member)
		with self.assertRaises(frappe.PermissionError):
			assert_conversation_access(self.open_conversation.name)
		options = contact_options(search=self.uncategorized.display_value, limit=20)
		self.assertNotIn(self.uncategorized.name, {row["identity"] for row in options})

	def test_manager_can_filter_inbox_by_contact_team(self):
		frappe.set_user("Administrator")
		rows = conversation_page(team=self.team["name"], limit=20)["rows"]
		self.assertIn(self.conversation.name, {row["name"] for row in rows})
		self.assertNotIn(self.open_conversation.name, {row["name"] for row in rows})

	def test_business_filters_use_configured_fields_and_identity_links(self):
		suffix = frappe.generate_hash(length=10).lower()
		source = frappe.get_doc({
			"doctype": "WhatsApp Core Identity Source",
			"source_key": f"filter-user-{suffix}",
			"display_name": "Test business users",
			"source_doctype": "User",
			"enabled": 1,
			"auto_resolve": 0,
			"priority": 1,
			"phone_field": "mobile_no",
			"display_name_field": "first_name",
			"filter_fields": ["first_name", "enabled"],
		}).insert(ignore_permissions=True)
		frappe.get_doc({
			"doctype": "WhatsApp Core Identity Link",
			"identity": self.identity.name,
			"identity_source": source.name,
			"reference_doctype": "User",
			"reference_name": self.member,
			"display_name": "WhatsApp",
			"status": "Active",
		}).insert(ignore_permissions=True)

		schema = next(row for row in business_filter_schema() if row["name"] == source.name)
		self.assertEqual(
			{field["fieldname"] for field in schema["fields"]},
			{"first_name", "enabled"},
		)
		rows = conversation_page(
			business_source=source.name,
			business_filters={"first_name": "Whats"},
			limit=100,
		)["rows"]
		self.assertEqual({row["name"] for row in rows}, {self.conversation.name})
		self.assertFalse(
			conversation_page(
				business_source=source.name,
				business_filters={"first_name": "Does not exist"},
				limit=100,
			)["rows"]
		)
		options = business_filter_options(source.name, "first_name", "Whats")
		self.assertIn("WhatsApp", {row["value"] for row in options})
		with self.assertRaises(frappe.ValidationError):
			conversation_page(
				business_source=source.name,
				business_filters={"email": self.member},
				limit=20,
			)
		with self.assertRaises(frappe.ValidationError):
			business_filter_options(source.name, "email")

	def test_visible_rows_can_lazy_hydrate_permission_scoped_unread_counts(self):
		frappe.get_doc({
			"doctype": "WhatsApp Core Message",
			"message_key": f"lazy-unread-{frappe.generate_hash(length=10).lower()}",
			"provider_message_id": f"wamid.lazy-unread-{frappe.generate_hash(length=10).lower()}",
			"conversation": self.conversation.name,
			"channel": self.conversation.channel,
			"remote_identity": self.identity.name,
			"direction": "Inbound",
			"message_type": "text",
			"body": "Lazy unread badge",
			"content": {"text": {"body": "Lazy unread badge"}},
			"provider_timestamp": now_datetime(),
			"delivery_status": "Received",
		}).insert(ignore_permissions=True)
		frappe.set_user(self.member)
		page = conversation_page(limit=20, include_unread=0)
		row = next(row for row in page["rows"] if row["name"] == self.conversation.name)
		self.assertEqual(row["unread_count"], 0)
		counts = conversation_unread_counts(
			[self.conversation.name, self.open_conversation.name]
		)
		self.assertEqual(counts, {self.conversation.name: 1})

	@patch("frappe_whatsapp_core.conversation_reads.frappe.enqueue")
	def test_opening_conversation_establishes_new_message_unread_baseline(self, _enqueue):
		first = frappe.get_doc({
			"doctype": "WhatsApp Core Message",
			"message_key": f"open-baseline-{frappe.generate_hash(length=10).lower()}",
			"provider_message_id": f"wamid.open-baseline-{frappe.generate_hash(length=10).lower()}",
			"conversation": self.conversation.name,
			"channel": self.conversation.channel,
			"remote_identity": self.identity.name,
			"direction": "Inbound",
			"message_type": "text",
			"body": "Existing unread message",
			"content": {"text": {"body": "Existing unread message"}},
			"provider_timestamp": now_datetime(),
			"delivery_status": "Received",
		}).insert(ignore_permissions=True)
		frappe.set_user(self.member)
		self.assertGreaterEqual(
			conversation_unread_counts([self.conversation.name])[self.conversation.name],
			1,
		)
		mark_conversation_read(self.conversation.name)
		self.assertEqual(conversation_unread_counts([self.conversation.name]), {
			self.conversation.name: 0,
		})
		second = frappe.copy_doc(first)
		second.name = None
		second.message_key = f"new-after-open-{frappe.generate_hash(length=10).lower()}"
		second.provider_message_id = f"wamid.new-after-open-{frappe.generate_hash(length=10).lower()}"
		second.body = "New after opening"
		second.provider_timestamp = now_datetime()
		second.insert(ignore_permissions=True)
		self.assertEqual(conversation_unread_counts([self.conversation.name]), {
			self.conversation.name: 1,
		})

	def test_manager_can_search_inbox_by_fuzzy_name_candidate(self):
		self.identity.db_set("display_value", "Mohammed Anas")
		rows = conversation_page(search="Mohamad Anas", limit=100)["rows"]
		self.assertIn(self.conversation.name, {row["name"] for row in rows})

	def test_manager_can_search_inbox_by_contact_team(self):
		rows = conversation_page(search="Access Tem", limit=100)["rows"]
		self.assertIn(self.conversation.name, {row["name"] for row in rows})
		self.assertNotIn(self.open_conversation.name, {row["name"] for row in rows})

	def test_private_folder_filters_only_the_current_users_visible_contacts(self):
		frappe.set_user("Administrator")
		frappe.get_doc({
			"doctype": "WhatsApp Core Message",
			"message_key": f"folder-unread-{frappe.generate_hash(length=10).lower()}",
			"provider_message_id": f"wamid.folder-unread-{frappe.generate_hash(length=10).lower()}",
			"conversation": self.conversation.name,
			"channel": self.conversation.channel,
			"remote_identity": self.identity.name,
			"direction": "Inbound",
			"message_type": "text",
			"body": "Unread folder message",
			"content": {"text": {"body": "Unread folder message"}},
			"provider_timestamp": now_datetime(),
			"delivery_status": "Received",
		}).insert(ignore_permissions=True)
		frappe.set_user(self.member)
		folder = create_contact_folder("Priority customers", "#7c3aed")
		with patch("frappe_whatsapp_core.customer_workspace.frappe.publish_realtime") as publish:
			result = set_contact_folder(self.identity.name, folder["name"], enabled=1)
		self.assertEqual(result["folder_details"]["contact_count"], 1)
		self.assertEqual(result["folder_details"]["conversation_count"], 1)
		self.assertEqual(result["folder_details"]["unread_conversations"], 1)
		self.assertEqual(result["folder_details"]["unread_count"], 1)
		self.assertEqual(result["folder_details"]["folder_name"], "Priority customers")
		payload = publish.call_args.args[1]
		self.assertEqual(payload["folder_details"]["name"], folder["name"])
		self.assertEqual(payload["conversations"], [self.conversation.name])
		rows = conversation_page(folder=folder["name"], limit=20)["rows"]
		self.assertEqual({row["name"] for row in rows}, {self.conversation.name})
		self.assertEqual(rows[0]["contact_folders"][0]["folder_name"], "Priority customers")
		unread_rows = conversation_page(unread_only=1, limit=20)["rows"]
		self.assertEqual({row["name"] for row in unread_rows}, {self.conversation.name})
		navigation = inbox_navigation()
		self.assertEqual(navigation["conversation_count"], 1)
		self.assertEqual(navigation["unread_conversations"], 1)
		self.assertEqual(navigation["unread_count"], 1)
		priority = next(row for row in navigation["folders"] if row["name"] == folder["name"])
		self.assertEqual(priority["conversation_count"], 1)
		self.assertEqual(priority["unread_conversations"], 1)

		frappe.set_user(self.outsider)
		with self.assertRaises(frappe.DoesNotExistError):
			conversation_page(folder=folder["name"], limit=20)

	def test_team_dashboard_is_scoped_to_the_current_operator(self):
		frappe.set_user(self.member)
		result = operations_dashboard()
		teams = {row["name"]: row for row in result["teams"]}
		self.assertEqual(set(teams), {self.team["name"]})
		self.assertEqual(teams[self.team["name"]]["contact_count"], 1)
		self.assertEqual(result["metrics"]["conversations"], 1)

	def test_message_read_coverage_tracks_the_whole_responsible_team(self):
		message = {"read_by": [{"user": self.member}]}
		expected = attach_read_coverage([message], self.conversation.name)
		self.assertEqual({row["user"] for row in expected}, {self.member})
		self.assertEqual(message["read_coverage"]["read"], 1)
		self.assertEqual(message["read_coverage"]["expected"], 1)
		self.assertTrue(message["read_coverage"]["complete"])

	@patch("frappe_whatsapp_core.inbox.search_presented_identities")
	def test_manager_can_search_business_presented_contact_name(self, presented_search):
		presented_search.return_value = [self.identity.name]
		rows = conversation_page(search="Visible Member Company", limit=100)["rows"]
		self.assertIn(self.conversation.name, {row["name"] for row in rows})
		presented_search.assert_called_once_with("Visible Member Company")

	def test_realtime_recipients_match_team_and_uncategorized_scope(self):
		recipients = conversation_recipients([
			self.conversation.name,
			self.open_conversation.name,
		])

		self.assertIn("Administrator", recipients[self.conversation.name])
		self.assertIn(self.member, recipients[self.conversation.name])
		self.assertNotIn(self.outsider, recipients[self.conversation.name])
		self.assertIn("Administrator", recipients[self.open_conversation.name])
		self.assertIn(self.outsider, recipients[self.open_conversation.name])
		self.assertNotIn(self.member, recipients[self.open_conversation.name])

	def test_presence_publishes_only_to_the_conversation_scope(self):
		with patch("frappe_whatsapp_core.realtime.frappe.publish_realtime") as publish:
			count = publish_conversation_presence(
				self.conversation.name,
				[{"user": self.member, "display_name": "WhatsApp Member", "user_image": ""}],
			)

		self.assertGreaterEqual(count, 2)
		users = {item.kwargs.get("user") for item in publish.call_args_list}
		self.assertIn("Administrator", users)
		self.assertIn(self.member, users)
		self.assertNotIn(self.outsider, users)
		self.assertTrue(all(not item.kwargs["after_commit"] for item in publish.call_args_list))

	def test_internal_comments_are_team_only_editable_and_realtime_scoped(self):
		frappe.set_user(self.member)
		with patch("frappe_whatsapp_core.realtime.frappe.publish_realtime") as publish:
			created = add_comment(self.conversation.name, "Customer requested a callback tomorrow.")

		self.assertEqual(created["user"], self.member)
		self.assertEqual(comment_page(self.conversation.name)["rows"][0]["name"], created["name"])
		users = {item.kwargs.get("user") for item in publish.call_args_list}
		self.assertIn(self.member, users)
		self.assertNotIn(self.outsider, users)
		self.assertTrue(
			frappe.has_permission(
				"WhatsApp Core Internal Comment",
				"read",
				doc=frappe.get_doc("WhatsApp Core Internal Comment", created["name"]),
			)
		)

		updated = update_comment(created["name"], "Callback is confirmed for tomorrow.")
		self.assertEqual(updated["content"], "Callback is confirmed for tomorrow.")

		frappe.set_user(self.outsider)
		with self.assertRaises(frappe.PermissionError):
			comment_page(self.conversation.name)
		with self.assertRaises(frappe.PermissionError):
			update_comment(created["name"], "Out-of-scope edit")
		self.assertNotIn(
			created["name"],
			frappe.get_list("WhatsApp Core Internal Comment", pluck="name"),
		)

		frappe.set_user("Administrator")
		result = delete_comment(created["name"])
		self.assertTrue(result["success"])
		self.assertFalse(frappe.db.exists("WhatsApp Core Internal Comment", created["name"]))

	def test_internal_work_can_reference_messages_assign_and_resolve(self):
		message = frappe.get_doc({
			"doctype": "WhatsApp Core Message",
			"message_key": f"internal-task-{frappe.generate_hash(length=10).lower()}",
			"provider_message_id": f"wamid.internal-task-{frappe.generate_hash(length=10).lower()}",
			"conversation": self.conversation.name,
			"channel": self.conversation.channel,
			"remote_identity": self.identity.name,
			"direction": "Inbound",
			"message_type": "text",
			"body": "Please review this request",
			"content": {"text": {"body": "Please review this request"}},
			"provider_timestamp": now_datetime(),
			"delivery_status": "Received",
		}).insert(ignore_permissions=True)

		self.assertIn(self.member, {row["name"] for row in work_item_assignees(self.conversation.name)})
		with patch(
			"frappe.desk.doctype.notification_log.notification_log.enqueue_create_notification"
		) as notify:
			created = add_comment(
				self.conversation.name,
				"Verify this customer request.",
				message_references=[message.name],
				assigned_to=self.member,
			)
		notify.assert_called_once()
		self.assertEqual(created["message_references"], [message.name])
		self.assertEqual(created["assigned_to"], self.member)
		self.assertEqual(created["status"], "Open")
		notification_payload = notify.call_args.args[1]
		self.assertIn(f"comment={created['name']}", notification_payload["link"])
		self.assertIn(f"message={message.name}", notification_payload["link"])

		frappe.set_user(self.member)
		resolved = update_comment(created["name"], status="Resolved")
		self.assertEqual(resolved["status"], "Resolved")
		self.assertEqual(resolved["resolved_by"], self.member)
		self.assertTrue(resolved["resolved_at"])

	def test_internal_work_supports_summary_mentions_replies_and_durable_notifications(self):
		topic = frappe.get_doc({
			"doctype": "WhatsApp Core Conversation Topic",
			"topic_key": f"collaboration-{frappe.generate_hash(length=10).lower()}",
			"conversation": self.conversation.name,
			"title": "Delivery commitment",
			"summary": "Confirm the promised delivery date.",
			"status": "Open",
			"source": "Manual",
		}).insert(ignore_permissions=True)
		with patch(
			"frappe.desk.doctype.notification_log.notification_log.enqueue_create_notification"
		) as notify:
			root = add_comment(
				self.conversation.name,
				"Please confirm this commitment.",
				mentioned_users=[self.member],
				reference_doctype="WhatsApp Core Conversation Topic",
				reference_name=topic.name,
			)
		notify.assert_called_once()
		self.assertEqual(root["mentioned_users"], [self.member])
		self.assertEqual(root["reference_name"], topic.name)
		self.assertEqual(root["reference_label"], "Delivery commitment")

		frappe.set_user(self.member)
		with patch(
			"frappe.desk.doctype.notification_log.notification_log.enqueue_create_notification"
		) as notify:
			reply = add_comment(
				self.conversation.name,
				"Confirmed with the customer.",
				parent_comment=root["name"],
			)
		notify.assert_called_once()
		self.assertEqual(reply["parent_comment"], root["name"])
		self.assertEqual(reply["parent_user_display_name"], "Administrator")

		with self.assertRaises(frappe.PermissionError):
			add_comment(
				self.conversation.name,
				"Invalid mention",
				mentioned_users=[self.outsider],
			)

		frappe.set_user("Administrator")
		notification = frappe.get_doc({
			"doctype": "Notification Log",
			"for_user": self.member,
			"from_user": "Administrator",
			"type": "Mention",
			"subject": "A teammate needs your attention in WhatsApp",
			"document_type": "WhatsApp Core Internal Comment",
			"document_name": root["name"],
			"read": 0,
		}).insert(ignore_permissions=True)
		frappe.set_user(self.member)
		feed = collaboration_notifications()
		self.assertEqual(feed["rows"][0]["conversation"], self.conversation.name)
		self.assertGreaterEqual(feed["unread"], 1)
		mark_collaboration_notification_read(notification.name)
		self.assertEqual(frappe.db.get_value("Notification Log", notification.name, "read"), 1)

	def test_operator_presence_is_ephemeral_and_rejects_out_of_scope_users(self):
		client_id = f"browser_{frappe.generate_hash(length=16)}"
		try:
			frappe.set_user(self.member)
			with patch(
				"frappe_whatsapp_core.conversation_presence.publish_conversation_presence"
			) as publish:
				result = update_conversation_presence(
					self.conversation.name,
					client_id,
					active=1,
				)
				unchanged = update_conversation_presence(
					self.conversation.name,
					client_id,
					active=1,
				)
			self.assertEqual(result["conversation"], self.conversation.name)
			self.assertEqual(result["viewers"][0]["user"], self.member)
			self.assertEqual(unchanged["viewers"], result["viewers"])
			publish.assert_called_once()

			frappe.set_user(self.outsider)
			with self.assertRaises(frappe.PermissionError):
				update_conversation_presence(self.conversation.name, client_id, active=1)
		finally:
			frappe.cache.delete_key(_presence_key(self.conversation.name))
			frappe.cache.delete_key(f"{_presence_key(self.conversation.name)}:viewers")

	def test_created_message_publishes_complete_delta_only_to_scoped_user_rooms(self):
		message = frappe.get_doc({
			"doctype": "WhatsApp Core Message",
			"message_key": f"realtime-{frappe.generate_hash(length=10).lower()}",
			"provider_message_id": f"wamid.realtime-{frappe.generate_hash(length=10).lower()}",
			"conversation": self.conversation.name,
			"channel": self.conversation.channel,
			"remote_identity": self.identity.name,
			"direction": "Inbound",
			"message_type": "text",
			"body": "Scoped realtime message",
			"content": {"text": {"body": "Scoped realtime message"}},
			"provider_timestamp": now_datetime(),
			"delivery_status": "Received",
		}).insert(ignore_permissions=True)
		with patch("frappe_whatsapp_core.realtime.frappe.publish_realtime") as publish:
			publish_message_changes([{
				"kind": "message",
				"status": "created",
				"name": message.name,
			}])

		calls_by_user = {call.kwargs.get("user"): call for call in publish.call_args_list}
		self.assertIn(self.member, calls_by_user)
		self.assertNotIn(self.outsider, calls_by_user)
		payload = calls_by_user[self.member].args[1]
		self.assertEqual(payload["message_changes"][0]["message"]["name"], message.name)
		self.assertEqual(payload["conversation_rows"][0]["name"], self.conversation.name)
		self.assertIn("unread_count", payload["conversation_rows"][0])
		self.assertTrue(calls_by_user[self.member].kwargs["after_commit"])

	def test_status_delta_does_not_rebuild_conversation_projection(self):
		message = frappe.get_doc({
			"doctype": "WhatsApp Core Message",
			"message_key": f"status-realtime-{frappe.generate_hash(length=10).lower()}",
			"provider_message_id": f"wamid.status-realtime-{frappe.generate_hash(length=10).lower()}",
			"conversation": self.conversation.name,
			"channel": self.conversation.channel,
			"remote_identity": self.identity.name,
			"direction": "Outbound",
			"message_type": "text",
			"body": "Status only",
			"content": {"text": {"body": "Status only"}},
			"provider_timestamp": now_datetime(),
			"delivery_status": "Delivered",
		}).insert(ignore_permissions=True)
		with (
			patch("frappe_whatsapp_core.realtime.frappe.publish_realtime") as publish,
			patch("frappe_whatsapp_core.inbox.conversation_rows_for_realtime") as rows,
		):
			publish_message_changes([{
				"kind": "status",
				"status": "updated",
				"name": message.name,
			}])

		rows.assert_not_called()
		member_payload = next(
			call.args[1]
			for call in publish.call_args_list
			if call.kwargs.get("user") == self.member
		)
		self.assertEqual(member_payload["conversation_rows"], [])
		self.assertEqual(
			set(member_payload["message_changes"][0]["message"]),
			{"name", "conversation", "provider_message_id", "delivery_status", "failure"},
		)

	def test_call_rows_and_realtime_follow_the_same_team_scope(self):
		frappe.set_user("Administrator")
		call = frappe.get_doc({
			"doctype": "WhatsApp Core Call",
			"call_id": f"team-call-{frappe.generate_hash(length=10).lower()}",
			"channel": self.conversation.channel,
			"conversation": self.conversation.name,
			"remote_identity": self.identity.name,
			"direction": "Inbound",
			"status": "connect",
			"session": {"sdp_type": "offer", "sdp": "v=0"},
			"last_event": {"event": "connect"},
		}).insert(ignore_permissions=True)

		frappe.set_user(self.member)
		assert_call_access(call.call_id)
		self.assertTrue(frappe.has_permission("WhatsApp Core Call", "read", doc=call))

		frappe.set_user(self.outsider)
		with self.assertRaises(frappe.PermissionError):
			assert_call_access(call.call_id)
		self.assertFalse(frappe.has_permission("WhatsApp Core Call", "read", doc=call))

		frappe.set_user("Administrator")
		with patch("frappe_whatsapp_core.realtime.frappe.publish_realtime") as publish:
			publish_call_changes([call.name])
		users = {item.kwargs.get("user") for item in publish.call_args_list}
		self.assertIn(self.member, users)
		self.assertNotIn(self.outsider, users)
		payload = next(
			item.args[1] for item in publish.call_args_list
			if item.kwargs.get("user") == self.member
		)
		self.assertEqual(payload["call"]["call_id"], call.call_id)

	def _user(self, email):
		user = frappe.get_doc({
			"doctype": "User",
			"email": email,
			"first_name": "WhatsApp",
			"enabled": 1,
			"send_welcome_email": 0,
		}).insert(ignore_permissions=True)
		user.add_roles("WhatsApp User")
		return user.name

	def _identity(self, label):
		return frappe.get_doc({
			"doctype": "WhatsApp Core Identity",
			"identity_key": label,
			"identity_type": "WhatsApp",
			"normalized_value": f"91{frappe.generate_hash(length=10).lower()}",
			"display_value": label,
			"provider": "meta",
			"status": "Active",
		}).insert(ignore_permissions=True)

	def _conversation(self, identity, suffix):
		channel = frappe.get_doc({
			"doctype": "WhatsApp Core Channel",
			"channel_key": f"meta:team-access-{suffix}",
			"display_name": "Team access test",
			"provider": "meta",
			"phone_number_id": f"team-access-{suffix}",
			"enabled": 1,
		}).insert(ignore_permissions=True)
		return frappe.get_doc({
			"doctype": "WhatsApp Core Conversation",
			"conversation_key": f"{channel.name}:{identity.name}",
			"channel": channel.name,
			"remote_identity": identity.name,
			"status": "Open",
			"last_message_at": now_datetime(),
		}).insert(ignore_permissions=True)
