from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from frappe_whatsapp_core.flow_actions import (
	action_definition,
	execute_registered_action,
	registered_action_catalog,
)
from frappe_whatsapp_core.flow_schema import validate_graph
from frappe_whatsapp_core.flow_templates import BUILTIN_FLOWS
from frappe_whatsapp_core.materializer import (
	get_or_create_channel,
	get_or_create_conversation,
	get_or_create_identity,
)


class TestFlowActionContract(FrappeTestCase):
	def test_business_app_can_register_typed_dotted_python_action(self):
		hooks = {
			"example.record": {
				"label": "Record example",
				"method": "example_app.whatsapp_actions.record_example",
				"parameters": {
					"type": "object",
					"required": ["value"],
					"properties": {"value": {"type": "string"}},
				},
			}
		}
		with patch("frappe_whatsapp_core.flow_actions.frappe.get_hooks", return_value=hooks):
			catalog = registered_action_catalog()
			self.assertEqual(catalog[0]["method"], hooks["example.record"]["method"])
			self.assertEqual(
				action_definition(hooks["example.record"]["method"])["key"],
				"example.record",
			)

	def test_frappe_merged_hook_scalars_are_normalized(self):
		hooks = {
			"example.record": {
				"label": ["Record example"],
				"method": ["example_app.whatsapp_actions.record_example"],
				"parameters": {
					"type": ["object"],
					"required": ["value"],
					"properties": {
						"value": {"type": ["string"], "title": ["Value"]}
					},
				},
			}
		}
		with patch("frappe_whatsapp_core.flow_actions.frappe.get_hooks", return_value=hooks):
			definition = registered_action_catalog()[0]
			self.assertEqual(definition["method"], "example_app.whatsapp_actions.record_example")
			self.assertEqual(definition["parameters"]["type"], "object")
			self.assertEqual(
				definition["parameters"]["properties"]["value"]["type"], "string"
			)

	@patch("frappe_whatsapp_core.flow_actions.frappe.get_attr")
	@patch("frappe_whatsapp_core.flow_actions.frappe.get_hooks")
	def test_only_allowlisted_method_is_invoked(self, get_hooks, get_attr):
		get_hooks.return_value = {
			"example.record": "example_app.whatsapp_actions.record_example"
		}
		get_attr.return_value = lambda action_input, context: {
			"value": action_input["value"],
			"conversation": context["conversation"],
		}
		result = execute_registered_action(
			"example_app.whatsapp_actions.record_example",
			{"value": "captured"},
			context={"conversation": "CONV-1"},
		)
		self.assertEqual(result, {"value": "captured", "conversation": "CONV-1"})
		get_attr.assert_called_once_with("example_app.whatsapp_actions.record_example")

	@patch("frappe_whatsapp_core.flow_actions.frappe.get_attr")
	@patch("frappe_whatsapp_core.flow_actions.frappe.get_hooks")
	def test_action_can_receive_standard_flow_payload(self, get_hooks, get_attr):
		get_hooks.return_value = {
			"example.attach": "example_app.whatsapp_actions.attach_file"
		}
		get_attr.return_value = lambda action_input, flow_payload: {
			"value": action_input["value"],
			"attachment": flow_payload["last_input"]["value"]["file"],
		}
		result = execute_registered_action(
			"example.attach",
			{"value": "medical report"},
			flow_payload={"last_input": {"value": {"file": "FILE-1"}}},
		)
		self.assertEqual(result["attachment"], "FILE-1")

	def test_core_starter_flow_contains_no_business_action(self):
		for graph in BUILTIN_FLOWS.values():
			self.assertFalse(any(node.get("type") == "action" for node in graph["nodes"]))
			self.assertEqual(validate_graph(graph), [])

	def test_topic_action_groups_flow_messages_and_preserves_manual_assignments(self):
		suffix = frappe.generate_hash(length=10)
		channel = get_or_create_channel(f"topic-action-{suffix}")
		phone_suffix = f"{int(suffix, 36) % 100_000_000:08d}"
		identity = get_or_create_identity(f"9198{phone_suffix}")
		conversation = get_or_create_conversation(channel, identity)
		message = frappe.get_doc({
			"doctype": "WhatsApp Core Message",
			"message_key": f"topic-action-message-{suffix}",
			"conversation": conversation.name,
			"channel": channel.name,
			"provider_message_id": f"wamid.{suffix}",
			"direction": "Inbound",
			"message_type": "text",
			"body": "Feedback",
			"content": "{}",
			"provider_timestamp": frappe.utils.now_datetime(),
			"delivery_status": "Received",
		}).insert(ignore_permissions=True)
		context = {"inbound": {"message": message.name}, "inputs": {}}
		instance = type(
			"FlowInstance",
			(),
			{"name": f"FLOW-{suffix}", "flow": "FLOW", "conversation": conversation.name},
		)()

		result = execute_registered_action(
			"topic.upsert",
			{
				"topic_key": "retailer-feedback",
				"title": "Retailer feedback",
				"category": "Feedback",
				"status": "Resolved",
			},
			context=context,
			flow_instance=instance,
		)

		self.assertEqual(result["category"], "Feedback")
		self.assertEqual(result["messages"], 1)
		self.assertEqual(context["topics"]["retailer-feedback"], result["topic"])
		self.assertEqual(
			frappe.db.get_value("WhatsApp Core Topic Message", {"message": message.name}, "topic"),
			result["topic"],
		)
