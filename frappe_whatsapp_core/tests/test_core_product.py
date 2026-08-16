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
	_message_payload,
	outbound_ready,
	queue_template_internal,
	queue_text_internal,
	start_conversation,
)
from frappe_whatsapp_core.template_catalog import scoped_template_key


class TestCoreProduct(FrappeTestCase):
	def setUp(self):
		super().setUp()
		self.suffix = frappe.generate_hash(length=10)
		self.phone_suffix = now_datetime().strftime("%H%M%S%f")[-10:]
		self.channel = get_or_create_channel(f"core-product-{self.suffix}")
		self.account = f"core-product-account-{self.suffix}"
		settings = frappe.get_single("WhatsApp Core Settings")
		settings.set("accounts", [{
			"channel": self.channel.name,
			"account_name": self.account,
			"is_default": 1,
		}])
		settings.save(ignore_permissions=True)
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

		unmapped = get_or_create_channel(f"core-unmapped-{self.suffix}")
		with self.assertRaises(frappe.ValidationError):
			settings.get_account_name(unmapped.name)
		with patch(
			"frappe_whatsapp_core.outbound.connection_status",
			return_value={
				"enabled": True,
				"outbound_enabled": True,
				"credentials_configured": True,
				"account_count": 1,
			},
		):
			self.assertTrue(outbound_ready(self.channel.name))
			self.assertFalse(outbound_ready(unmapped.name))

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
			"template_key": scoped_template_key(self.account, f"welcome_{self.suffix}", "en"),
			"account_name": self.account,
			"channel": self.channel.name,
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

	def test_named_template_parameters_are_exact_and_rendered(self):
		template = frappe.get_doc({
			"doctype": "WhatsApp Core Template",
			"template_key": scoped_template_key(self.account, f"named_{self.suffix}", "en"),
			"account_name": self.account,
			"channel": self.channel.name,
			"template_name": f"named_{self.suffix}",
			"language_code": "en",
			"approval_status": "APPROVED",
			"enabled": 1,
			"parameter_format": "NAMED",
			"body_text": "Order {{order_id}} for {{customer_name}} is ready",
			"components": json.dumps([{
				"type": "BODY",
				"text": "Order {{order_id}} for {{customer_name}} is ready",
				"example": {
					"body_text_named_params": [
						{"param_name": "order_id", "example": "A-1"},
						{"param_name": "customer_name", "example": "Sam"},
					],
				},
			}]),
		}).insert(ignore_permissions=True)
		components = [{
			"type": "body",
			"parameters": [
				{"type": "text", "parameter_name": "order_id", "text": "A-2"},
				{"type": "text", "parameter_name": "customer_name", "text": "Lee"},
			],
		}]
		with (
			patch("frappe_whatsapp_core.outbound.outbound_ready", return_value=True),
			patch("frappe_whatsapp_core.outbound._run_preflight_hooks"),
		):
			queued = queue_template_internal(
				self.thread.name,
				template.name,
				components=components,
				enqueue_delivery=False,
			)
		self.assertEqual(queued.body, "Order A-2 for Lee is ready")
		self.assertEqual(json.loads(queued.content)["components"], components)
		provider_payload = _message_payload(
			frappe.get_doc("WhatsApp Core Message", queued.name),
			self.identity.normalized_value,
		)
		self.assertEqual(provider_payload["template"]["components"], components)

		with self.assertRaisesRegex(frappe.ValidationError, "exactly match"):
			queue_template_internal(
				self.thread.name,
				template.name,
				components=[{
					"type": "body",
					"parameters": [{
						"type": "text",
						"parameter_name": "order_id",
						"text": "A-2",
					}],
				}],
				enqueue_delivery=False,
			)

		template.components = json.dumps([{
			"type": "BODY",
			"text": "Order {{1}} is ready",
		}])
		template.body_text = "Order {{1}} is ready"
		template.save(ignore_permissions=True)
		with self.assertRaisesRegex(frappe.ValidationError, "NAMED BODY"):
			queue_template_internal(
				self.thread.name,
				template.name,
				components=[{
					"type": "body",
					"parameters": [{"type": "text", "text": "A-3"}],
				}],
				enqueue_delivery=False,
			)

		template.parameter_format = "POSITIONAL"
		template.components = json.dumps([{
			"type": "BODY",
			"text": "Order {{order_id}} is ready",
		}])
		template.body_text = "Order {{order_id}} is ready"
		template.save(ignore_permissions=True)
		with self.assertRaisesRegex(frappe.ValidationError, "POSITIONAL BODY"):
			queue_template_internal(
				self.thread.name,
				template.name,
				components=[{
					"type": "body",
					"parameters": [{
						"type": "text",
						"parameter_name": "order_id",
						"text": "A-4",
					}],
				}],
				enqueue_delivery=False,
			)
