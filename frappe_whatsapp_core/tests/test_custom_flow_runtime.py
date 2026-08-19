import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, now_datetime

from frappe_whatsapp_core.core_event_handler import _dispatch_commands, _multi_select_prompt
from frappe_whatsapp_core.flow_router import route_inbound
from frappe_whatsapp_core.flows import _validate_answer, publish_flow, resume_flow
from frappe_whatsapp_core.materializer import (
	get_or_create_channel,
	get_or_create_conversation,
	get_or_create_identity,
)


def appointment_graph(command="/appointment"):
	return {
		"schema_version": 1,
		"triggers": [
			{"key": "appointment", "type": "command", "match": command, "priority": 10}
		],
		"nodes": [
			{"id": "start", "type": "start", "config": {}},
			{
				"id": "mode",
				"type": "ask_input",
				"config": {
					"message": "Choose an appointment action",
					"answer_key": "mode",
					"input_type": "radio",
					"options": [
						{"label": "Create", "value": "create"},
						{"label": "Check", "value": "check"},
						{"label": "Exit", "value": "exit"},
					],
				},
			},
			{"id": "mode_branch", "type": "condition", "config": {}},
			{
				"id": "number",
				"type": "ask_input",
				"config": {
					"message": "Enter a patient number",
					"answer_key": "patient_number",
					"input_type": "number",
					"minimum": 1,
					"integer_only": True,
				},
			},
			{
				"id": "report",
				"type": "ask_input",
				"config": {
					"message": "Attach a medical report",
					"answer_key": "report",
					"input_type": "attachment",
					"accepted_media_types": ["image", "document", "audio"],
				},
			},
			{
				"id": "more",
				"type": "ask_input",
				"config": {
					"message": "Attach another report?",
					"answer_key": "more",
					"input_type": "radio",
					"options": [
						{"label": "Another", "value": "yes"},
						{"label": "Finish", "value": "no"},
					],
				},
			},
			{"id": "more_branch", "type": "condition", "config": {}},
			{
				"id": "remember",
				"type": "action",
				"config": {
					"action": "context.set",
					"input": {"key": "last_report", "value": {"var": "inputs.report.value"}},
					"output_key": "stored_report",
				},
			},
			{
				"id": "end",
				"type": "end",
				"config": {"message": "Appointment request {{answers.patient_number}} recorded."},
			},
			{"id": "exit", "type": "end", "config": {"message": "No changes made."}},
		],
		"edges": [
			{"id": "e1", "source": "start", "target": "mode"},
			{"id": "e2", "source": "mode", "target": "mode_branch"},
			{
				"id": "e3",
				"source": "mode_branch",
				"target": "number",
				"when": {"op": "eq", "left": {"var": "answers.mode"}, "right": "create"},
			},
			{"id": "e4", "source": "mode_branch", "target": "exit", "default": True},
			{"id": "e5", "source": "number", "target": "report"},
			{"id": "e6", "source": "report", "target": "more"},
			{"id": "e7", "source": "more", "target": "more_branch"},
			{
				"id": "e8",
				"source": "more_branch",
				"target": "report",
				"when": {"op": "eq", "left": {"var": "answers.more"}, "right": "yes"},
				"max_traversals": 3,
			},
			{"id": "e9", "source": "more_branch", "target": "remember", "default": True},
			{"id": "e10", "source": "remember", "target": "end"},
		],
	}


class TestCustomFlowRuntime(FrappeTestCase):
	def test_content_input_accepts_text_buttons_and_cached_media(self):
		node = {
			"type": "ask_input",
			"config": {
				"input_type": "content",
				"accepted_media_types": ["image", "document", "audio", "sticker"],
			},
		}
		self.assertEqual(_validate_answer(node, "Machine stopped"), (True, "Machine stopped", None))
		self.assertEqual(
			_validate_answer(node, {"button_id": "finalize"}),
			(True, "finalize", None),
		)

		with patch(
			"frappe_whatsapp_core.message_media.cache_message_media",
			return_value=frappe._dict(
				name="FILE-CONTENT",
				file_name="photo.jpg",
				file_url="/private/files/photo.jpg",
				content_type="image/jpeg",
			),
		):
			ok, value, error = _validate_answer(node, {
				"type": "image",
				"message": "MSG-CONTENT",
				"body": "Control panel",
				"media": {"id": "MEDIA-CONTENT", "filename": "photo.jpg"},
			})
		self.assertTrue(ok)
		self.assertIsNone(error)
		self.assertEqual(value["file"], "FILE-CONTENT")
		self.assertEqual(value["caption"], "Control panel")

	def test_multi_select_accepts_numbers_labels_values_and_deduplicates(self):
		node = {
			"type": "ask_input",
			"config": {
				"input_type": "multi_select",
				"options": [
					{"label": "Gym Vest", "value": "gym_vest"},
					{"label": "Innerwear", "value": "innerwear"},
					{"label": "Winterwear", "value": "winterwear"},
				],
			},
		}
		ok, value, error = _validate_answer(node, "1, innerwear; Gym Vest")
		self.assertTrue(ok)
		self.assertEqual(value, ["gym_vest", "innerwear"])
		self.assertIsNone(error)
		self.assertFalse(_validate_answer(node, "unknown")[0])
		prompt = _multi_select_prompt({
			"message": "Choose categories",
			"options": node["config"]["options"],
		})
		self.assertIn("1. Gym Vest", prompt)
		self.assertIn("separated by commas", prompt)

	def setUp(self):
		suffix = frappe.generate_hash(length=10)
		channel = get_or_create_channel(f"custom-flow-{suffix}")
		number_suffix = frappe.utils.now_datetime().strftime("%H%M%S%f")[-10:]
		identity = get_or_create_identity(f"9196{number_suffix}")
		self.conversation = get_or_create_conversation(channel, identity)
		self.command = f"/appointment-{suffix}"
		self.flow = frappe.get_doc({
			"doctype": "WhatsApp Core Flow",
			"flow_key": f"test.appointment.{suffix}",
			"title": "Appointment",
			"status": "Draft",
			"approval_status": "Draft",
			"enabled": 1,
			"draft_graph": json.dumps(appointment_graph(self.command)),
		}).insert(ignore_permissions=True)
		publish_flow(self.flow.name)

	@patch("frappe_whatsapp_core.core_event_handler.outbound_ready", return_value=True)
	def test_transport_service_flow_reply_does_not_require_operator_role(self, _outbound_ready):
		frappe.db.set_value(
			"WhatsApp Core Conversation",
			self.conversation.name,
			"last_inbound_at",
			now_datetime(),
			update_modified=False,
		)
		transport_user = f"flow-transport-{frappe.generate_hash(length=8).lower()}@example.invalid"
		frappe.get_doc({
			"doctype": "User",
			"email": transport_user,
			"first_name": "Flow Transport",
			"enabled": 1,
			"user_type": "Website User",
			"send_welcome_email": 0,
			"roles": [{"role": "WhatsApp Core Transport Service"}],
		}).insert(ignore_permissions=True)
		frappe.set_user(transport_user)
		try:
			result = _dispatch_commands(
				self.conversation.name,
				[{"type": "send_message", "message": "Trusted flow reply"}],
			)
		finally:
			frappe.set_user("Administrator")

		self.assertEqual(result[0]["status"], "queued")
		self.assertEqual(
			frappe.db.get_value("WhatsApp Core Message", result[0]["message"], "body"),
			"Trusted flow reply",
		)

	def test_typed_attachment_loop_action_and_final_response(self):
		started = route_inbound(
			self.conversation.name,
			"event:start",
			{"type": "text", "body": self.command},
		)
		self.assertEqual(started["commands"][-1]["type"], "ask_input")
		self.assertEqual(resume_flow(started["instance"], "event:mode", "create")["status"], "waiting")

		invalid = resume_flow(started["instance"], "event:invalid", "not-a-number")
		self.assertEqual(invalid["status"], "invalid")
		self.assertIn("valid number", invalid["commands"][0]["message"])
		self.assertEqual(resume_flow(started["instance"], "event:number", "42")["status"], "waiting")

		def cached_file(message_name):
			return frappe._dict(
				name=f"FILE-{message_name}",
				file_name=f"{message_name}.jpg",
				file_url=f"/private/files/{message_name}.jpg",
				content_type="image/jpeg",
			)

		with patch(
			"frappe_whatsapp_core.message_media.cache_message_media",
			side_effect=cached_file,
		):
			first = resume_flow(started["instance"], "event:report-1", {
				"type": "image",
				"message": "MSG-1",
				"body": "First report",
				"media": {"id": "MEDIA-1", "filename": "report-1.jpg"},
			})
			self.assertEqual(first["status"], "waiting")
			self.assertEqual(resume_flow(started["instance"], "event:more-1", "yes")["status"], "waiting")
			second = resume_flow(started["instance"], "event:report-2", {
				"type": "image",
				"message": "MSG-2",
				"body": "Second report",
				"media": {"id": "MEDIA-2", "filename": "report-2.jpg"},
			})
			self.assertEqual(second["status"], "waiting")

		completed = resume_flow(started["instance"], "event:more-2", "no")
		self.assertEqual(completed["status"], "completed")
		self.assertEqual(completed["commands"][-1]["message"], "Appointment request 42 recorded.")
		context = json.loads(
			frappe.db.get_value("WhatsApp Core Flow Instance", started["instance"], "context")
		)
		self.assertEqual(len(context["attachments"]), 2)
		self.assertEqual(context["variables"]["last_report"]["file"], "FILE-MSG-2")

	def test_exit_command_cancels_active_flow(self):
		started = route_inbound(
			self.conversation.name,
			"event:start",
			{"type": "text", "body": self.command},
		)
		cancelled = route_inbound(
			self.conversation.name,
			"event:exit",
			{"type": "text", "body": "/exit"},
		)
		self.assertEqual(cancelled["kind"], "exit")
		self.assertEqual(cancelled["status"], "cancelled")
		self.assertEqual(
			frappe.db.get_value("WhatsApp Core Flow Instance", started["instance"], "status"),
			"Cancelled",
		)

	def test_invalid_webhook_retry_is_idempotent(self):
		started = route_inbound(
			self.conversation.name,
			"event:start",
			{"type": "text", "body": self.command},
		)
		resume_flow(started["instance"], "event:mode", "create")
		first = resume_flow(started["instance"], "event:invalid", "not-a-number")
		second = resume_flow(started["instance"], "event:invalid", "not-a-number")
		self.assertEqual(first["status"], "invalid")
		self.assertEqual(second["status"], "duplicate")
		self.assertEqual(second["commands"], [])

	def test_expired_instance_does_not_block_a_new_trigger(self):
		started = route_inbound(
			self.conversation.name,
			"event:start",
			{"type": "text", "body": self.command},
		)
		frappe.db.set_value(
			"WhatsApp Core Flow Instance",
			started["instance"],
			"expires_at",
			add_to_date(now_datetime(), days=-1),
			update_modified=False,
		)
		restarted = route_inbound(
			self.conversation.name,
			"event:restart",
			{"type": "text", "body": self.command},
		)
		self.assertEqual(restarted["kind"], "start")
		self.assertNotEqual(restarted["instance"], started["instance"])
		self.assertEqual(
			frappe.db.get_value("WhatsApp Core Flow Instance", started["instance"], "status"),
			"Expired",
		)

	def test_publishing_same_active_trigger_in_another_flow_is_rejected(self):
		suffix = frappe.generate_hash(length=10)
		second = frappe.get_doc({
			"doctype": "WhatsApp Core Flow",
			"flow_key": f"test.trigger-collision.{suffix}",
			"title": "Trigger collision",
			"status": "Draft",
			"approval_status": "Draft",
			"enabled": 1,
			"draft_graph": json.dumps(appointment_graph(self.command.upper())),
		}).insert(ignore_permissions=True)
		with self.assertRaises(frappe.ValidationError):
			publish_flow(second.name)
