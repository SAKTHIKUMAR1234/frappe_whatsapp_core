from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch

import frappe

from frappe_whatsapp_core.campaigns import _campaign_batch_sender
from frappe_whatsapp_core.hub_client import send_batch
from frappe_whatsapp_core.outbound import queue_campaign_batch


class TestBatchTransport(TestCase):
	def test_hub_batch_maps_channels_and_uses_one_request(self):
		settings = SimpleNamespace(
			hub_url="https://hub.example.test",
			request_timeout=30,
			get_hub_auth_headers=lambda: {"Authorization": "token test"},
			get_account_name=lambda channel: f"account:{channel}",
		)
		response = MagicMock(ok=True)
		response.json.return_value = {
			"message": {
				"success": True,
				"queued": 2,
				"items": [
					{
						"idempotency_key": "key-1",
						"status": "completed",
						"result": {"success": True},
					},
					{
						"idempotency_key": "key-2",
						"status": "completed",
						"result": {"success": True},
					},
				],
			},
		}
		with (
			patch(
				"frappe_whatsapp_core.hub_client.get_settings",
				return_value=settings,
			),
			patch(
				"frappe_whatsapp_core.hub_client._session.post",
				return_value=response,
			) as post,
		):
			result = send_batch([
				{
					"channel": "channel-1",
					"payload": {"to": "911111111111"},
					"idempotency_key": "key-1",
				},
				{
					"channel": "channel-2",
					"payload": {"to": "922222222222"},
					"idempotency_key": "key-2",
				},
			])

		self.assertTrue(result["accepted"])
		self.assertEqual(post.call_count, 1)
		self.assertEqual(
			post.call_args.kwargs["json"]["messages"][0]["account_name"],
			"account:channel-1",
		)

	def test_core_campaign_sender_defaults_to_batch_transport(self):
		with patch("frappe_whatsapp_core.campaigns.frappe.get_hooks", return_value=[]):
			self.assertIs(_campaign_batch_sender(), queue_campaign_batch)

	def test_campaign_batch_submits_all_messages_together(self):
		campaign = SimpleNamespace(
			name="campaign-1",
			channel="channel-1",
			template="template-1",
		)
		recipients = [
			SimpleNamespace(
				name=f"recipient-{index}",
				identity=f"identity-{index}",
				personalization="{}",
			)
			for index in range(2)
		]
		channel = SimpleNamespace(name="channel-1")
		template = SimpleNamespace(name="template-1", language_code="en")
		identities = {
			f"identity-{index}": SimpleNamespace(
				name=f"identity-{index}",
				normalized_value=f"91999999999{index}",
			)
			for index in range(2)
		}
		messages = [
			frappe._dict(
				name=f"message-{index}",
				channel="channel-1",
				conversation=f"conversation-{index}",
				idempotency_key=f"key-{index}",
			)
			for index in range(2)
		]

		def cached_doc(doctype, name):
			if doctype == "WhatsApp Core Channel":
				return channel
			if doctype == "WhatsApp Core Template":
				return template
			return identities[name]

		hub_response = {
			"accepted": True,
			"success": True,
			"items": [
				{
					"idempotency_key": f"key-{index}",
					"status": "completed",
					"result": {
						"success": True,
						"meta_message_id": f"wamid.{index}",
					},
				}
				for index in range(2)
			],
		}
		with (
			patch(
				"frappe_whatsapp_core.outbound.frappe.get_cached_doc",
				side_effect=cached_doc,
			),
			patch(
				"frappe_whatsapp_core.outbound.get_or_create_conversation",
				side_effect=[
					SimpleNamespace(name="conversation-0"),
					SimpleNamespace(name="conversation-1"),
				],
			),
			patch(
				"frappe_whatsapp_core.outbound.queue_template_internal",
				side_effect=messages,
			),
			patch(
				"frappe_whatsapp_core.outbound._message_payload",
				side_effect=[
					{"to": "919999999990"},
					{"to": "919999999991"},
				],
			),
			patch(
				"frappe_whatsapp_core.outbound.send_hub_batch",
				return_value=hub_response,
			) as hub_batch,
			patch(
				"frappe_whatsapp_core.outbound.frappe.get_doc",
				side_effect=messages,
			),
			patch("frappe_whatsapp_core.outbound._mark_sent") as mark_sent,
		):
			result = queue_campaign_batch(campaign, recipients)

		self.assertEqual(hub_batch.call_count, 1)
		self.assertEqual(len(hub_batch.call_args.args[0]), 2)
		self.assertEqual(mark_sent.call_count, 2)
		self.assertTrue(all(row["success"] for row in result.values()))
