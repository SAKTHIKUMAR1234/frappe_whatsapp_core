import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import now_datetime

from frappe_whatsapp_core.identity import get_or_create_identity, _update_whatsapp_identity
from frappe_whatsapp_core.materializer import (
	get_or_create_channel,
	get_or_create_conversation,
	materialize_event,
)
from frappe_whatsapp_core.outbound import (
	_message_payload,
	deliver_queued_message,
	queue_marketing_template,
	queue_template_internal,
	queue_text_internal,
	resolve_recipient_phone,
	start_conversation,
)
from frappe_whatsapp_core.template_catalog import scoped_template_key


class TestBusinessScopedUserIdentity(FrappeTestCase):
	def setUp(self):
		super().setUp()
		self.suffix = frappe.generate_hash(length=10).lower()
		self.channel = get_or_create_channel(f"bsuid-phone-{self.suffix}", f"bsuid-waba-{self.suffix}")
		self.second_channel = get_or_create_channel(f"bsuid-phone-2-{self.suffix}", f"bsuid-waba-2-{self.suffix}")
		self.bsuid = f"US.A{self.suffix}"
		self.parent_bsuid = f"US.ENT.P{self.suffix}"
		self.phone = f"1415{now_datetime().strftime('%H%M%S%f')[-7:]}"
		settings = frappe.get_single("WhatsApp Core Settings")
		settings.set("accounts", [
			{"channel": self.channel.name, "account_name": f"account-{self.suffix}", "is_default": 1},
			{"channel": self.second_channel.name, "account_name": f"account-2-{self.suffix}"},
		])
		settings.save(ignore_permissions=True)

	def _event(self, label, payload):
		return frappe.get_doc({
			"doctype": "WhatsApp Core Event",
			"event_id": f"bsuid-{label}-{self.suffix}",
			"status": "Pending",
			"event_type": "messages",
			"direction": "Inbound",
			"payload": json.dumps(payload),
		}).insert(ignore_permissions=True)

	def _payload(self, messages, contacts=None, field="messages", extra=None):
		value = {
			"metadata": {"phone_number_id": self.channel.phone_number_id},
			"messages": messages,
		}
		if contacts is not None:
			value["contacts"] = contacts
		value.update(extra or {})
		return {
			"object": "whatsapp_business_account",
			"entry": [{
				"id": self.channel.waba_id,
				"changes": [{"field": field, "value": value}],
			}],
		}

	def test_phone_and_bsuid_are_typed_aliases_but_account_scoped(self):
		legacy = get_or_create_identity(self.phone, resolve=False)
		canonical = get_or_create_identity(
			self.bsuid,
			resolve=False,
			scope=self.channel.name,
			aliases={
				"user_id": self.bsuid,
				"parent_user_id": self.parent_bsuid,
				"phone": self.phone,
				"profile": {"name": "Private Name", "username": "private_user"},
			},
		)
		self.assertNotEqual(canonical.name, legacy.name)
		self.assertEqual(canonical.identifier_type, "BSUID")
		self.assertEqual(canonical.identity_scope, self.channel.name)
		self.assertEqual(resolve_recipient_phone(canonical, {"channel": self.channel.name}), self.bsuid)
		attributes = frappe.parse_json(canonical.attributes)
		self.assertEqual(attributes["parent_business_scoped_user_id"], self.parent_bsuid)
		self.assertEqual(attributes["username"], "private_user")
		self.assertIn(self.phone, attributes["phone_aliases"])

		other = get_or_create_identity(
			self.bsuid,
			resolve=False,
			scope=self.second_channel.name,
			aliases={"user_id": self.bsuid},
		)
		self.assertNotEqual(other.name, canonical.name)
		with self.assertRaises(frappe.ValidationError):
			resolve_recipient_phone(canonical, {"channel": self.second_channel.name})

	def test_identity_enrichment_reloads_a_stale_document_under_row_lock(self):
		identity = get_or_create_identity(
			self.bsuid,
			resolve=False,
			scope=self.channel.name,
			aliases={"user_id": self.bsuid, "username": "first_name"},
		)
		stale = frappe.get_doc("WhatsApp Core Identity", identity.name)
		concurrent = frappe.get_doc("WhatsApp Core Identity", identity.name)
		concurrent.display_value = "Concurrent update"
		concurrent.save(ignore_permissions=True)

		_update_whatsapp_identity(
			stale,
			scope=self.channel.name,
			bsuid=self.bsuid,
			parent_bsuid="",
			phone=self.phone,
			aliases={"user_id": self.bsuid, "phone": self.phone},
		)

		stale.reload()
		self.assertEqual(stale.display_value, self.phone)
		self.assertIn(self.phone, frappe.parse_json(stale.attributes)["phone_aliases"])

	def test_late_signed_phone_alias_merges_existing_same_account_threads(self):
		legacy = get_or_create_identity(self.phone, resolve=False)
		legacy_conversation = get_or_create_conversation(self.channel, legacy)
		scoped = get_or_create_identity(
			self.bsuid,
			resolve=False,
			scope=self.channel.name,
			aliases={"user_id": self.bsuid},
		)
		scoped_conversation = get_or_create_conversation(self.channel, scoped)

		resolved = get_or_create_identity(
			self.bsuid,
			resolve=False,
			scope=self.channel.name,
			aliases={"user_id": self.bsuid, "phone": self.phone},
		)

		self.assertEqual(resolved.name, scoped.name)
		self.assertFalse(frappe.db.exists(
			"WhatsApp Core Conversation", legacy_conversation.name
		))
		self.assertEqual(
			frappe.db.get_value(
				"WhatsApp Core Conversation", scoped_conversation.name, "remote_identity"
			),
			scoped.name,
		)
		legacy.reload()
		self.assertEqual(legacy.identifier_type, "Phone")
		self.assertFalse(legacy.identity_scope)

	def test_parent_only_identity_coalesces_with_later_regular_bsuid(self):
		started = start_conversation(self.channel.name, self.parent_bsuid)
		parent_only = frappe.get_doc("WhatsApp Core Identity", started["identity"])
		conversation = frappe.get_doc(
			"WhatsApp Core Conversation", started["conversation"]
		)
		self.assertEqual(parent_only.normalized_value, self.parent_bsuid)
		self.assertEqual(started["phone_number"], self.parent_bsuid)
		self.assertEqual(resolve_recipient_phone(
			parent_only, {"channel": self.channel.name}
		), self.parent_bsuid)

		regular = get_or_create_identity(
			self.bsuid,
			resolve=False,
			scope=self.channel.name,
			aliases={
				"user_id": self.bsuid,
				"parent_user_id": self.parent_bsuid,
			},
		)

		self.assertEqual(regular.name, parent_only.name)
		self.assertEqual(regular.normalized_value, self.bsuid)
		self.assertEqual(resolve_recipient_phone(
			regular, {"channel": self.channel.name}
		), self.bsuid)
		self.assertEqual(
			frappe.db.get_value(
				"WhatsApp Core Conversation", conversation.name, "remote_identity"
			),
			regular.name,
		)

	def test_shared_legacy_phone_is_split_without_stranding_other_account(self):
		legacy = get_or_create_identity(self.phone, resolve=False)
		first_conversation = get_or_create_conversation(self.channel, legacy)
		second_conversation = get_or_create_conversation(self.second_channel, legacy)

		scoped = get_or_create_identity(
			self.bsuid,
			resolve=False,
			scope=self.channel.name,
			aliases={"user_id": self.bsuid, "phone": self.phone},
		)

		self.assertNotEqual(scoped.name, legacy.name)
		self.assertEqual(
			frappe.db.get_value(
				"WhatsApp Core Conversation",
				{"channel": self.channel.name, "remote_identity": scoped.name},
				"remote_identity",
			),
			scoped.name,
		)
		self.assertEqual(
			frappe.db.get_value(
				"WhatsApp Core Conversation", second_conversation.name, "remote_identity"
			),
			legacy.name,
		)
		legacy.reload()
		self.assertEqual(legacy.identifier_type, "Phone")
		self.assertFalse(legacy.identity_scope)
		self.assertEqual(
			resolve_recipient_phone(legacy, {"channel": self.second_channel.name}),
			self.phone,
		)

	def test_bsuid_only_message_and_system_rotation_keep_one_thread(self):
		first = self._payload(
			[{
				"id": f"wamid.old.{self.suffix}",
				"from_user_id": self.bsuid,
				"timestamp": "1712345678",
				"type": "text",
				"text": {"body": "private sender"},
			}],
			contacts=[{
				"user_id": self.bsuid,
				"parent_user_id": self.parent_bsuid,
				"profile": {"username": "private_user"},
			}],
		)
		created = materialize_event(self._event("old", first), first)[0]
		old_message = frappe.get_doc("WhatsApp Core Message", created["name"])

		new_bsuid = f"US.N{self.suffix}"
		new_message_payload = self._payload(
			[{
				"id": f"wamid.new.{self.suffix}",
				"from_user_id": new_bsuid,
				"type": "text",
				"text": {"body": "same person"},
			}],
			contacts=[{"user_id": new_bsuid, "profile": {"username": "renamed_user"}}],
		)
		new_result = materialize_event(self._event("new", new_message_payload), new_message_payload)[0]
		new_message = frappe.get_doc("WhatsApp Core Message", new_result["name"])
		self.assertNotEqual(new_message.conversation, old_message.conversation)
		previous_parent = f"US.ENT.Old{self.suffix}"
		system = self._payload(
			[{
				"id": f"wamid.system.{self.suffix}",
				"type": "system",
				"system": {
					"type": "user_changed_number",
					"previous_user_id": self.bsuid,
					"user_id": new_bsuid,
					"previous_parent_user_id": previous_parent,
					"parent_user_id": self.parent_bsuid,
				},
			}],
			contacts=[{"user_id": new_bsuid, "profile": {"username": "private_user"}}],
		)
		system_result = materialize_event(self._event("system", system), system)[0]
		new_message.reload()
		self.assertEqual(system_result["status"], "created")
		self.assertEqual(new_message.conversation, old_message.conversation)
		self.assertEqual(
			frappe.db.get_value(
				"WhatsApp Core Conversation", old_message.conversation, "remote_identity"
			),
			frappe.db.get_value(
				"WhatsApp Core Conversation", new_message.conversation, "remote_identity"
			),
		)
		self.assertEqual(materialize_event(self._event("new-replay", new_message_payload), new_message_payload)[0]["status"], "duplicate")
		identity_name = frappe.db.get_value(
			"WhatsApp Core Conversation", old_message.conversation, "remote_identity"
		)
		for parent in (previous_parent, self.parent_bsuid):
			self.assertEqual(
				frappe.db.get_value(
					"WhatsApp Core Identity Alias",
					{"identity_scope": self.channel.name, "alias_value": parent},
					"identity",
				),
				identity_name,
			)

	def test_reverse_arrival_of_chained_rotations_preserves_latest_identity(self):
		middle_bsuid = f"US.M{self.suffix}"
		latest_bsuid = f"US.L{self.suffix}"

		def rotation(label, old_user_id, new_user_id):
			payload = self._payload(
				[{
					"id": f"wamid.rotation.{label}.{self.suffix}",
					"type": "system",
					"system": {
						"type": "user_changed_user_id",
						"previous_user_id": old_user_id,
						"user_id": new_user_id,
					},
				}],
				contacts=[{"user_id": new_user_id}],
			)
			return materialize_event(self._event(label, payload), payload)[0]

		later = rotation("middle-latest", middle_bsuid, latest_bsuid)
		late_predecessor = rotation("old-middle", self.bsuid, middle_bsuid)
		latest_message_payload = self._payload(
			[{
				"id": f"wamid.latest.{self.suffix}",
				"from_user_id": latest_bsuid,
				"type": "text",
				"text": {"body": "latest identity"},
			}],
			contacts=[{"user_id": latest_bsuid}],
		)
		latest_message = materialize_event(
			self._event("latest-message", latest_message_payload), latest_message_payload
		)[0]
		conversations = {
			frappe.db.get_value("WhatsApp Core Message", result["name"], "conversation")
			for result in (later, late_predecessor, latest_message)
		}
		self.assertEqual(len(conversations), 1)
		identity_name = frappe.db.get_value(
			"WhatsApp Core Conversation", conversations.pop(), "remote_identity"
		)
		identity = frappe.get_doc("WhatsApp Core Identity", identity_name)
		self.assertEqual(identity.normalized_value, latest_bsuid)
		attributes = frappe.parse_json(identity.attributes)
		self.assertEqual(attributes["business_scoped_user_id"], latest_bsuid)
		for identifier in (self.bsuid, middle_bsuid, latest_bsuid):
			self.assertEqual(
				frappe.db.get_value(
					"WhatsApp Core Identity Alias",
					{"identity_scope": self.channel.name, "alias_value": identifier},
					"identity",
				),
				identity.name,
			)

	def test_user_id_update_and_status_contacts_preserve_scoped_aliases(self):
		legacy = get_or_create_identity(self.phone, resolve=False)
		conversation = get_or_create_conversation(self.channel, legacy)
		other_conversation = get_or_create_conversation(self.second_channel, legacy)
		message = frappe.get_doc({
			"doctype": "WhatsApp Core Message",
			"message_key": f"status-{self.suffix}",
			"idempotency_key": f"status-{self.suffix}",
			"conversation": conversation.name,
			"channel": self.channel.name,
			"provider_message_id": f"wamid.status.{self.suffix}",
			"direction": "Outbound",
			"message_type": "text",
			"body": "hello",
			"content": {"body": "hello"},
			"provider_timestamp": now_datetime(),
			"delivery_status": "Sent",
		}).insert(ignore_permissions=True)
		status_payload = self._payload(
			[],
			contacts=[{
				"wa_id": self.phone,
				"user_id": self.bsuid,
				"parent_user_id": self.parent_bsuid,
				"profile": {"username": "status_user"},
			}],
			extra={"statuses": [{
				"id": message.provider_message_id,
				"status": "delivered",
				"recipient_id": self.phone,
				"recipient_user_id": self.bsuid,
				"recipient_parent_user_id": self.parent_bsuid,
			}]},
		)
		self.assertEqual(
			materialize_event(self._event("status", status_payload), status_payload)[0]["status"],
			"updated",
		)
		conversation = frappe.get_doc(
			"WhatsApp Core Conversation",
			frappe.db.get_value("WhatsApp Core Message", message.name, "conversation"),
		)
		identity = frappe.get_doc("WhatsApp Core Identity", conversation.remote_identity)
		self.assertEqual(identity.identity_scope, self.channel.name)
		self.assertEqual(frappe.parse_json(identity.attributes)["username"], "status_user")
		self.assertEqual(
			frappe.db.get_value(
				"WhatsApp Core Conversation", other_conversation.name, "remote_identity"
			),
			legacy.name,
		)

		new_bsuid = f"US.U{self.suffix}"
		update_payload = self._payload(
			[],
			contacts=[{
				"wa_id": self.phone, "user_id": new_bsuid,
				"profile": {"username": "updated_user"},
			}],
			field="user_id_update",
			extra={"user_id_update": {
				"wa_id": self.phone,
				"user_id": {"previous": self.bsuid, "current": new_bsuid},
				"parent_user_id": {
					"previous": self.parent_bsuid,
					"current": f"US.ENT.U{self.suffix}",
				},
			}},
		)
		result = materialize_event(self._event("user-update", update_payload), update_payload)[0]
		self.assertEqual(result["status"], "resolved")
		self.assertEqual(result["name"], identity.name)

	def test_preferences_are_ordered_and_stop_blocks_queued_delivery(self):
		identity = get_or_create_identity(
			self.bsuid, resolve=False, scope=self.channel.name,
			aliases={"user_id": self.bsuid},
		)
		conversation = get_or_create_conversation(self.channel, identity)
		marketing = self._template("MARKETING")

		def preference(value, timestamp, label):
			payload = self._payload(
				[],
				contacts=[{
					"user_id": self.bsuid,
					"profile": {"username": "preference_user"},
				}],
				field="user_preferences",
				extra={"user_preferences": [{
					"user_id": self.bsuid,
					"category": "marketing_messages",
					"value": value,
					"timestamp": str(timestamp),
				}]},
			)
			return materialize_event(self._event(label, payload), payload)

		preference("RESUME", 100, "resume")
		with (
			patch("frappe_whatsapp_core.outbound.outbound_ready", return_value=True),
			patch("frappe_whatsapp_core.outbound._run_preflight_hooks"),
			patch("frappe_whatsapp_core.outbound.frappe.enqueue"),
		):
			queued = queue_marketing_template(conversation.name, marketing.name)
		preference("STOP", 200, "stop")
		preference("RESUME", 150, "stale-resume")
		identity.reload()
		attributes = frappe.parse_json(identity.attributes)
		self.assertEqual(attributes["user_preferences"]["MARKETING_MESSAGES"]["value"], "STOP")
		self.assertEqual(attributes["username"], "preference_user")
		with patch("frappe_whatsapp_core.outbound.send_raw") as send_raw:
			deliver_queued_message(queued.name)
			send_raw.assert_not_called()
		self.assertEqual(
			frappe.db.get_value("WhatsApp Core Message", queued.name, "delivery_status"),
			"Failed",
		)

	def test_aggregated_preferences_match_contacts_without_cross_user_leakage(self):
		other_bsuid = f"GB.B{self.suffix}"
		payload = self._payload(
			[],
			contacts=[
				{"user_id": self.bsuid, "profile": {"username": "first_user"}},
				{"user_id": other_bsuid, "profile": {"username": "second_user"}},
			],
			field="user_preferences",
			extra={"user_preferences": [
				{
					"user_id": self.bsuid, "category": "marketing_messages",
					"value": "STOP", "timestamp": "200",
				},
				{
					"user_id": other_bsuid, "category": "marketing_messages",
					"value": "RESUME", "timestamp": "201",
				},
			]},
		)
		results = materialize_event(self._event("preferences-aggregate", payload), payload)
		self.assertEqual(len(results), 2)
		identities = [frappe.get_doc("WhatsApp Core Identity", row["name"]) for row in results]
		projected = {
			identity.normalized_value: frappe.parse_json(identity.attributes)
			for identity in identities
		}
		self.assertEqual(projected[self.bsuid]["username"], "first_user")
		self.assertEqual(projected[other_bsuid]["username"], "second_user")
		self.assertEqual(
			projected[self.bsuid]["user_preferences"]["MARKETING_MESSAGES"]["value"],
			"STOP",
		)
		self.assertEqual(
			projected[other_bsuid]["user_preferences"]["MARKETING_MESSAGES"]["value"],
			"RESUME",
		)

	def test_status_identity_mismatch_fails_closed(self):
		identity = get_or_create_identity(
			self.bsuid, resolve=False, scope=self.channel.name,
			aliases={"user_id": self.bsuid},
		)
		conversation = get_or_create_conversation(self.channel, identity)
		message = frappe.get_doc({
			"doctype": "WhatsApp Core Message",
			"message_key": f"mismatch-{self.suffix}",
			"idempotency_key": f"mismatch-{self.suffix}",
			"conversation": conversation.name,
			"channel": self.channel.name,
			"provider_message_id": f"wamid.mismatch.{self.suffix}",
			"direction": "Outbound",
			"message_type": "text",
			"body": "hello",
			"content": {"body": "hello"},
			"provider_timestamp": now_datetime(),
			"delivery_status": "Sent",
		}).insert(ignore_permissions=True)
		other_bsuid = f"GB.X{self.suffix}"
		payload = self._payload(
			[],
			contacts=[{"user_id": other_bsuid}],
			extra={"statuses": [{
				"id": message.provider_message_id,
				"status": "delivered",
				"recipient_user_id": other_bsuid,
			}]},
		)
		with self.assertRaises(frappe.ValidationError):
			materialize_event(self._event("status-mismatch", payload), payload)

	def test_bsuid_only_call_preserves_parent_and_profile(self):
		payload = self._payload(
			[],
			contacts=[{
				"user_id": self.bsuid,
				"parent_user_id": self.parent_bsuid,
				"profile": {"username": "caller"},
			}],
			field="calls",
			extra={
				"calls": [{
					"id": f"call-{self.suffix}",
					"from_user_id": self.bsuid,
					"from_parent_user_id": self.parent_bsuid,
					"event": "connect",
				}],
			},
		)
		result = materialize_event(self._event("call", payload), payload)[0]
		call = frappe.get_doc("WhatsApp Core Call", result["name"])
		self.assertEqual(call.remote_user_id, self.bsuid)
		self.assertEqual(call.remote_parent_user_id, self.parent_bsuid)
		identity = get_or_create_identity(
			self.bsuid, resolve=False, scope=self.channel.name, aliases={"user_id": self.bsuid}
		)
		self.assertEqual(frappe.parse_json(identity.attributes)["username"], "caller")

	def test_outbound_bsuid_preview_marketing_and_authentication_gate(self):
		identity = get_or_create_identity(
			self.bsuid,
			resolve=False,
			scope=self.channel.name,
			aliases={"user_id": self.bsuid},
		)
		conversation = get_or_create_conversation(self.channel, identity)
		conversation.last_inbound_at = now_datetime()
		conversation.save(ignore_permissions=True)
		marketing = self._template("MARKETING")
		authentication = self._template("AUTHENTICATION")
		with (
			patch("frappe_whatsapp_core.outbound.outbound_ready", return_value=True),
			patch("frappe_whatsapp_core.outbound._run_preflight_hooks"),
			patch("frappe_whatsapp_core.outbound.frappe.enqueue"),
		):
			text = queue_text_internal(conversation.name, "https://example.com", preview_url=True)
			marketing_message = queue_marketing_template(
				conversation.name,
				marketing.name,
				message_activity_sharing=1,
			)
			with self.assertRaises(frappe.ValidationError):
				queue_template_internal(conversation.name, authentication.name)

		text_doc = frappe.get_doc("WhatsApp Core Message", text.name)
		text_payload = _message_payload(text_doc, self.bsuid)
		self.assertTrue(text_payload["text"]["preview_url"])
		self.assertEqual(text_payload["recipient"], self.bsuid)
		self.assertNotIn("to", text_payload)
		marketing_doc = frappe.get_doc("WhatsApp Core Message", marketing_message.name)
		marketing_content = frappe.parse_json(marketing_doc.content)
		self.assertEqual(marketing_content["transport_endpoint"], "marketing_messages")
		self.assertTrue(_message_payload(marketing_doc, self.bsuid)["message_activity_sharing"])

	def _template(self, category):
		name = f"{category.lower()}_{self.suffix}"
		return frappe.get_doc({
			"doctype": "WhatsApp Core Template",
			"template_key": scoped_template_key(f"account-{self.suffix}", name, "en"),
			"account_name": f"account-{self.suffix}",
			"channel": self.channel.name,
			"template_name": name,
			"language_code": "en",
			"category": category,
			"approval_status": "APPROVED",
			"enabled": 1,
			"body_text": "Hello",
			"components": json.dumps([{"type": "BODY", "text": "Hello"}]),
		}).insert(ignore_permissions=True)
