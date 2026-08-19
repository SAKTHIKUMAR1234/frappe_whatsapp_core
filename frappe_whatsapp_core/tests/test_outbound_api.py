import json
import uuid
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from frappe_whatsapp_core import outbound_api
from frappe_whatsapp_core.template_catalog import scoped_template_key


class TestOutboundAPI(FrappeTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		suffix = frappe.generate_hash(length=8).lower()
		self.phone_number_id = f"api-phone-{suffix}"
		self.channel = frappe.get_doc({
			"doctype": "WhatsApp Core Channel",
			"channel_key": f"meta:{self.phone_number_id}",
			"display_name": "Outbound API test",
			"provider": "meta",
			"phone_number_id": self.phone_number_id,
			"enabled": 1,
		}).insert(ignore_permissions=True)
		self.account = f"api-account-{suffix}"
		settings = frappe.get_single("WhatsApp Core Settings")
		settings.set("accounts", [{
			"channel": self.channel.name,
			"account_name": self.account,
			"is_default": 1,
		}])
		settings.save(ignore_permissions=True)
		self.phone = f"91{int(suffix, 36) % 10_000_000_000:010d}"

	def test_send_text_by_phone_returns_stable_queue_receipt(self):
		with (
			patch("frappe_whatsapp_core.outbound.outbound_ready", return_value=True),
			patch("frappe_whatsapp_core.outbound._within_service_window", return_value=True),
			patch("frappe_whatsapp_core.outbound._enqueue_message_delivery"),
		):
			result = outbound_api.send_text(
				self.phone,
				"API hello",
				phone_number_id=self.phone_number_id,
				client_message_id=str(uuid.uuid4()),
			)
		self.assertEqual(result["status"], "queued")
		self.assertEqual(result["delivery_status"], "Queued")
		self.assertTrue(result["conversation"])

	def test_send_template_accepts_meta_id_and_positional_values(self):
		template_name = f"api_{frappe.generate_hash(length=6).lower()}"
		provider_id = str(int(frappe.generate_hash(length=12), 36))
		frappe.get_doc({
			"doctype": "WhatsApp Core Template",
			"template_key": scoped_template_key(self.account, template_name, "en"),
			"account_name": self.account,
			"channel": self.channel.name,
			"template_name": template_name,
			"template_id": provider_id,
			"language_code": "en",
			"approval_status": "APPROVED",
			"enabled": 1,
			"body_text": "Hello {{1}}, your order is {{2}}",
		}).insert(ignore_permissions=True)
		with (
			patch("frappe_whatsapp_core.outbound.outbound_ready", return_value=True),
			patch("frappe_whatsapp_core.outbound._enqueue_message_delivery"),
		):
			result = outbound_api.send_template(
				self.phone,
				provider_id,
				parameters='["Sakthi", "ready"]',
				phone_number_id=self.phone_number_id,
			)
		message = frappe.get_doc("WhatsApp Core Message", result["message"])
		content = json.loads(message.content)
		self.assertEqual(message.body, "Hello Sakthi, your order is ready")
		self.assertEqual(
			content["components"][0]["parameters"],
			[
				{"type": "text", "text": "Sakthi"},
				{"type": "text", "text": "ready"},
			],
		)

	def test_phone_api_requires_management_access(self):
		original_user = frappe.session.user
		frappe.local.session.user = "limited@example.com"
		try:
			with (
				patch.object(outbound_api.frappe, "get_roles", return_value=["WhatsApp User"]),
				self.assertRaises(frappe.PermissionError),
			):
				outbound_api.send_text(self.phone, "Denied")
		finally:
			frappe.local.session.user = original_user

	def test_parameter_fields_reject_non_arrays(self):
		with self.assertRaises(frappe.ValidationError):
			outbound_api.send_template(
				self.phone,
				"any-template",
				parameters='{"1":"not-an-array"}',
			)
