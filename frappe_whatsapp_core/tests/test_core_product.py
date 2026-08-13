import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import now_datetime

from frappe_whatsapp_core.inbox import conversation, conversations
from frappe_whatsapp_core.materializer import (
	get_or_create_channel,
	get_or_create_conversation,
	get_or_create_identity,
)
from frappe_whatsapp_core.outbound import (
	queue_template_internal,
	queue_text_internal,
	start_conversation,
)


class TestCoreProduct(FrappeTestCase):
	def setUp(self):
		super().setUp()
		self.suffix = frappe.generate_hash(length=10)
		self.phone_suffix = now_datetime().strftime("%H%M%S%f")[-10:]
		self.channel = get_or_create_channel(f"core-product-{self.suffix}")
		self.identity = get_or_create_identity(f"91{self.phone_suffix}")
		self.thread = get_or_create_conversation(self.channel, self.identity)

	def test_core_settings_validate_channel_routing(self):
		settings = frappe.get_single("WhatsApp Core Settings")
		settings.enabled = 1
		settings.outbound_enabled = 1
		settings.hub_url = "https://hub.example.test/"
		settings.api_key = f"key-{self.suffix}"
		settings.api_secret = f"secret-{self.suffix}"
		settings.request_timeout = 20
		settings.set("accounts", [{
			"channel": self.channel.name,
			"account_name": f"account-{self.suffix}",
			"is_default": 1,
		}])
		settings.save()
		settings.reload()

		self.assertEqual(settings.hub_url, "https://hub.example.test")
		self.assertEqual(settings.get_account_name(self.channel.name), f"account-{self.suffix}")
		self.assertEqual(settings.get_password("api_key"), f"key-{self.suffix}")

	def test_new_chat_can_use_an_existing_core_contact(self):
		started = start_conversation(
			self.channel.name,
			identity=self.identity.name,
		)
		self.assertEqual(started["conversation"], self.thread.name)
		self.assertEqual(started["identity"], self.identity.name)
		self.assertEqual(started["phone_number"], self.identity.normalized_value)

	def test_optimistic_inbox_and_template_window_gate(self):
		self.thread.last_inbound_at = now_datetime()
		self.thread.save(ignore_permissions=True)
		template = frappe.get_doc({
			"doctype": "WhatsApp Core Template",
			"template_key": f"welcome-{self.suffix}",
			"template_name": f"welcome_{self.suffix}",
			"language_code": "en",
			"approval_status": "APPROVED",
			"enabled": 1,
			"body_text": "Welcome {{1}}",
			"footer_text": "Reply STOP to opt out",
			"components": json.dumps([
				{"type": "BODY", "text": "Welcome {{1}}"},
				{
					"type": "BUTTONS",
					"buttons": [{"type": "QUICK_REPLY", "text": "Continue"}],
				},
			]),
		}).insert(ignore_permissions=True)

		with (
			patch("frappe_whatsapp_core.outbound.outbound_ready", return_value=True),
			patch("frappe_whatsapp_core.outbound._run_preflight_hooks"),
			patch("frappe_whatsapp_core.outbound.frappe.enqueue"),
			patch("frappe_whatsapp_core.outbound.frappe.publish_realtime"),
		):
			client_message_id = "f9cc5adc-1b9c-4be1-aee7-b23e4c390ac2"
			text = queue_text_internal(
				self.thread.name,
				"Hello",
				"Core Test",
				client_message_id=client_message_id,
			)
			started = start_conversation(
				self.channel.name,
				f"92{self.phone_suffix}",
				"New contact",
			)
			opening = queue_template_internal(
				started["conversation"],
				template.name,
				components=[{
					"type": "body",
					"parameters": [{"type": "text", "text": "Customer"}],
				}],
				source="Core Test",
			)

		self.assertEqual(text.delivery_status, "Queued")
		self.assertEqual(text.provider_message_id, f"local:{client_message_id}")
		self.assertEqual(opening.message_type, "template")
		self.assertEqual(opening.body, "Welcome Customer")
		opening_content = json.loads(opening.content)
		self.assertEqual(opening_content["template_snapshot"]["body"], "Welcome Customer")
		self.assertEqual(opening_content["template_snapshot"]["footer"], "Reply STOP to opt out")
		self.assertEqual(
			opening_content["template_snapshot"]["buttons"],
			[{"label": "Continue", "type": "QUICK_REPLY", "url": ""}],
		)
		rows = conversations(limit=100)
		self.assertIn(self.thread.name, {row["name"] for row in rows})
		snapshot = conversation(self.thread.name)
		self.assertEqual(snapshot["messages"][-1]["body"], "Hello")
		self.assertTrue(snapshot["outbound"]["text_allowed"])
