import json
import uuid
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from frappe_whatsapp_core.legacy_compat import (
	legacy_template_components,
	queue_interactive_by_phone,
	queue_media_by_phone,
	queue_template_by_phone,
	queue_text_by_phone,
)
from frappe_whatsapp_core.template_catalog import scoped_template_key


class TestLegacyCompatibility(FrappeTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		suffix = frappe.generate_hash(length=8).lower()
		self.phone_number_id = f"compat-phone-{suffix}"
		self.channel = frappe.get_doc({
			"doctype": "WhatsApp Core Channel",
			"channel_key": f"meta:{self.phone_number_id}",
			"display_name": "Compatibility test",
			"provider": "meta",
			"phone_number_id": self.phone_number_id,
			"enabled": 1,
		}).insert(ignore_permissions=True)
		self.account = f"compat-account-{suffix}"
		settings = frappe.get_single("WhatsApp Core Settings")
		settings.set("accounts", [{
			"channel": self.channel.name,
			"account_name": self.account,
			"is_default": 1,
		}])
		settings.save(ignore_permissions=True)
		self.phone = f"91{int(suffix, 36) % 10_000_000_000:010d}"

	def test_text_creates_only_a_core_message(self):
		with (
			patch("frappe_whatsapp_core.outbound.outbound_ready", return_value=True),
			patch("frappe_whatsapp_core.outbound._within_service_window", return_value=True),
		):
			message = queue_text_by_phone(
				self.phone,
				"Core cutover proof",
				phone_number_id=self.phone_number_id,
				enqueue_delivery=False,
			)
		self.assertEqual(message.delivery_status, "Queued")
		self.assertEqual(message.message_type, "text")
		self.assertEqual(message.body, "Core cutover proof")

	def test_template_converts_legacy_variables(self):
		template_name = f"compat_{frappe.generate_hash(length=6).lower()}"
		frappe.get_doc({
			"doctype": "WhatsApp Core Template",
			"template_key": scoped_template_key(self.account, template_name, "en"),
			"account_name": self.account,
			"channel": self.channel.name,
			"template_name": template_name,
			"language_code": "en",
			"approval_status": "APPROVED",
			"enabled": 1,
			"body_text": "Hello {{1}}",
		}).insert(ignore_permissions=True)
		with (
			patch("frappe_whatsapp_core.outbound.outbound_ready", return_value=True),
			patch("frappe_whatsapp_core.outbound._within_service_window", return_value=True),
		):
			message = queue_template_by_phone(
				self.phone,
				template_name,
				variables={"body": ["Member"]},
				phone_number_id=self.phone_number_id,
				enqueue_delivery=False,
			)
		content = json.loads(message.content)
		self.assertEqual(message.message_type, "template")
		self.assertEqual(message.body, "Hello Member")
		self.assertEqual(
			content["components"][0]["parameters"][0],
				{"type": "text", "text": "Member"},
			)

	def test_template_retry_returns_existing_message_without_duplicate_delivery(self):
		template_name = f"retry_{frappe.generate_hash(length=6).lower()}"
		frappe.get_doc({
			"doctype": "WhatsApp Core Template",
			"template_key": scoped_template_key(self.account, template_name, "en"),
			"account_name": self.account,
			"channel": self.channel.name,
			"template_name": template_name,
			"language_code": "en",
			"approval_status": "APPROVED",
			"enabled": 1,
			"body_text": "Retry hello {{1}}",
		}).insert(ignore_permissions=True)
		client_message_id = str(uuid.uuid4())
		with (
			patch("frappe_whatsapp_core.outbound.outbound_ready", return_value=True),
			patch("frappe_whatsapp_core.outbound._enqueue_message_delivery") as enqueue,
		):
			first = queue_template_by_phone(
				self.phone,
				template_name,
				variables={"body": ["Member"]},
				phone_number_id=self.phone_number_id,
				client_message_id=client_message_id,
			)
			replayed = queue_template_by_phone(
				self.phone,
				template_name,
				variables={"body": ["Member"]},
				phone_number_id=self.phone_number_id,
				client_message_id=client_message_id,
			)

		self.assertEqual(replayed.name, first.name)
		self.assertEqual(replayed.conversation, first.conversation)
		self.assertEqual(replayed.provider_message_id, f"local:{client_message_id}")
		self.assertIn("sender_name", replayed)
		self.assertEqual(
			frappe.db.count(
				"WhatsApp Core Message",
				{"provider_message_id": f"local:{client_message_id}"},
			),
			1,
		)
		enqueue.assert_called_once_with(first.name)

	def test_client_message_id_reuse_with_changed_payload_or_type_fails_closed(self):
		template_name = f"conflict_{frappe.generate_hash(length=6).lower()}"
		frappe.get_doc({
			"doctype": "WhatsApp Core Template",
			"template_key": scoped_template_key(self.account, template_name, "en"),
			"account_name": self.account,
			"channel": self.channel.name,
			"template_name": template_name,
			"language_code": "en",
			"approval_status": "APPROVED",
			"enabled": 1,
			"body_text": "Conflict hello {{1}}",
		}).insert(ignore_permissions=True)
		client_message_id = str(uuid.uuid4())
		with patch("frappe_whatsapp_core.outbound.outbound_ready", return_value=True):
			queue_template_by_phone(
				self.phone,
				template_name,
				variables={"body": ["Original"]},
				phone_number_id=self.phone_number_id,
				client_message_id=client_message_id,
				enqueue_delivery=False,
			)
			with self.assertRaises(frappe.ValidationError):
				queue_template_by_phone(
					self.phone,
					template_name,
					variables={"body": ["Changed"]},
					phone_number_id=self.phone_number_id,
					client_message_id=client_message_id,
					enqueue_delivery=False,
				)
			with self.assertRaises(frappe.ValidationError):
				queue_text_by_phone(
					self.phone,
					"Changed type",
					phone_number_id=self.phone_number_id,
					client_message_id=client_message_id,
					enqueue_delivery=False,
				)
			with self.assertRaises(frappe.ValidationError):
				queue_template_by_phone(
					f"92{self.phone[2:]}",
					template_name,
					variables={"body": ["Original"]},
					phone_number_id=self.phone_number_id,
					client_message_id=client_message_id,
					enqueue_delivery=False,
				)

	def test_duplicate_insert_race_returns_exact_existing_winner(self):
		client_message_id = str(uuid.uuid4())
		with (
			patch("frappe_whatsapp_core.outbound.outbound_ready", return_value=True),
			patch("frappe_whatsapp_core.outbound._within_service_window", return_value=True),
		):
			winner = queue_text_by_phone(
				self.phone,
				"Race-safe text",
				phone_number_id=self.phone_number_id,
				client_message_id=client_message_id,
				enqueue_delivery=False,
			)
		winner_doc = frappe.get_doc("WhatsApp Core Message", winner.name)
		with (
			patch("frappe_whatsapp_core.outbound.outbound_ready", return_value=True),
			patch("frappe_whatsapp_core.outbound._within_service_window", return_value=True),
			patch(
				"frappe_whatsapp_core.outbound._message_by_client_id",
				side_effect=[None, winner_doc],
			) as lookup,
			patch(
				"frappe.model.document.Document.insert",
				side_effect=frappe.DuplicateEntryError("concurrent insert"),
			),
			patch("frappe_whatsapp_core.outbound._enqueue_message_delivery") as enqueue,
		):
			replayed = queue_text_by_phone(
				self.phone,
				"Race-safe text",
				phone_number_id=self.phone_number_id,
				client_message_id=client_message_id,
			)

		self.assertEqual(replayed.name, winner.name)
		self.assertEqual(
			lookup.call_args_list[-1].kwargs,
			{"channel": self.channel.name, "for_update": True},
		)
		enqueue.assert_not_called()

	def test_media_and_interactive_create_core_messages(self):
		with (
			patch("frappe_whatsapp_core.outbound.outbound_ready", return_value=True),
			patch("frappe_whatsapp_core.outbound._within_service_window", return_value=True),
		):
			media = queue_media_by_phone(
				self.phone,
				"document",
				media_url="https://example.invalid/proof.pdf",
				filename="proof.pdf",
				phone_number_id=self.phone_number_id,
				enqueue_delivery=False,
			)
			interactive = queue_interactive_by_phone(
				self.phone,
				"button",
				"Choose",
				buttons=[{"id": "yes", "title": "Yes"}],
				phone_number_id=self.phone_number_id,
				enqueue_delivery=False,
			)
		self.assertEqual(media.message_type, "document")
		self.assertEqual(interactive.message_type, "interactive")

	def test_local_template_document_is_uploaded_and_attached_to_core(self):
		from frappe.utils.file_manager import save_file

		template_name = f"document_{frappe.generate_hash(length=6).lower()}"
		frappe.get_doc({
			"doctype": "WhatsApp Core Template",
			"template_key": scoped_template_key(self.account, template_name, "en"),
			"account_name": self.account,
			"channel": self.channel.name,
			"template_name": template_name,
			"language_code": "en",
			"approval_status": "APPROVED",
			"enabled": 1,
			"header_type": "DOCUMENT",
			"body_text": "Attached for {{1}}",
		}).insert(ignore_permissions=True)
		file_doc = save_file(
			"cutover-proof.txt",
			b"cutover-proof",
			None,
			None,
			is_private=1,
		)
		with (
			patch("frappe_whatsapp_core.outbound.outbound_ready", return_value=True),
			patch(
				"frappe_whatsapp_core.legacy_compat.upload_media_internal",
				return_value={"media_id": "media-proof"},
			) as upload,
		):
			message = queue_template_by_phone(
				self.phone,
				template_name,
				variables={"body": ["Member"]},
				document_link=file_doc.file_url,
				document_filename=file_doc.file_name,
				phone_number_id=self.phone_number_id,
				enqueue_delivery=False,
			)
		upload.assert_called_once()
		content = json.loads(message.content)
		self.assertEqual(content["template_snapshot"]["header_media"], file_doc.file_url)
		self.assertEqual(
			frappe.db.get_value("File", file_doc.name, "attached_to_name"),
			message.name,
		)

	def test_component_converter_accepts_json_and_native_parameters(self):
		self.assertEqual(
			legacy_template_components('{"body":["A",2]}'),
			[{
				"type": "body",
				"parameters": [
					{"type": "text", "text": "A"},
					{"type": "text", "text": "2"},
				],
			}],
		)
