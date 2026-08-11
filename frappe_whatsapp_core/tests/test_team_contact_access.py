import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import now_datetime

from frappe_whatsapp_core.identity import contact_options
from frappe_whatsapp_core.inbox import conversations
from frappe_whatsapp_core.permissions import assert_conversation_access
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

	def test_uncategorized_contact_remains_visible(self):
		frappe.set_user(self.outsider)
		assert_conversation_access(self.open_conversation.name)
		options = contact_options(search=self.uncategorized.display_value, limit=20)
		self.assertIn(self.uncategorized.name, {row["identity"] for row in options})

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
