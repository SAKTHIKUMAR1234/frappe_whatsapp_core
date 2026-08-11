import json

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import now_datetime

from frappe_whatsapp_core.consent import is_opt_out_event, suppress_conversation
from frappe_whatsapp_core.materializer import (
	get_or_create_channel,
	get_or_create_conversation,
	get_or_create_identity,
)
from frappe_whatsapp_core.outbound import resolve_recipient_phone


class TestConsentControls(FrappeTestCase):
	def setUp(self):
		suffix = frappe.generate_hash(length=10)
		self.channel = get_or_create_channel(f"consent-{suffix}")
		number_suffix = now_datetime().strftime("%H%M%S%f")[-8:]
		self.identity = get_or_create_identity(f"9195{number_suffix}")
		self.conversation = get_or_create_conversation(self.channel, self.identity)

	def test_stop_is_exact_and_case_insensitive(self):
		self.assertTrue(is_opt_out_event({"body": " STOP "}))
		self.assertTrue(is_opt_out_event({"interactive_id": "/stop"}))
		self.assertFalse(is_opt_out_event({"body": "please stop later"}))

	def test_stop_blocks_identity_and_cancels_queued_work(self):
		message_key = frappe.generate_hash(length=40)
		message = frappe.get_doc({
			"doctype": "WhatsApp Core Message",
			"message_key": message_key,
			"idempotency_key": message_key,
			"conversation": self.conversation.name,
			"channel": self.channel.name,
			"provider_message_id": f"local:{message_key}",
			"direction": "Outbound",
			"message_type": "text",
			"body": "Pending",
			"content": "{}",
			"provider_timestamp": now_datetime(),
			"delivery_status": "Queued",
		}).insert(ignore_permissions=True)
		campaign = frappe.get_doc({
			"doctype": "WhatsApp Core Campaign",
			"campaign_key": f"consent-{message_key}",
			"title": "Consent test",
			"channel": self.channel.name,
			"content_type": "Text",
			"message_text": "Hello",
			"status": "Prepared",
		}).insert(ignore_permissions=True)
		recipient = frappe.get_doc({
			"doctype": "WhatsApp Core Campaign Recipient",
			"recipient_key": frappe.generate_hash(length=40),
			"campaign": campaign.name,
			"identity": self.identity.name,
			"status": "Queued",
			"personalization": "{}",
			"core_message": message.name,
		}).insert(ignore_permissions=True)

		result = suppress_conversation(self.conversation.name, "event:stop")

		self.assertEqual(result["status"], "blocked")
		self.assertEqual(
			frappe.db.get_value("WhatsApp Core Identity", self.identity.name, "status"),
			"Blocked",
		)
		self.assertEqual(
			frappe.db.get_value("WhatsApp Core Message", message.name, "delivery_status"),
			"Failed",
		)
		self.assertEqual(
			frappe.db.get_value("WhatsApp Core Campaign Recipient", recipient.name, "status"),
			"Skipped",
		)
		attributes = json.loads(
			frappe.db.get_value("WhatsApp Core Identity", self.identity.name, "attributes")
		)
		self.assertEqual(attributes["consent"]["status"], "Opted Out")
		with self.assertRaises(frappe.ValidationError):
			resolve_recipient_phone(self.identity.name)
