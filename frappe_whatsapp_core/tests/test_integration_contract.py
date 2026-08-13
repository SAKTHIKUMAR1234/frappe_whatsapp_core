import inspect
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from frappe_whatsapp_core import api, template_catalog
from frappe_whatsapp_core.mcp_tools import TOOL_DEFINITIONS


class TestIntegrationCallbackContract(FrappeTestCase):
	def test_integration_callback_endpoints_keep_required_parameters(self):
		outbound = inspect.signature(api.receive_outbound_result).parameters
		self.assertIn("idempotency_key", outbound)
		self.assertIn("status", outbound)
		self.assertTrue(callable(api.receive))
		self.assertIn("template", inspect.signature(template_catalog.receive_push).parameters)

	def test_integration_callbacks_require_core_management_access(self):
		original_user = frappe.session.user
		frappe.local.session.user = "limited@example.com"
		try:
			with (
				patch.object(api.frappe, "get_roles", return_value=["WhatsApp User"]),
				self.assertRaises(frappe.PermissionError),
			):
				api.receive_outbound_result("not-used", "sent")

			with (
				patch.object(api.frappe, "get_roles", return_value=["WhatsApp User"]),
				self.assertRaises(frappe.PermissionError),
			):
				api.receive()
		finally:
			frappe.local.session.user = original_user

	def test_template_authoring_is_exposed_through_audited_mcp_contracts(self):
		tool_names = {tool["name"] for tool in TOOL_DEFINITIONS}
		self.assertIn("whatsapp.create_template", tool_names)
		self.assertIn("whatsapp.update_template", tool_names)

	def test_core_template_edit_is_scoped_to_site_and_reprojects_hub_result(self):
		key = template_catalog.sync_template_projection({
			"hub_template_name": "hub-template-test",
			"name": f"contract_{frappe.generate_hash(length=8).lower()}",
			"language": "en",
			"category": "UTILITY",
			"status": "APPROVED",
			"components": [{"type": "BODY", "text": "Original body"}],
		})["name"]
		with patch.object(template_catalog, "call_management") as call_management:
			call_management.return_value = {
				"success": True,
				"template": {
					"hub_template_name": "hub-template-test",
					"name": frappe.db.get_value(
						"WhatsApp Core Template", key, "template_name"
					),
					"language": "en",
					"category": "UTILITY",
					"status": "IN_REVIEW",
					"components": [{"type": "BODY", "text": "Revised body"}],
				},
			}
			result = template_catalog.request_template_upsert(
				template={"body_text": "Revised body"},
				template_key=key,
			)
		self.assertTrue(result["success"])
		self.assertEqual(result["approval_status"], "IN_REVIEW")
		arguments = call_management.call_args.args[1]
		self.assertEqual(arguments["site_name"], frappe.local.site)
		self.assertEqual(arguments["hub_template_name"], "hub-template-test")
		self.assertEqual(
			frappe.db.get_value(
				"WhatsApp Core Template", key, ["approval_status", "enabled", "body_text"], as_dict=True
			),
			{"approval_status": "IN_REVIEW", "enabled": 0, "body_text": "Revised body"},
		)
