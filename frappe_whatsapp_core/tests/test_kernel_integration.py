import copy
import json
import unittest
from datetime import datetime

import frappe
from frappe.tests.utils import FrappeTestCase

from frappe_whatsapp_core.api import receive_outbound_result
from frappe_whatsapp_core.cases import create_case, transition_case
from frappe_whatsapp_core.flow_router import route_inbound
from frappe_whatsapp_core.flows import publish_flow, resume_flow
from frappe_whatsapp_core.materializer import (
	get_or_create_channel,
	get_or_create_conversation,
	get_or_create_identity,
	materialize_event,
	materialize_status,
)
from frappe_whatsapp_core.packs import install_pack

MESSAGE_PAYLOAD = {
	"object": "whatsapp_business_account",
	"entry": [{
		"id": "WABA-TEST",
		"changes": [{
			"field": "messages",
			"value": {
				"metadata": {"phone_number_id": "PHONE-TEST"},
				"messages": [{
					"id": "wamid.kernel-integration",
					"from": "+91 99999 99999",
					"timestamp": "1712345678",
					"type": "text",
					"text": {"body": "Test message"},
				}],
			},
		}],
	}],
}


class TestKernelIntegration(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		from essdee_whatsapp.solution_pack import MANIFEST

		cls.manifest = copy.deepcopy(MANIFEST)
		install_pack(cls.manifest)

	def _event(self, event_id, payload):
		return frappe.get_doc({
			"doctype": "WhatsApp Core Event",
			"event_id": event_id,
			"status": "Pending",
			"event_type": "message:text",
			"direction": "Inbound",
			"payload": json.dumps(payload),
		}).insert(ignore_permissions=True)

	def test_solution_pack_is_idempotent_and_immutable(self):
		first = install_pack(self.manifest)
		second = install_pack(copy.deepcopy(self.manifest))
		self.assertEqual(first, second)
		self.assertEqual(
			frappe.db.count("WhatsApp Core Workspace", {"solution": "essdee.operations"}),
			3,
		)
		self.assertEqual(
			frappe.db.count("WhatsApp Core Case Type", {"solution": "essdee.operations"}),
			3,
		)

		changed = copy.deepcopy(self.manifest)
		changed["name"] = "Mutated Active Pack"
		with self.assertRaises(frappe.ValidationError):
			install_pack(changed)

	def test_message_projection_deduplication_and_status(self):
		event = self._event("event-kernel-message", MESSAGE_PAYLOAD)
		created = materialize_event(event, MESSAGE_PAYLOAD)
		duplicate = materialize_event(event, MESSAGE_PAYLOAD)
		self.assertEqual(created[0]["status"], "created")
		self.assertEqual(duplicate[0]["status"], "duplicate")

		message = frappe.get_doc("WhatsApp Core Message", created[0]["name"])
		self.assertEqual(message.body, "Test message")
		self.assertEqual(message.provider_timestamp, datetime(2024, 4, 5, 19, 34, 38))
		conversation = frappe.get_doc(
			"WhatsApp Core Conversation",
			message.conversation,
		)
		self.assertEqual(
			frappe.db.count(
				"WhatsApp Core Conversation",
				{
					"channel": message.channel,
					"remote_identity": conversation.remote_identity,
				},
			),
			1,
		)
		self.assertEqual(
			frappe.db.count(
				"WhatsApp Core Identity",
				{"normalized_value": "919999999999"},
			),
			1,
		)

		status_payload = {
			"entry": [{
				"id": "WABA-TEST",
				"changes": [{
					"field": "messages",
					"value": {
						"metadata": {"phone_number_id": "PHONE-TEST"},
						"statuses": [{
							"id": "wamid.kernel-integration",
							"status": "delivered",
						}],
					},
				}],
			}],
		}
		status_event = self._event("event-kernel-status", status_payload)
		result = materialize_event(status_event, status_payload)
		self.assertEqual(result[0]["status"], "updated")
		self.assertEqual(
			frappe.db.get_value("WhatsApp Core Message", message.name, "delivery_status"),
			"Delivered",
		)

	def test_durable_outbound_result_maps_provider_id_without_regression(self):
		suffix = frappe.generate_hash(length=10)
		channel = get_or_create_channel(f"callback-phone-{suffix}")
		identity = get_or_create_identity(
			f"9198{frappe.utils.now_datetime().strftime('%H%M%S%f')}"
		)
		conversation = get_or_create_conversation(channel, identity)
		message_key = f"callback-message-{suffix}"
		message = frappe.get_doc({
			"doctype": "WhatsApp Core Message",
			"message_key": message_key,
			"idempotency_key": message_key,
			"conversation": conversation.name,
			"channel": channel.name,
			"provider_message_id": f"local:{suffix}",
			"direction": "Outbound",
			"message_type": "text",
			"body": "Queued",
			"content": "{}",
			"provider_timestamp": frappe.utils.now_datetime(),
			"delivery_status": "Queued",
		}).insert(ignore_permissions=True)

		result = receive_outbound_result(
			message.name,
			"sent",
			success=1,
			event_id=f"relay-{suffix}",
			meta_message_id=f"wamid.{suffix}",
			status_code=200,
			attempt=1,
		)
		self.assertEqual(result["delivery_status"], "Sent")
		message.reload()
		self.assertEqual(message.provider_message_id, f"wamid.{suffix}")

		materialize_status(
			channel,
			{"id": f"wamid.{suffix}", "status": "delivered"},
		)
		receive_outbound_result(
			message.name,
			"sent",
			success=1,
			meta_message_id=f"wamid.{suffix}",
		)
		message.reload()
		self.assertEqual(message.delivery_status, "Delivered")

	def test_case_required_fields_and_terminal_transition(self):
		with self.assertRaises(frappe.ValidationError):
			create_case("essdee.operations.tech_support", "Missing description")

		case = create_case(
			"essdee.operations.tech_support",
			"Printer is offline",
			{"description": "Warehouse printer is unreachable"},
		)
		self.assertEqual(case.stage_key, "reported")
		self.assertEqual(case.state_category, "open")

		case = transition_case(case.name, "diagnosing")
		self.assertEqual(case.state_category, "active")
		case = transition_case(case.name, "resolved")
		self.assertEqual(case.state_category, "done")
		self.assertIsNotNone(case.closed_at)

	def test_versioned_flow_branches_and_keeps_context(self):
		payload = copy.deepcopy(MESSAGE_PAYLOAD)
		payload["entry"][0]["changes"][0]["value"]["messages"][0]["id"] = "wamid.flow-conversation"
		event = self._event("event-flow-conversation", payload)
		message_name = materialize_event(event, payload)[0]["name"]
		conversation = frappe.db.get_value("WhatsApp Core Message", message_name, "conversation")
		graph = {
			"schema_version": 1,
			"triggers": [{"key": "help", "type": "command", "match": "/help"}],
			"nodes": [
				{"id": "start", "type": "start", "config": {"label": "Start"}},
				{
					"id": "liked",
					"type": "ask_choice",
					"config": {
						"message": "Do you like our products?",
						"answer_key": "liked",
						"options": [
							{"label": "Yes", "value": "yes"},
							{"label": "No", "value": "no"},
						],
					},
				},
				{"id": "branch", "type": "condition", "config": {}},
				{
					"id": "product",
					"type": "ask_text",
					"config": {"message": "Which product?", "answer_key": "product"},
				},
				{
					"id": "difficulty",
					"type": "ask_text",
					"config": {
						"message": "What difficulty did you face?",
						"answer_key": "difficulty",
					},
				},
				{
					"id": "remember",
					"type": "action",
					"config": {
						"action": "context.set",
						"input": {
							"key": "favorite",
							"value": {"var": "answers.product"},
						},
					},
				},
				{"id": "end", "type": "end", "config": {}},
			],
			"edges": [
				{"id": "e1", "source": "start", "target": "liked"},
				{"id": "e2", "source": "liked", "target": "branch"},
				{
					"id": "e3",
					"source": "branch",
					"target": "product",
					"when": {
						"op": "eq",
						"left": {"var": "answers.liked"},
						"right": "yes",
					},
				},
				{"id": "e4", "source": "branch", "target": "difficulty", "default": True},
				{"id": "e5", "source": "product", "target": "remember"},
				{"id": "e5b", "source": "remember", "target": "end"},
				{"id": "e6", "source": "difficulty", "target": "end"},
			],
		}
		flow = frappe.get_doc({
			"doctype": "WhatsApp Core Flow",
			"flow_key": "test.review",
			"title": "Review",
			"status": "Draft",
			"enabled": 1,
			"draft_graph": json.dumps(graph),
		}).insert(ignore_permissions=True)
		published = publish_flow(flow.name)
		self.assertEqual(published["status"], "published")

		started = route_inbound(conversation, "event:/help", {"body": "/help"})
		self.assertTrue(started["handled"])
		self.assertEqual(started["kind"], "start")
		self.assertEqual(started["status"], "waiting")
		self.assertEqual(started["commands"][-1]["type"], "ask_choice")

		second = resume_flow(started["instance"], "event:liked", "yes")
		self.assertEqual(second["status"], "waiting")
		self.assertEqual(second["commands"][-1]["message"], "Which product?")

		completed = resume_flow(started["instance"], "event:product", "Model A")
		self.assertEqual(completed["status"], "completed")
		instance = frappe.get_doc("WhatsApp Core Flow Instance", started["instance"])
		self.assertEqual(json.loads(instance.context)["answers"]["product"], "Model A")
		self.assertEqual(json.loads(instance.context)["variables"]["favorite"], "Model A")


if __name__ == "__main__":
	unittest.main()
