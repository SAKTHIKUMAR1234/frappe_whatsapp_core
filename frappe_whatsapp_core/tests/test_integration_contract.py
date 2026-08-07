import inspect
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from frappe_whatsapp_core import api, template_catalog


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
