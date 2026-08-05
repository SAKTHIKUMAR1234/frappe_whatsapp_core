import inspect

from frappe.tests.utils import FrappeTestCase

from frappe_whatsapp_core import api, template_catalog


class TestIntegrationCallbackContract(FrappeTestCase):
	def test_integration_callback_endpoints_keep_required_parameters(self):
		outbound = inspect.signature(api.receive_outbound_result).parameters
		self.assertIn("idempotency_key", outbound)
		self.assertIn("status", outbound)
		self.assertTrue(callable(api.receive))
		self.assertIn("template", inspect.signature(template_catalog.receive_push).parameters)
