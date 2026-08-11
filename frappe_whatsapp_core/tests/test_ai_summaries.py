import json
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, now_datetime
from redis.exceptions import LockError

from frappe_whatsapp_core.ai_summaries import (
	_media_parts,
	_model_data,
	_run_i2a,
	attach_message_insights,
	enqueue_summary_for_messages,
	get_group_summary,
	get_identity_summary,
	summarize_identities,
	summarize_identity,
)
from frappe_whatsapp_core.hooks import scheduler_events


class TestAISummaries(FrappeTestCase):
	def test_automatic_categorization_runs_in_half_hour_batches(self):
		method = "frappe_whatsapp_core.ai_summaries.queue_pending_summaries"
		cron = scheduler_events["cron"]
		self.assertIn(method, cron["*/30 * * * *"])
		self.assertNotIn(method, cron["* * * * *"])

	def test_query_rows_attach_message_insights_without_calling_missing_serializer(self):
		frappe.get_doc({
			"doctype": "WhatsApp Core Message Insight",
			"insight_key": frappe.generate_hash(length=32),
			"message": self.messages[0].name,
			"conversation": self.conversation.name,
			"identity": self.identity.name,
			"status": "Ready",
			"category": "Payment proof",
			"message_summary": "Payment receipt needs verification.",
			"intents": json.dumps(["payment_confirmation"]),
			"action_items": json.dumps(["Verify payment"]),
			"risks": json.dumps([]),
			"confidence": 95,
		}).insert(ignore_permissions=True)
		messages = [frappe._dict(name=self.messages[0].name)]

		attach_message_insights(messages)

		self.assertEqual(messages[0].ai_insight["category"], "Payment proof")
		self.assertEqual(messages[0].ai_insight["action_items"], ["Verify payment"])

	@patch("frappe_whatsapp_core.ai_summaries.frappe.enqueue")
	@patch("frappe_whatsapp_core.ai_summaries.frappe.db.sql")
	@patch("frappe_whatsapp_core.ai_summaries._settings")
	def test_summary_jobs_are_deduplicated_per_identity(self, settings, sql, enqueue):
		settings.return_value = self.settings
		sql.return_value = [self.identity.name]

		enqueue_summary_for_messages([self.messages[0].name, self.messages[0].name])

		enqueue.assert_called_once()
		kwargs = enqueue.call_args.kwargs
		self.assertTrue(kwargs["deduplicate"])
		self.assertTrue(kwargs["enqueue_after_commit"])
		self.assertTrue(kwargs["job_id"].startswith("whatsapp-summary-"))
		self.assertNotIn(self.identity.name, kwargs["job_id"])

	def setUp(self):
		super().setUp()
		suffix = frappe.generate_hash(length=8)
		self.settings = SimpleNamespace(
			enable_ai_summaries=1,
			summary_i2a_action="WhatsApp Message Understanding",
			summary_batch_size=50,
			summary_max_media_mb=15,
		)
		self.identity = frappe.get_doc({
			"doctype": "WhatsApp Core Identity",
			"identity_key": f"summary-identity-{suffix}",
			"identity_type": "WhatsApp",
			"normalized_value": f"summary-{suffix}",
			"display_value": "Summary Test Contact",
			"provider": "Meta",
			"status": "Active",
			"resolution_status": "Unresolved",
			"attributes": "{}",
		}).insert(ignore_permissions=True)
		self.channel = frappe.get_doc({
			"doctype": "WhatsApp Core Channel",
			"channel_key": f"summary-channel-{suffix}",
			"display_name": "Summary Test Channel",
			"provider": "Meta",
			"phone_number_id": f"phone-{suffix}",
			"waba_id": f"waba-{suffix}",
			"enabled": 1,
		}).insert(ignore_permissions=True)
		self.conversation = frappe.get_doc({
			"doctype": "WhatsApp Core Conversation",
			"conversation_key": f"summary-conversation-{suffix}",
			"channel": self.channel.name,
			"remote_identity": self.identity.name,
			"status": "Open",
			"last_message_at": now_datetime(),
		}).insert(ignore_permissions=True)
		self.messages = [
			self._message("Customer says the payment was made", 0),
			self._message("Please arrange a callback tomorrow", 1),
		]

	def _message(self, body, offset):
		timestamp = add_to_date(now_datetime(), seconds=offset)
		return frappe.get_doc({
			"doctype": "WhatsApp Core Message",
			"message_key": f"summary-message-{frappe.generate_hash(length=10)}",
			"conversation": self.conversation.name,
			"channel": self.channel.name,
			"provider_message_id": f"wamid.summary.{frappe.generate_hash(length=12)}",
			"direction": "Inbound",
			"message_type": "text",
			"body": body,
			"content": json.dumps({"text": {"body": body}}),
			"provider_timestamp": timestamp,
			"delivery_status": "Received",
		}).insert(ignore_permissions=True)

	def _result(self, summary, refs):
		return {
			"data": {
				"summary": summary,
				"primary_intent": "Payment follow-up",
				"categories": ["Payment proof", "Callback"],
				"action_items": ["Verify payment", "Call customer"],
				"risks": ["Payment is not independently verified"],
				"confidence": 92,
				"language": "English",
				"message_insights": [
					{
						"message_ref": ref,
						"transcript": "" if ref != "M1" else "Payment completed",
						"media_summary": "",
						"message_summary": f"Insight for {ref}",
						"category": "Payment proof" if ref == "M1" else "Callback",
						"primary_intent": "Follow-up",
						"intents": ["follow_up"],
						"action_items": ["Review"],
						"risks": [],
						"confidence": 90,
						"language": "English",
					}
					for ref in refs
				],
			},
			"model": "Test I2A Model",
			"usage": {"total_tokens": 100},
			"latency_ms": 20,
		}

	@patch("frappe_whatsapp_core.ai_summaries._settings")
	@patch("frappe_whatsapp_core.ai_summaries._run_i2a")
	def test_incremental_cursor_does_not_resend_previous_messages(self, run_i2a, settings):
		settings.return_value = self.settings
		run_i2a.return_value = self._result("Payment sent; callback requested.", ["M1", "M2"])

		first = summarize_identity(self.identity.name)

		self.assertEqual(first["processed_message_count"], 2)
		self.assertEqual(first["categories"], ["Payment proof", "Callback"])
		self.assertEqual(
			frappe.db.count("WhatsApp Core Message Insight", {"identity": self.identity.name}),
			2,
		)
		self.assertTrue(frappe.db.exists("WhatsApp Core Message Category", "Payment proof"))
		self.assertTrue(frappe.db.exists("WhatsApp Core Message Category", "Callback"))
		third = self._message("The callback is no longer required", 2)
		run_i2a.return_value = self._result("Payment sent; callback cancelled.", ["M1"])

		second = summarize_identity(self.identity.name)

		self.assertEqual(second["processed_message_count"], 3)
		self.assertEqual(second["last_message"], third.name)
		prompt = json.loads(run_i2a.call_args.args[1])
		self.assertEqual(len(prompt["new_messages"]), 1)
		self.assertEqual(prompt["new_messages"][0]["text"], third.body)
		self.assertEqual(
			prompt["previous_state"]["summary"],
			"Payment sent; callback requested.",
		)
		self.assertEqual(
			prompt["previous_state"]["categories"],
			["Payment proof", "Callback"],
		)
		self.assertIn("Payment proof", prompt["available_categories"])
		self.assertIn("Callback", prompt["available_categories"])

	@patch("frappe_whatsapp_core.ai_summaries._settings")
	@patch("frappe_whatsapp_core.ai_summaries._run_i2a")
	def test_incremental_categories_preserve_prior_contact_history(self, run_i2a, settings):
		settings.return_value = self.settings
		run_i2a.return_value = self._result("Payment sent; callback requested.", ["M1", "M2"])
		summarize_identity(self.identity.name)
		self._message("Please send the latest catalogue", 2)
		run_i2a.return_value = {
			"data": {
				"summary": "Payment follow-up remains open; catalogue requested.",
				"primary_intent": "Catalogue request",
				"categories": ["Catalogue"],
				"action_items": ["Send catalogue"],
				"risks": [],
				"confidence": 96,
				"language": "English",
				"message_insights": [{
					"message_ref": "M1",
					"category": "Catalogue",
					"primary_intent": "Catalogue request",
					"message_summary": "Catalogue requested",
				}],
			},
			"model": "Test I2A Model",
		}

		result = summarize_identity(self.identity.name)

		self.assertEqual(
			result["categories"],
			["Payment proof", "Callback", "Catalogue"],
		)

	@patch("frappe_whatsapp_core.ai_summaries._settings")
	@patch("frappe_whatsapp_core.ai_summaries._run_i2a")
	def test_message_insights_complete_omitted_summary_and_categories(self, run_i2a, settings):
		settings.return_value = self.settings
		run_i2a.return_value = {
			"data": {
				"primary_intent": "Catalogue request",
				"message_insights": [{
					"message_ref": "M1",
					"category": "Catalogue",
					"message_summary": "The customer requested the latest catalogue.",
				}],
			},
			"model": "Test I2A Model",
		}

		result = summarize_identity(self.identity.name)

		self.assertEqual(result["categories"], ["Catalogue"])
		self.assertEqual(
			result["summary"],
			"The customer requested the latest catalogue.",
		)

	@patch("frappe_whatsapp_core.ai_summaries._settings")
	@patch("frappe_whatsapp_core.ai_summaries._run_i2a")
	def test_one_job_drains_all_pending_batches(self, run_i2a, settings):
		self.settings.summary_batch_size = 1
		settings.return_value = self.settings
		run_i2a.side_effect = [
			self._result("Payment received.", ["M1"]),
			self._result("Payment received; callback requested.", ["M1"]),
		]

		summary = summarize_identity(self.identity.name)

		self.assertEqual(run_i2a.call_count, 2)
		self.assertEqual(summary["processed_message_count"], 2)
		self.assertEqual(summary["last_message"], self.messages[-1].name)

	@patch("frappe_whatsapp_core.ai_summaries._settings")
	@patch("frappe_whatsapp_core.ai_summaries._run_i2a")
	def test_group_summary_uses_contact_summaries_not_raw_history(self, run_i2a, settings):
		settings.return_value = self.settings
		run_i2a.side_effect = [
			self._result("Contact reports payment and asks for a callback.", ["M1", "M2"]),
			{
				"data": {
					"summary": "One contact needs payment verification and a callback.",
					"primary_intent": "Management follow-up",
					"categories": [],
					"action_items": ["Verify and call"],
					"risks": ["Unverified payment"],
					"confidence": 88,
					"language": "English",
				},
				"model": "Test I2A Model",
			},
		]
		summarize_identity(self.identity.name)

		group = summarize_identities([self.identity.name], scope_key="agent:test")

		self.assertEqual(group["scope_type"], "Group")
		self.assertEqual(group["identity_count"], 1)
		self.assertEqual(
			get_group_summary("agent:test", [self.identity.name])["summary"],
			group["summary"],
		)
		self.assertEqual(group["categories"], ["Payment proof", "Callback"])
		group_prompt = json.loads(run_i2a.call_args.args[1])
		self.assertEqual(group_prompt["contacts"][0]["contact_ref"], "C1")
		self.assertNotIn(self.messages[0].body, run_i2a.call_args.args[1])

	@patch("frappe_whatsapp_core.ai_summaries._settings")
	@patch("frappe_whatsapp_core.ai_summaries._run_i2a")
	def test_group_summary_first_updates_stale_contact_summaries(self, run_i2a, settings):
		settings.return_value = self.settings
		run_i2a.return_value = self._result("Initial contact summary.", ["M1", "M2"])
		summarize_identity(self.identity.name)
		third = self._message("A new complaint needs attention", 2)
		run_i2a.reset_mock()
		run_i2a.side_effect = [
			self._result("Contact now has an open complaint.", ["M1"]),
			{
				"data": {
					"summary": "One contact has an open complaint.",
					"primary_intent": "Complaint follow-up",
					"categories": ["Complaint"],
					"action_items": ["Review complaint"],
					"risks": [],
					"confidence": 90,
					"language": "English",
				},
				"model": "Test I2A Model",
			},
		]

		group = summarize_identities([self.identity.name], scope_key="agent:current")

		self.assertEqual(run_i2a.call_count, 2)
		self.assertEqual(get_identity_summary(self.identity.name)["last_message"], third.name)
		self.assertEqual(
			group["categories"],
			["Payment proof", "Callback", "Complaint"],
		)

	@patch("frappe_whatsapp_core.ai_summaries.cache_message_media")
	def test_audio_is_sent_as_redactable_i2a_input(self, cache_media):
		audio = self._message("", 3)
		audio.message_type = "audio"
		audio.content = json.dumps({"audio": {"id": "MEDIA-A", "mime_type": "audio/ogg"}})
		audio.save(ignore_permissions=True)
		cache_media.return_value = SimpleNamespace(
			file_name="voice.ogg",
			get_content=lambda: b"voice-bytes",
			get=lambda key: "audio/ogg" if key == "content_type" else None,
		)

		parts = _media_parts([audio], self.settings)

		audio_part = next(part for part in parts if part["type"] == "input_audio")
		self.assertEqual(audio_part["input_audio"]["format"], "ogg")
		self.assertNotEqual(audio_part["input_audio"]["data"], "voice-bytes")

	@patch("frappe_tools.i2a.intents.run_intent")
	def test_invalid_provider_media_falls_back_to_evidence_text(self, run_intent):
		from frappe_tools.i2a.providers import ProviderError

		run_intent.side_effect = [
			ProviderError("Unable to process input image. Please retry"),
			{"data": {"summary": "The text remains actionable."}},
		]

		result = _run_i2a(
			self.settings,
			"Customer requested a catalogue.",
			[{"type": "image_url", "image_url": {"url": "data:image/png;base64,eA=="}}],
		)

		self.assertEqual(result["data"]["summary"], "The text remains actionable.")
		self.assertEqual(run_intent.call_count, 2)
		self.assertEqual(run_intent.call_args.kwargs["content_parts"], [])
		self.assertIn("could not be decoded", run_intent.call_args.args[1])

	@patch("frappe_tools.i2a.intents.run_intent")
	def test_generic_provider_media_error_also_uses_text_fallback(self, run_intent):
		from frappe_tools.i2a.providers import ProviderError

		run_intent.side_effect = [
			ProviderError("Provider returned error"),
			{"data": {"summary": "Recovered without media."}},
		]

		result = _run_i2a(
			self.settings,
			"Evidence text",
			[{"type": "image_url", "image_url": {"url": "data:image/png;base64,eA=="}}],
		)

		self.assertEqual(result["data"]["summary"], "Recovered without media.")
		self.assertEqual(run_intent.call_args.kwargs["content_parts"], [])

	@patch("frappe_whatsapp_core.ai_summaries._settings")
	@patch("frappe_whatsapp_core.ai_summaries._run_i2a", side_effect=RuntimeError("provider down"))
	def test_failed_pass_does_not_advance_message_cursor(self, _run_i2a, settings):
		settings.return_value = self.settings
		with self.assertRaisesRegex(RuntimeError, "provider down"):
			summarize_identity(self.identity.name)

		summary = get_identity_summary(self.identity.name)
		self.assertEqual(summary["status"], "Failed")
		self.assertIsNone(summary["last_message"])
		self.assertEqual(summary["processed_message_count"], 0)

	@patch("frappe_whatsapp_core.ai_summaries._settings")
	@patch("frappe_whatsapp_core.ai_summaries.frappe.cache.lock")
	def test_busy_summary_returns_cached_pending_state(self, cache_lock, settings):
		settings.return_value = self.settings
		cache_lock.return_value.__enter__.side_effect = LockError("busy")

		result = summarize_identity(self.identity.name)

		self.assertTrue(result["refresh_in_progress"])
		self.assertEqual(result["scope_type"], "Identity")
		self.assertEqual(result["identity"], self.identity.name)

	def test_provider_list_result_is_normalized_without_attribute_error(self):
		result = _model_data({
			"data": [{"message_ref": "M1", "category": "Complaint"}],
		})

		self.assertEqual(result["message_insights"][0]["category"], "Complaint")

	def test_duplicate_provider_insights_are_collapsed_by_message_ref(self):
		result = _model_data({
			"data": {
				"summary": "Payment needs review.",
				"message_insights": [
					{"message_ref": "M1", "category": "Other"},
					{"message_ref": "M1", "category": "Payment proof"},
				],
			},
		})

		self.assertEqual(len(result["message_insights"]), 1)
		self.assertEqual(result["message_insights"][0]["category"], "Payment proof")
