from contextlib import nullcontext
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch

import frappe

from frappe_whatsapp_core.campaigns import _campaign_batch_sender
from frappe_whatsapp_core.hub_client import (
	connection_status,
	publish_outbound_command,
	send_batch,
)
from frappe_whatsapp_core.outbound import (
	deliver_queued_message,
	deliver_queued_message_batch,
	queue_campaign_batch,
	resolve_recipient_phone,
)


class TestBatchTransport(TestCase):
	def test_connection_status_exposes_only_fixed_hub_gateway(self):
		settings = SimpleNamespace(
			enabled=1,
			outbound_enabled=1,
			hub_url="https://hub.example.test",
			accounts=[],
			get_password=lambda fieldname, raise_exception=False: f"saved-{fieldname}",
		)
		with patch(
			"frappe_whatsapp_core.hub_client.frappe.get_single",
			return_value=settings,
		):
			result = connection_status()

		self.assertEqual(result["data_plane"], "hub_gateway")
		self.assertNotIn("relay_url", result)

	def test_single_delivery_ends_read_snapshot_before_status_write(self):
		message = frappe._dict(
			name="message-1",
			channel="channel-1",
			conversation="conversation-1",
			idempotency_key="key-1",
			delivery_status="Queued",
		)
		conversation = frappe._dict(name="conversation-1", remote_identity="identity-1")
		identity = frappe._dict(name="identity-1", normalized_value="919999999999")
		documents = {
			("WhatsApp Core Message", "message-1"): message,
			("WhatsApp Core Conversation", "conversation-1"): conversation,
			("WhatsApp Core Identity", "identity-1"): identity,
		}
		sequence = []
		with (
			patch("frappe_whatsapp_core.outbound.frappe.cache.lock", return_value=nullcontext()),
			patch(
				"frappe_whatsapp_core.outbound.frappe.get_doc",
				side_effect=lambda doctype, name: documents[(doctype, name)],
			),
			patch("frappe_whatsapp_core.outbound.resolve_recipient_phone", return_value="919999999999"),
			patch("frappe_whatsapp_core.outbound._message_payload", return_value={"to": "919999999999"}),
			patch(
				"frappe_whatsapp_core.outbound.send_raw",
				side_effect=lambda *args: sequence.append("send") or {
					"accepted": True,
					"status": "sent",
					"meta_message_id": "wamid.test",
				},
			),
			patch(
				"frappe_whatsapp_core.outbound.frappe.db.rollback",
				side_effect=lambda: sequence.append("rollback"),
			),
			patch(
				"frappe_whatsapp_core.outbound._mark_sent",
				side_effect=lambda *args: sequence.append("mark"),
			),
		):
			deliver_queued_message("message-1")

		self.assertEqual(sequence, ["send", "rollback", "mark"])

	def test_hub_batch_maps_channels_and_uses_one_request(self):
		settings = SimpleNamespace(
			hub_url="https://hub.example.test",
			request_timeout=30,
			get_hub_auth_headers=lambda: {"Authorization": "token test"},
			get_account_name=lambda channel: f"account:{channel}",
		)
		response = MagicMock(ok=True)
		response.json.return_value = {
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
		}
		with (
			patch(
				"frappe_whatsapp_core.outbound.outbound_ready",
				return_value=True,
			) as outbound_ready,
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
			post.call_args.args[0],
			"https://hub.example.test/api/method/"
			"frappe_whatsapp_hub.frappe_whatsapp_hub.api.gateway.outbound_batch",
		)
		self.assertEqual(
			post.call_args.kwargs["json"]["messages"][0]["account_name"],
			"account:channel-1",
		)

	def test_core_batch_uses_fixed_hub_gateway_method(self):
		settings = SimpleNamespace(
			hub_url="https://hub.example.test",
			request_timeout=30,
			get_hub_auth_headers=lambda: {
				"Authorization": "token core-key:core-secret"
			},
			get_account_name=lambda channel: f"account:{channel}",
		)
		response = MagicMock(ok=True)
		response.json.return_value = {
			"success": True,
			"queued": 1,
			"duplicates": 0,
			"items": [{"idempotency_key": "key-1", "status": "queued"}],
		}
		with (
			patch("frappe_whatsapp_core.hub_client.get_settings", return_value=settings),
			patch(
				"frappe_whatsapp_core.hub_client._session.post",
				return_value=response,
			) as post,
		):
			result = send_batch([{
				"channel": "channel-1",
				"payload": {"to": "911111111111"},
				"idempotency_key": "key-1",
			}])

		self.assertTrue(result["accepted"])
		self.assertEqual(
			post.call_args.args[0],
			"https://hub.example.test/api/method/"
			"frappe_whatsapp_hub.frappe_whatsapp_hub.api.gateway.outbound_batch",
		)

	def test_core_campaign_sender_defaults_to_batch_transport(self):
		with patch("frappe_whatsapp_core.campaigns.frappe.get_hooks", return_value=[]):
			self.assertIs(_campaign_batch_sender(), queue_campaign_batch)

	def test_management_publishes_one_runtime_command_to_go(self):
		settings = SimpleNamespace(
			hub_url="https://hub.example.test",
			request_timeout=30,
			get_hub_auth_headers=lambda: {"Authorization": "token core:secret"},
			get_account_name=lambda channel: f"account:{channel}",
		)
		response = MagicMock(ok=True, status_code=202)
		response.json.return_value = {
			"success": True, "command_id": "campaign-1", "queued": 1,
			"duplicates": 0, "total": 1,
		}
		with (
			patch("frappe_whatsapp_core.hub_client.get_settings", return_value=settings),
			patch("frappe_whatsapp_core.hub_client._session.post", return_value=response) as post,
		):
			result = publish_outbound_command(
				"campaign-1",
				[{"channel": "channel-1", "payload": {"to": "9876543210", "type": "text", "text": {"body": "hello"}}, "idempotency_key": "message-1"}],
				execute_at="2026-08-13T10:00:00+05:30",
			)
		self.assertTrue(result["accepted"])
		self.assertEqual(
			post.call_args.args[0],
			"https://hub.example.test/api/method/"
			"frappe_whatsapp_hub.frappe_whatsapp_hub.api.gateway.outbound_command",
		)
		self.assertEqual(post.call_args.kwargs["json"]["command_id"], "campaign-1")
		self.assertEqual(post.call_args.kwargs["json"]["execute_at"], "2026-08-13T10:00:00+05:30")

	def test_recipient_phone_defaults_to_core_identity(self):
		identity = SimpleNamespace(normalized_value="+91 98765 43210")
		with patch(
			"frappe_whatsapp_core.outbound.frappe.get_hooks",
			return_value=[],
		):
			self.assertEqual(resolve_recipient_phone(identity), "919876543210")

	def test_company_resolver_can_override_recipient_phone(self):
		identity = SimpleNamespace(
			name="identity-1",
			normalized_value="911111111111",
		)
		resolver = MagicMock(return_value={"phone_number": "+91 99999 88888"})
		with (
			patch(
				"frappe_whatsapp_core.outbound.frappe.get_hooks",
				return_value=["company.resolve_phone"],
			),
			patch(
				"frappe_whatsapp_core.outbound.frappe.get_attr",
				return_value=resolver,
			),
		):
			phone = resolve_recipient_phone(identity, {"source": "message"})

		self.assertEqual(phone, "919999988888")
		resolver.assert_called_once_with(
			identity=identity,
			context={"source": "message"},
		)

	def test_campaign_batch_defers_transport_until_after_commit(self):
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

		with (
			patch(
				"frappe_whatsapp_core.outbound.outbound_ready",
				return_value=True,
			) as outbound_ready,
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
				"frappe_whatsapp_core.outbound.resolve_recipient_phone",
				side_effect=[
					"919999999990",
					"919999999991",
				],
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
			) as hub_batch,
			patch("frappe_whatsapp_core.outbound.frappe.db.sql") as db_sql,
			patch("frappe_whatsapp_core.outbound.frappe.publish_realtime") as publish,
			patch("frappe_whatsapp_core.outbound.frappe.enqueue") as enqueue,
		):
			result = queue_campaign_batch(campaign, recipients)

		hub_batch.assert_not_called()
		outbound_ready.assert_called_once_with(channel.name)
		enqueue.assert_called_once_with(
			"frappe_whatsapp_core.outbound.deliver_queued_message_batch",
			queue="short",
			enqueue_after_commit=True,
			message_names=["message-0", "message-1"],
		)
		self.assertTrue(all(row["success"] for row in result.values()))
		db_sql.assert_called_once()
		publish.assert_called_once()
		self.assertEqual(publish.call_args.args[1], {"changed": True})

	def test_campaign_batch_never_converts_deadlock_to_recipient_failure(self):
		campaign = SimpleNamespace(
			name="campaign-deadlock",
			channel="channel-1",
			template="template-1",
		)
		recipient = SimpleNamespace(
			name="recipient-deadlock",
			identity="identity-deadlock",
			personalization="{}",
		)
		with (
			patch("frappe_whatsapp_core.outbound.outbound_ready", return_value=True),
			patch(
				"frappe_whatsapp_core.outbound.frappe.get_cached_doc",
				side_effect=[
					SimpleNamespace(name="channel-1"),
					SimpleNamespace(name="template-1", language_code="en"),
					SimpleNamespace(name="identity-deadlock"),
				],
			),
			patch(
				"frappe_whatsapp_core.outbound.get_or_create_conversation",
				side_effect=frappe.QueryDeadlockError("deadlock"),
			),
			patch("frappe_whatsapp_core.outbound.frappe.enqueue") as enqueue,
		):
			with self.assertRaises(frappe.QueryDeadlockError):
				queue_campaign_batch(campaign, [recipient])

		enqueue.assert_not_called()

	def test_committed_campaign_batch_submits_all_messages_together(self):
		messages = {
			f"message-{index}": frappe._dict(
				name=f"message-{index}",
				channel="channel-1",
				conversation=f"conversation-{index}",
				idempotency_key=f"key-{index}",
				delivery_status="Queued",
			)
			for index in range(2)
		}
		conversations = {
			f"conversation-{index}": frappe._dict(
				name=f"conversation-{index}",
				remote_identity=f"identity-{index}",
			)
			for index in range(2)
		}
		identities = {
			f"identity-{index}": frappe._dict(
				name=f"identity-{index}",
				normalized_value=f"91999999999{index}",
			)
			for index in range(2)
		}

		def get_doc(doctype, name):
			return {
				"WhatsApp Core Message": messages,
				"WhatsApp Core Conversation": conversations,
				"WhatsApp Core Identity": identities,
			}[doctype][name]

		hub_response = {
			"accepted": True,
			"items": [
				{
					"idempotency_key": f"key-{index}",
					"status": "queued",
					"result": {"success": True, "status": "queued"},
				}
				for index in range(2)
			],
		}
		with (
			patch(
				"frappe_whatsapp_core.outbound.frappe.get_doc",
				side_effect=get_doc,
			),
			patch(
				"frappe_whatsapp_core.outbound.resolve_recipient_phone",
				side_effect=["919999999990", "919999999991"],
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
			patch("frappe_whatsapp_core.outbound.frappe.db.rollback") as rollback,
		):
			deliver_queued_message_batch(list(messages))

		self.assertEqual(hub_batch.call_count, 1)
		self.assertEqual(len(hub_batch.call_args.args[0]), 2)
		self.assertEqual(rollback.call_count, 2)

	def test_missing_message_does_not_abort_other_committed_batch_items(self):
		message = frappe._dict(
			name="message-valid",
			channel="channel-1",
			conversation="conversation-1",
			idempotency_key="key-valid",
			delivery_status="Queued",
		)
		conversation = frappe._dict(name="conversation-1", remote_identity="identity-1")
		identity = frappe._dict(name="identity-1", normalized_value="919999999999")

		def get_doc(doctype, name):
			if doctype == "WhatsApp Core Message" and name == "message-missing":
				raise frappe.DoesNotExistError
			return {
				("WhatsApp Core Message", "message-valid"): message,
				("WhatsApp Core Conversation", "conversation-1"): conversation,
				("WhatsApp Core Identity", "identity-1"): identity,
			}[(doctype, name)]

		with (
			patch("frappe_whatsapp_core.outbound.frappe.get_doc", side_effect=get_doc),
			patch("frappe_whatsapp_core.outbound.resolve_recipient_phone", return_value="919999999999"),
			patch("frappe_whatsapp_core.outbound._message_payload", return_value={"to": "919999999999"}),
			patch(
				"frappe_whatsapp_core.outbound.send_hub_batch",
				return_value={
					"accepted": True,
					"items": [{
						"idempotency_key": "key-valid",
						"status": "queued",
						"result": {"success": True, "status": "queued"},
					}],
				},
			) as hub_batch,
			patch("frappe_whatsapp_core.outbound.frappe.db.rollback"),
			patch("frappe_whatsapp_core.outbound.frappe.logger") as logger,
		):
			deliver_queued_message_batch(["message-missing", "message-valid"])

		hub_batch.assert_called_once()
		self.assertEqual(len(hub_batch.call_args.args[0]), 1)
		logger.return_value.warning.assert_called_once()

	def test_invalid_campaign_recipient_fails_before_message_creation(self):
		campaign = SimpleNamespace(
			name="campaign-invalid-recipient",
			channel="channel-1",
			template="template-1",
		)
		recipient = SimpleNamespace(
			name="recipient-invalid",
			identity="identity-invalid",
			personalization="{}",
		)
		channel = SimpleNamespace(name="channel-1")
		template = SimpleNamespace(name="template-1", language_code="en")
		identity = SimpleNamespace(name="identity-invalid")
		conversation = SimpleNamespace(name="conversation-invalid")
		with (
			patch("frappe_whatsapp_core.outbound.outbound_ready", return_value=True),
			patch(
				"frappe_whatsapp_core.outbound.frappe.get_cached_doc",
				side_effect=[channel, template, identity],
			),
			patch(
				"frappe_whatsapp_core.outbound.get_or_create_conversation",
				return_value=conversation,
			),
			patch(
				"frappe_whatsapp_core.outbound.resolve_recipient_phone",
				side_effect=frappe.ValidationError("invalid recipient"),
			),
			patch(
				"frappe_whatsapp_core.outbound.queue_template_internal",
			) as queue_template,
			patch("frappe_whatsapp_core.outbound.frappe.enqueue") as enqueue,
		):
			result = queue_campaign_batch(campaign, [recipient])

		self.assertFalse(result[recipient.name]["success"])
		queue_template.assert_not_called()
		enqueue.assert_not_called()
