from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from frappe_whatsapp_core.calling import get_call_permission
from frappe_whatsapp_core.groups import group_workspace, send_group_message
from frappe_whatsapp_core.materializer import get_or_create_channel, get_or_create_group_identity, materialize_call


class TestGroupsAndCalling(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")

	@patch("frappe_whatsapp_core.groups._accounts")
	@patch("frappe_whatsapp_core.groups._account", return_value="Hub Account")
	@patch("frappe_whatsapp_core.groups._call")
	def test_group_workspace_and_send_use_hub(self, call, account, accounts):
		accounts.return_value = [{"account_name": "Hub Account", "display_name": "Primary"}]
		call.side_effect = [{"data": [{"id": "GROUP-1"}]}, {"messages": [{"id": "wamid.1"}]}]
		workspace = group_workspace()
		sent = send_group_message("Hub Account", "GROUP-1", "text", {"body": "Hello"})
		self.assertEqual(workspace["data"][0]["id"], "GROUP-1")
		self.assertEqual(sent["messages"][0]["id"], "wamid.1")
		self.assertEqual(call.call_args_list[1].args[0:2], ("groups", "send_group_message"))

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
		created = materialize_call(channel, {
			"id": "CALL-1", "event": "connect", "from": "919876543210",
			"timestamp": "1785900000", "session": {"sdp_type": "offer", "sdp": "v=0"},
		})
		self.assertEqual(created["status"], "created")
		self.assertEqual(frappe.db.get_value("WhatsApp Core Call", "CALL-1", "status"), "connect")
