from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from frappe_whatsapp_core.api import receive_outbound_result
from frappe_whatsapp_core.campaigns import (
	_complete_campaign,
	_lock_campaign_rows,
	authorize_campaign,
	cancel_campaign,
	create_campaign,
	launch_campaign,
	prepare_campaign,
	process_campaign_batch,
)
from frappe_whatsapp_core.materializer import materialize_status
from frappe_whatsapp_core.outbound import queue_campaign_recipient, retry_queued_messages
from frappe_whatsapp_core.template_catalog import sync_template_projection


def blocked_campaign_preflight(_context):
	return {"ready": False, "reasons": ["Test business gate is locked"]}


class TestCampaigns(FrappeTestCase):
	def setUp(self):
		super().setUp()
		suffix = frappe.generate_hash(length=8).lower()
		self.channel = frappe.get_doc({
			"doctype": "WhatsApp Core Channel",
			"channel_key": f"meta:campaign-{suffix}",
			"display_name": "Campaign Test",
			"provider": "meta",
			"phone_number_id": f"campaign-{suffix}",
			"enabled": 1,
		}).insert(ignore_permissions=True)
		self.identities = [
			frappe.get_doc({
				"doctype": "WhatsApp Core Identity",
				"identity_key": f"campaign-identity-{suffix}-{index}",
				"identity_type": "WhatsApp",
				"normalized_value": f"91990000{suffix[:4]}{index}",
				"display_value": f"91990000{suffix[:4]}{index}",
				"provider": "meta",
				"status": "Active",
			}).insert(ignore_permissions=True)
			for index in range(2)
		]
		self.template = sync_template_projection({
			"name": f"campaign_template_{suffix}",
			"language": "en",
			"status": "APPROVED",
			"category": "UTILITY",
			"components": [{
				"type": "BODY",
				"text": "Hello {{1}}",
			}],
		})["name"]
		self.campaign = create_campaign(
			campaign_key=f"campaign.test.{suffix}",
			title="Campaign test",
			channel=self.channel.name,
			template=self.template,
			audience_source={"provider": "test"},
		)

	def test_template_projection_extracts_copy(self):
		template = frappe.get_doc("WhatsApp Core Template", self.template)
		self.assertEqual(template.approval_status, "APPROVED")
		self.assertEqual(template.body_text, "Hello {{1}}")
		self.assertTrue(template.enabled)

	def test_template_projection_notifies_open_core_sessions(self):
		with patch("frappe_whatsapp_core.template_catalog.frappe.publish_realtime") as publish:
			result = sync_template_projection({
				"name": f"realtime_{frappe.generate_hash(length=8).lower()}",
				"language": "en",
				"status": "APPROVED",
			})
		publish.assert_any_call(
			"whatsapp_core_template",
			{"template": result["name"]},
			after_commit=True,
		)

	def test_prepare_is_exact_and_deduplicated(self):
		with patch("frappe_whatsapp_core.campaigns.frappe.publish_realtime") as publish:
			summary = prepare_campaign(
				self.campaign.name,
				[
					{
						"identity": self.identities[0].name,
						"personalization": {"components": []},
					},
					self.identities[0].name,
					self.identities[1].name,
				],
			)
		publish.assert_called_with(
			"whatsapp_core_campaign",
			{"campaign": self.campaign.name, "status": "Prepared", "counts": {}},
			after_commit=True,
		)
		self.assertEqual(summary["status"], "Prepared")
		self.assertEqual(summary["recipient_count"], 2)
		self.assertEqual(
			frappe.db.count(
				"WhatsApp Core Campaign Recipient",
				{"campaign": self.campaign.name},
			),
			2,
		)

	def test_send_authorization_is_separate_and_explicit(self):
		prepare_campaign(
			self.campaign.name,
			[self.identities[0].name],
		)
		with self.assertRaises(frappe.ValidationError):
			authorize_campaign(self.campaign.name, "yes")

		summary = authorize_campaign(
			self.campaign.name,
			f"AUTHORIZE {self.campaign.campaign_key}",
		)
		self.assertTrue(summary["send_authorized"])
		self.assertEqual(summary["template_approval_status"], "APPROVED")

	def test_plain_text_campaign_uses_service_window_guarded_sender(self):
		campaign = create_campaign(
			campaign_key=f"campaign.text.{frappe.generate_hash(length=8).lower()}",
			title="Open-window follow-up",
			channel=self.channel.name,
			content_type="Text",
			message_text="Hello from the service team",
		)
		prepare_campaign(campaign.name, [self.identities[0].name])
		summary = authorize_campaign(campaign.name, f"AUTHORIZE {campaign.campaign_key}")
		self.assertEqual(summary["content_type"], "Text")
		self.assertEqual(summary["template_approval_status"], "NOT_REQUIRED")

		recipient = frappe.get_doc(
			"WhatsApp Core Campaign Recipient",
			{"campaign": campaign.name},
		)
		with (
			patch(
				"frappe_whatsapp_core.outbound.get_or_create_conversation",
				return_value=SimpleNamespace(name="TEXT-CONVERSATION"),
			),
			patch(
				"frappe_whatsapp_core.outbound.queue_text_internal",
				return_value=SimpleNamespace(name="TEXT-MESSAGE"),
			) as queue_text,
		):
			result = queue_campaign_recipient(campaign, recipient)
		self.assertEqual(result["message"], "TEXT-MESSAGE")
		queue_text.assert_called_once_with(
			"TEXT-CONVERSATION",
			"Hello from the service team",
			source=f"Campaign:{campaign.name}",
		)

	def test_business_preflight_blocks_launch_while_gate_is_locked(self):
		prepare_campaign(
			self.campaign.name,
			[self.identities[0].name],
		)
		authorize_campaign(
			self.campaign.name,
			f"AUTHORIZE {self.campaign.campaign_key}",
		)
		with patch(
			"frappe_whatsapp_core.campaigns.frappe.get_hooks",
			return_value=[
				"frappe_whatsapp_core.tests.test_campaigns.blocked_campaign_preflight"
			],
		):
			with self.assertRaises(frappe.ValidationError):
				launch_campaign(self.campaign.name)
		self.assertEqual(
			frappe.db.get_value(
				"WhatsApp Core Campaign",
				self.campaign.name,
				"status",
			),
			"Prepared",
		)

	def test_campaign_worker_never_exceeds_relay_batch_limit(self):
		self.campaign.status = "Running"
		self.campaign.save(ignore_permissions=True)
		with (
			patch("frappe_whatsapp_core.campaigns._campaign_batch_sender", return_value=object()),
			patch("frappe_whatsapp_core.campaigns.frappe.get_all", return_value=[]) as get_all,
			patch("frappe_whatsapp_core.campaigns._complete_campaign"),
		):
			process_campaign_batch(self.campaign.name, batch_size=500)
		self.assertEqual(get_all.call_args.kwargs["limit_page_length"], 40)

	def test_campaign_locks_are_sorted_before_recipient_updates(self):
		with patch("frappe_whatsapp_core.campaigns.frappe.db.sql") as sql:
			_lock_campaign_rows(["campaign.z", "campaign.a", "campaign.z", None])
		query, values = sql.call_args.args
		self.assertIn("FOR UPDATE", query)
		self.assertEqual(values["campaign_names"], ["campaign.a", "campaign.z"])

	def test_campaign_completion_does_not_run_hot_path_full_reconciliation(self):
		self.campaign.status = "Running"
		self.campaign.save(ignore_permissions=True)
		with patch("frappe_whatsapp_core.campaigns.refresh_campaign_counts") as refresh:
			_complete_campaign(self.campaign)
		refresh.assert_not_called()
		self.assertEqual(
			frappe.db.get_value("WhatsApp Core Campaign", self.campaign.name, "status"),
			"Completed",
		)

	def test_provider_failure_reconciles_campaign_immediately(self):
		prepare_campaign(self.campaign.name, [self.identities[0].name])
		recipient = frappe.get_doc(
			"WhatsApp Core Campaign Recipient",
			{"campaign": self.campaign.name},
		)
		conversation = frappe.get_doc({
			"doctype": "WhatsApp Core Conversation",
			"conversation_key": f"campaign-conversation-{frappe.generate_hash(length=8)}",
			"channel": self.channel.name,
			"remote_identity": self.identities[0].name,
			"status": "Open",
			"last_message_at": frappe.utils.now_datetime(),
		}).insert(ignore_permissions=True)
		message = frappe.get_doc({
			"doctype": "WhatsApp Core Message",
			"message_key": f"campaign-message-{frappe.generate_hash(length=8)}",
			"idempotency_key": f"campaign-result-{frappe.generate_hash(length=8)}",
			"conversation": conversation.name,
			"channel": self.channel.name,
			"provider_message_id": f"local:{frappe.generate_hash(length=8)}",
			"direction": "Outbound",
			"message_type": "template",
			"body": "Campaign test",
			"content": "{}",
			"provider_timestamp": frappe.utils.now_datetime(),
			"delivery_status": "Queued",
		}).insert(ignore_permissions=True)
		frappe.db.set_value(
			"WhatsApp Core Campaign Recipient",
			recipient.name,
			{"status": "Queued", "core_message": message.name},
			update_modified=False,
		)

		receive_outbound_result(
			message.idempotency_key,
			"failed",
			success=0,
			error="Provider rejected test recipient",
		)

		self.assertEqual(
			frappe.db.get_value(
				"WhatsApp Core Campaign Recipient", recipient.name, "status"
			),
			"Failed",
		)
		self.assertEqual(
			frappe.db.get_value(
				"WhatsApp Core Campaign", self.campaign.name, "failed_count"
			),
			1,
		)

		# Delivery/read webhooks must reconcile the same campaign immediately,
		# not wait for the five-minute repair scheduler.
		frappe.db.set_value(
			"WhatsApp Core Message",
			message.name,
			{
				"delivery_status": "Sent",
				"provider_message_id": f"wamid.{frappe.generate_hash(length=8)}",
			},
			update_modified=False,
		)
		frappe.db.set_value(
			"WhatsApp Core Campaign Recipient",
			recipient.name,
			{"status": "Sent", "completed_at": None},
			update_modified=False,
		)
		materialize_status(
			self.channel,
			{
				"id": frappe.db.get_value(
					"WhatsApp Core Message", message.name, "provider_message_id"
				),
				"status": "delivered",
			},
		)
		self.assertEqual(
			frappe.db.get_value(
				"WhatsApp Core Campaign Recipient", recipient.name, "status"
			),
			"Delivered",
		)

	def test_cancelled_campaign_messages_are_terminal_and_never_retried(self):
		prepare_campaign(self.campaign.name, [self.identities[0].name])
		recipient = frappe.get_doc(
			"WhatsApp Core Campaign Recipient",
			{"campaign": self.campaign.name},
		)
		conversation = frappe.get_doc({
			"doctype": "WhatsApp Core Conversation",
			"conversation_key": f"cancel-conversation-{frappe.generate_hash(length=8)}",
			"channel": self.channel.name,
			"remote_identity": self.identities[0].name,
			"status": "Open",
			"last_message_at": frappe.utils.now_datetime(),
		}).insert(ignore_permissions=True)
		message = frappe.get_doc({
			"doctype": "WhatsApp Core Message",
			"message_key": f"cancel-message-{frappe.generate_hash(length=8)}",
			"idempotency_key": f"cancel-result-{frappe.generate_hash(length=8)}",
			"conversation": conversation.name,
			"channel": self.channel.name,
			"provider_message_id": f"local:{frappe.generate_hash(length=8)}",
			"direction": "Outbound",
			"message_type": "template",
			"body": "Cancelled campaign test",
			"content": "{}",
			"provider_timestamp": frappe.utils.now_datetime(),
			"delivery_status": "Queued",
		}).insert(ignore_permissions=True)
		frappe.db.set_value(
			"WhatsApp Core Campaign Recipient",
			recipient.name,
			{"status": "Queued", "core_message": message.name},
			update_modified=False,
		)

		cancel_campaign(self.campaign.name)

		self.assertEqual(
			frappe.db.get_value("WhatsApp Core Message", message.name, "delivery_status"),
			"Failed",
		)
		self.assertEqual(
			frappe.db.get_value(
				"WhatsApp Core Campaign Recipient", recipient.name, "status"
			),
			"Skipped",
		)
		# Defence in depth: even a stale/externally-reset queued row from a
		# cancelled campaign must not be selected by the global retry scheduler.
		frappe.db.set_value(
			"WhatsApp Core Message",
			message.name,
			{"delivery_status": "Queued", "modified": "2000-01-01 00:00:00"},
			update_modified=False,
		)
		with patch("frappe_whatsapp_core.outbound.frappe.enqueue") as enqueue:
			retry_queued_messages()
		retried_messages = {
			call.kwargs.get("message_name") for call in enqueue.call_args_list
		}
		self.assertNotIn(message.name, retried_messages)
