from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from frappe_whatsapp_core.hub_client import call_management
from frappe_whatsapp_core.meta_flows import (
	create_flow,
	flow_endpoint_status,
	flow_workspace,
	get_business_public_key,
	get_flow,
	migrate_flows,
	provision_flow_endpoint,
	set_business_public_key,
	upload_flow_json,
)


class TestHubManagementClient(FrappeTestCase):
	@patch("frappe_whatsapp_core.hub_client._session.post")
	@patch("frappe_whatsapp_core.hub_client.get_settings")
	def test_management_call_uses_hub_credentials(self, get_settings, post):
		settings = SimpleNamespace(
			hub_url="https://hub.invalid",
			request_timeout=30,
			get_hub_auth_headers=lambda: {"Authorization": "token key:secret"},
		)
		get_settings.return_value = settings
		response = MagicMock(ok=True)
		response.json.return_value = {"message": {"success": True, "data": []}}
		post.return_value = response
		result = call_management(
			"frappe_whatsapp_integration.frappe_whatsapp_hub.api.meta_flows.list_flows",
			{"waba_name": "WABA"},
		)
		self.assertTrue(result["success"])
		self.assertTrue(post.call_args.args[0].endswith("api.meta_flows.list_flows"))
		self.assertNotIn("access_token", post.call_args.kwargs["json"])


class TestMetaFlowProxy(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.accounts = [
			{
				"account_name": "Hub Account",
				"channel": "Channel",
				"display_name": "Primary",
				"phone_number_id": "PHONE-1",
				"is_default": True,
			}
		]

	@patch("frappe_whatsapp_core.meta_flows._call")
	@patch("frappe_whatsapp_core.meta_flows._accounts")
	def test_workspace_lists_meta_not_local_flows(self, accounts, call):
		accounts.return_value = self.accounts
		call.side_effect = [
			{"account_name": "Hub Account", "waba_name": "WABA Doc", "waba_id": "WABA-1"},
			{"success": True, "data": [{"id": "FLOW-1", "name": "Support", "status": "DRAFT"}]},
		]
		result = flow_workspace()
		self.assertEqual(result["flows"][0]["id"], "FLOW-1")
		self.assertEqual(call.call_args_list[1].args[0:2], ("meta_flows", "list_flows"))

	@patch("frappe_whatsapp_core.meta_flows._context", return_value={"waba_name": "WABA Doc"})
	@patch("frappe_whatsapp_core.meta_flows._call")
	def test_create_and_upload_stay_on_meta(self, call, context):
		call.side_effect = [
			{"success": True, "data": {"id": "FLOW-1"}},
			{"success": True, "data": {"validation_errors": []}},
		]
		created = create_flow("Hub Account", "Support", ["CUSTOMER_SUPPORT"])
		uploaded = upload_flow_json("Hub Account", "FLOW-1", {"version": "7.1", "screens": []})
		self.assertEqual(created["data"]["id"], "FLOW-1")
		self.assertEqual(uploaded["data"]["validation_errors"], [])
		self.assertEqual(call.call_args_list[0].args[0:2], ("meta_flows", "create_flow"))
		self.assertEqual(call.call_args_list[1].args[0:2], ("meta_flows", "upload_flow_json"))

	@patch("frappe_whatsapp_core.meta_flows._context", return_value={"waba_name": "WABA Doc"})
	@patch("frappe_whatsapp_core.meta_flows._call")
	def test_get_flow_includes_meta_asset(self, call, context):
		call.side_effect = [
			{"data": {"id": "FLOW-1", "status": "DRAFT"}},
			{"data": {"version": "7.1", "screens": []}, "asset": {"name": "flow.json"}},
		]
		result = get_flow("Hub Account", "FLOW-1")
		self.assertEqual(result["flow_json"]["version"], "7.1")
		self.assertEqual(call.call_args_list[1].args[1], "get_flow_json")

	@patch("frappe_whatsapp_core.meta_flows._context", return_value={"waba_name": "Destination WABA"})
	@patch("frappe_whatsapp_core.meta_flows._call")
	def test_migration_targets_mapped_destination_waba(self, call, context):
		call.return_value = {"data": [{"id": "FLOW-2"}]}
		result = migrate_flows("Hub Account", "SOURCE-WABA", ["Support"])
		self.assertEqual(result["data"][0]["id"], "FLOW-2")
		self.assertEqual(call.call_args.args[0:2], ("meta_flows", "migrate_flows"))
		self.assertEqual(call.call_args.args[2]["destination_waba_name"], "Destination WABA")

	@patch("frappe_whatsapp_core.meta_flows._resolve_account_name", return_value="Hub Account")
	@patch("frappe_whatsapp_core.meta_flows._call")
	def test_flow_public_key_stays_on_mapped_account(self, call, resolve):
		call.side_effect = [{"data": {"business_public_key": "KEY"}}, {"success": True}]
		self.assertEqual(get_business_public_key("Hub Account")["data"]["business_public_key"], "KEY")
		set_business_public_key("Hub Account", "NEW KEY")
		self.assertEqual(call.call_args_list[0].args[0:2], ("meta_flows", "get_business_public_key"))
		self.assertEqual(call.call_args_list[1].args[2]["business_public_key"], "NEW KEY")

	@patch("frappe_whatsapp_core.meta_flows._resolve_account_name", return_value="Hub Account")
	@patch("frappe_whatsapp_core.meta_flows._call")
	def test_flow_endpoint_provisioning_stays_in_integration(self, call, resolve):
		call.side_effect = [
			{"provisioned": False, "endpoint_uri": "https://hub.invalid/flow"},
			{"provisioned": True, "public_key_fingerprint": "abc"},
		]
		self.assertFalse(flow_endpoint_status("Hub Account")["provisioned"])
		self.assertTrue(provision_flow_endpoint("Hub Account")["provisioned"])
		self.assertEqual(call.call_args_list[0].args[0:2], ("flow_endpoint", "status"))
		self.assertEqual(call.call_args_list[1].args[0:2], ("flow_endpoint", "provision"))
