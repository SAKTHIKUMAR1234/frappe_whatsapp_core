from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from frappe_whatsapp_core.flow_endpoint import handle


class TestMetaFlowEndpoint(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")

	@patch("frappe_whatsapp_core.flow_endpoint.frappe.get_doc")
	@patch("frappe_whatsapp_core.flow_endpoint._cached_response", return_value=None)
	@patch("frappe_whatsapp_core.flow_endpoint._channel_for", return_value="CHANNEL-1")
	@patch("frappe_whatsapp_core.flow_endpoint._resolve_account_name", return_value="ACCOUNT-1")
	def test_ping_is_handled_without_business_hook(self, resolve, channel, cached, get_doc):
		log = MagicMock()
		get_doc.return_value = log
		with patch("frappe_whatsapp_core.permissions.frappe.get_roles", return_value=["System Manager"]):
			result = handle("ACCOUNT-1", "PHONE-1", {"action": "ping", "version": "3.0"})
		self.assertEqual(result, {"data": {"status": "active"}, "_http_status": 200})
		self.assertEqual(log.status, "Completed")

	@patch("frappe_whatsapp_core.flow_endpoint.frappe.get_attr")
	@patch("frappe_whatsapp_core.flow_endpoint.frappe.get_hooks")
	@patch("frappe_whatsapp_core.flow_endpoint.frappe.get_doc")
	@patch("frappe_whatsapp_core.flow_endpoint._cached_response", return_value=None)
	@patch("frappe_whatsapp_core.flow_endpoint._channel_for", return_value="CHANNEL-1")
	@patch("frappe_whatsapp_core.flow_endpoint._resolve_account_name", return_value="ACCOUNT-1")
	def test_business_handler_owns_data_exchange(
		self, resolve, channel, cached, get_doc, get_hooks, get_attr
	):
		get_doc.return_value = MagicMock()
		get_hooks.return_value = ["custom_app.flow_handler"]
		get_attr.return_value = lambda payload, context: {
			"screen": "SUCCESS",
			"data": {"extension_message_response": {"params": {"flow_token": payload["flow_token"]}}},
		}
		with patch("frappe_whatsapp_core.permissions.frappe.get_roles", return_value=["System Manager"]):
			result = handle(
				"ACCOUNT-1",
				"PHONE-1",
				{
					"action": "data_exchange",
					"screen": "DETAILS",
					"flow_token": "token-1",
					"data": {"name": "Customer"},
				},
			)
		self.assertEqual(result["screen"], "SUCCESS")
		self.assertEqual(result["_http_status"], 200)
		get_attr.assert_called_once_with("custom_app.flow_handler")
