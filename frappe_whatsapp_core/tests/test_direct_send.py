import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import now_datetime

from frappe_whatsapp_core.materializer import (
	get_or_create_channel,
	get_or_create_conversation,
	get_or_create_identity,
	materialize_status,
)
from frappe_whatsapp_core.outbound import (
	_message_payload,
	queue_direct_interactive_internal,
	queue_direct_text_internal,
	queue_text_internal,
)


class TestDirectSend(FrappeTestCase):
	def setUp(self):
		super().setUp()
		self.suffix = frappe.generate_hash(length=10).lower()
		self.channel = get_or_create_channel(
			f"direct-phone-{self.suffix}", f"direct-waba-{self.suffix}"
		)
		settings = frappe.get_single("WhatsApp Core Settings")
		settings.set("accounts", [{
			"channel": self.channel.name,
			"account_name": f"direct-account-{self.suffix}",
			"is_default": 1,
		}])
		settings.save(ignore_permissions=True)
		self.identity = get_or_create_identity(
			f"1415{now_datetime().strftime('%H%M%S%f')[-7:]}", resolve=False
		)
		self.conversation = get_or_create_conversation(self.channel, self.identity)

	def _queue(self, category, client_message_id, **kwargs):
		with (
			patch("frappe_whatsapp_core.outbound.outbound_ready", return_value=True),
			patch("frappe_whatsapp_core.outbound._run_preflight_hooks"),
		):
			return queue_direct_text_internal(
				self.conversation.name,
				"Your order has shipped",
				category,
				"Direct Send Test",
				client_message_id=client_message_id,
				enqueue_delivery=False,
				**kwargs,
			)

	def _queue_interactive(self, payload, client_message_id, **kwargs):
		with (
			patch("frappe_whatsapp_core.outbound.outbound_ready", return_value=True),
			patch("frappe_whatsapp_core.outbound._run_preflight_hooks"),
		):
			return queue_direct_interactive_internal(
				self.conversation.name,
				payload,
				client_message_id=client_message_id,
				enqueue_delivery=False,
				**kwargs,
			)

	def test_utility_is_durable_and_emits_exact_top_level_category(self):
		queued = self._queue(
			"UTILITY",
			"c60b1605-3d75-4dbf-8337-b767a7909e16",
			ttl_seconds="600",
			template_name="order_shipped_v2",
		)
		message = frappe.get_doc("WhatsApp Core Message", queued.name)
		content = json.loads(message.content)
		self.assertEqual(content["direct_send_category"], "utility")
		payload = _message_payload(message, self.identity.normalized_value)
		self.assertEqual(payload["category"], "utility")
		self.assertEqual(payload["type"], "text")
		self.assertEqual(payload["text"], {"body": "Your order has shipped"})
		self.assertEqual(payload["ttl_seconds"], 600)
		self.assertEqual(
			payload["direct_send_config"],
			{"template_name": "order_shipped_v2"},
		)
		self.assertNotIn("endpoint", payload)

	def test_authentication_text_and_category_idempotency_are_strict(self):
		client_id = "459cff6c-c9bb-4df1-9782-d971cc86c594"
		queued = self._queue("authentication", client_id)
		message = frappe.get_doc("WhatsApp Core Message", queued.name)
		self.assertEqual(
			_message_payload(message, self.identity.normalized_value)["category"],
			"authentication",
		)
		with self.assertRaises(frappe.ValidationError):
			self._queue("utility", client_id)

	def test_authentication_requires_phone_but_utility_accepts_bsuid(self):
		bsuid = f"US.{self.suffix}"
		identity = get_or_create_identity(
			bsuid,
			scope=self.channel.name,
			aliases={"user_id": bsuid},
		)
		conversation = get_or_create_conversation(self.channel, identity)
		with (
			patch("frappe_whatsapp_core.outbound.outbound_ready", return_value=True),
			patch("frappe_whatsapp_core.outbound._run_preflight_hooks"),
		):
			with self.assertRaisesRegex(
				frappe.ValidationError,
				"phone number",
			):
				queue_direct_text_internal(
					conversation.name,
					"Your verification code is 123456",
					"authentication",
					client_message_id="1219ace6-9292-49c2-a0c3-8742940014c0",
					enqueue_delivery=False,
				)
			queued = queue_direct_text_internal(
				conversation.name,
				"Your order has shipped",
				"utility",
				client_message_id="c6846abc-65ff-4d1a-a4b5-a8273b78f2be",
				enqueue_delivery=False,
			)
		message = frappe.get_doc("WhatsApp Core Message", queued.name)
		payload = _message_payload(message, bsuid)
		self.assertEqual(payload["recipient"], bsuid)
		self.assertNotIn("to", payload)

		# A durable authentication row must remain fail-closed at delivery even
		# if bad legacy data bypassed the queue-time recipient check.
		message.content = {
			**json.loads(message.content),
			"direct_send_category": "authentication",
		}
		message.save(ignore_permissions=True)
		with self.assertRaisesRegex(frappe.ValidationError, "phone number"):
			_message_payload(message, bsuid)

	def test_invalid_or_corrupt_category_fails_closed(self):
		with self.assertRaises(frappe.ValidationError):
			self._queue("marketing", "427404ca-979f-45a4-a1e3-8204490ab27f")
		queued = self._queue("utility", "dba6426d-e8fa-49db-a02c-0e59e069bb03")
		message = frappe.get_doc("WhatsApp Core Message", queued.name)
		content = json.loads(message.content)
		content["direct_send_category"] = "arbitrary"
		message.content = content
		message.save(ignore_permissions=True)
		with self.assertRaises(frappe.ValidationError):
			_message_payload(message, self.identity.normalized_value)

	def test_ttl_is_category_bounded_and_idempotent(self):
		with self.assertRaisesRegex(frappe.ValidationError, "between 30 and 43200"):
			self._queue(
				"utility",
				"139c2601-81f6-4451-b8d8-78e3b46cfd10",
				ttl_seconds=29,
			)
		with self.assertRaisesRegex(frappe.ValidationError, "between 30 and 900"):
			self._queue(
				"authentication",
				"1ca5d748-27b2-4f5d-8f78-988948294c13",
				ttl_seconds=901,
			)
		client_id = "03a143fd-4f50-4f35-ae56-f106dc2c590d"
		queued = self._queue("utility", client_id, ttl_seconds=300)
		self.assertEqual(self._queue("utility", client_id, ttl_seconds=300).name, queued.name)
		with self.assertRaises(frappe.ValidationError):
			self._queue("utility", client_id, ttl_seconds=301)

	def test_business_named_template_is_utility_only_and_projects_provider_id(self):
		with self.assertRaisesRegex(frappe.ValidationError, "utility messages only"):
			self._queue(
				"authentication",
				"f9f28986-349a-4812-b271-b79917b01851",
				template_name="login_code",
			)
		with self.assertRaisesRegex(frappe.ValidationError, "lowercase"):
			self._queue(
				"utility",
				"f92aa55e-825d-4f68-a3da-690ca46efe6c",
				template_name="Order-Shipped",
			)
		client_id = "c20dc28b-cb24-455d-b864-99ea13a9d0c7"
		queued = self._queue(
			"utility",
			client_id,
			template_name="shipment_update",
		)
		self.assertEqual(
			self._queue(
				"utility",
				client_id,
				template_name="shipment_update",
			).name,
			queued.name,
		)
		with self.assertRaises(frappe.ValidationError):
			self._queue(
				"utility",
				client_id,
				template_name="different_name",
			)

		frappe.db.set_value(
			"WhatsApp Core Message",
			queued.name,
			"provider_message_id",
			"wamid.direct.named",
		)
		materialize_status(
			self.channel,
			{
				"id": "wamid.direct.named",
				"status": "delivered",
				"template_id": "987654321012345",
			},
		)
		message = frappe.get_doc("WhatsApp Core Message", queued.name)
		content = json.loads(message.content)
		self.assertEqual(content["direct_send_template_name"], "shipment_update")
		self.assertEqual(message.provider_template_id, "987654321012345")
		self.assertNotIn("provider_template_id", content)
		self.assertEqual(
			self._queue(
				"utility",
				client_id,
				template_name="shipment_update",
			).name,
			queued.name,
		)

	def test_utility_cta_media_header_is_durable_and_exact(self):
		interactive = {
			"type": "cta_url",
			"header": {
				"type": "image",
				"image": {
					"id": "MEDIA-IMAGE-1",
					"link": "https://cdn.example.com/invoice.png",
				},
			},
			"body": {"text": "Your invoice is ready"},
			"footer": {"text": "Available for 10 minutes"},
			"action": {
				"name": "cta_url",
				"parameters": {
					"display_text": "View invoice",
					"url": "https://billing.example.com/invoice/123",
				},
			},
		}
		queued = self._queue_interactive(
			interactive,
			"ea22a637-a3ee-4677-aaeb-02161d1239e2",
			ttl_seconds=600,
		)
		message = frappe.get_doc("WhatsApp Core Message", queued.name)
		payload = _message_payload(message, self.identity.normalized_value)
		self.assertEqual(payload["type"], "interactive")
		self.assertEqual(payload["interactive"], interactive)
		self.assertEqual(payload["category"], "utility")
		self.assertEqual(payload["ttl_seconds"], 600)

	def test_reply_buttons_accept_video_and_document_headers(self):
		for index, header in enumerate((
			{"type": "video", "video": {"link": "https://cdn.example.com/demo.mp4"}},
			{
				"type": "document",
				"document": {"id": "MEDIA-DOC-1", "filename": "invoice.pdf"},
			},
		)):
			with self.subTest(header=header["type"]):
				interactive = {
					"type": "button",
					"header": header,
					"body": {"text": "Confirm delivery"},
					"action": {
						"buttons": [
							{"type": "reply", "reply": {"id": "yes", "title": "Yes"}},
							{"type": "reply", "reply": {"id": "no", "title": "No"}},
						],
					},
				}
				queued = self._queue_interactive(
					interactive,
					f"00000000-0000-4000-8000-00000000000{index}",
				)
				message = frappe.get_doc("WhatsApp Core Message", queued.name)
				self.assertEqual(
					_message_payload(message, self.identity.normalized_value)["interactive"],
					interactive,
				)

	def test_direct_interactive_is_bounded_and_corruption_fails_closed(self):
		cta = {
			"type": "cta_url",
			"body": {"text": "Open your receipt"},
			"action": {
				"name": "cta_url",
				"parameters": {"display_text": "Open", "url": "https://example.com"},
			},
		}
		with self.assertRaisesRegex(frappe.ValidationError, "text messages only"):
			self._queue_interactive(
				cta,
				"52b60c89-af64-4e3a-b69c-b434b93e02b2",
				category="authentication",
			)
		for index, invalid in enumerate((
			{**cta, "unexpected": "field"},
			{
				**cta,
				"type": "CTA_URL",
			},
			{
				**cta,
				"action": {
					"name": "cta_url",
					"parameters": {
						"display_text": "Open",
						"url": " https://example.com",
					},
				},
			},
			{
				**cta,
				"action": {
					"name": "cta_url",
					"parameters": {"display_text": "Open", "url": "http://127.0.0.1/x"},
				},
			},
			{
				"type": "button",
				"body": {"text": "Choose an action"},
				"action": {
					"buttons": [
						{
							"type": "cta_url",
							"cta_url": {
								"display_text": "Open",
								"url": "https://example.com",
							},
						},
						{"type": "reply", "reply": {"id": "no", "title": "No"}},
					],
				},
			},
			{
				"type": "button",
				"body": {"text": "Choose an action"},
				"action": {
					"buttons": [
						{"type": "reply", "reply": {"id": "yes", "title": "Same"}},
						{"type": "reply", "reply": {"id": "no", "title": "Same"}},
					],
				},
			},
		)):
			with self.subTest(invalid=invalid):
				with self.assertRaises(frappe.ValidationError):
					self._queue_interactive(
						invalid,
						f"10000000-0000-4000-8000-00000000000{index}",
					)
		queued = self._queue_interactive(
			cta,
			"e4578fdc-d78d-42e4-8462-b4d043a0cc5c",
		)
		message = frappe.get_doc("WhatsApp Core Message", queued.name)
		content = json.loads(message.content)
		content["payload"]["action"]["parameters"]["url"] = "http://127.0.0.1/x"
		message.content = content
		message.save(ignore_permissions=True)
		with self.assertRaises(frappe.ValidationError):
			_message_payload(message, self.identity.normalized_value)

	def test_standard_text_still_requires_service_window_and_has_no_category(self):
		with (
			patch("frappe_whatsapp_core.outbound.outbound_ready", return_value=True),
			patch("frappe_whatsapp_core.outbound._run_preflight_hooks"),
		):
			with self.assertRaises(frappe.ValidationError):
				queue_text_internal(
					self.conversation.name,
					"ordinary text",
					enqueue_delivery=False,
				)
		self.conversation.last_inbound_at = now_datetime()
		self.conversation.save(ignore_permissions=True)
		with (
			patch("frappe_whatsapp_core.outbound.outbound_ready", return_value=True),
			patch("frappe_whatsapp_core.outbound._run_preflight_hooks"),
		):
			queued = queue_text_internal(
				self.conversation.name,
				"ordinary text",
				enqueue_delivery=False,
			)
		message = frappe.get_doc("WhatsApp Core Message", queued.name)
		self.assertNotIn(
			"category", _message_payload(message, self.identity.normalized_value)
		)
