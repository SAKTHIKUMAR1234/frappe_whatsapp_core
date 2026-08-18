"""Built-in Core inbox, realtime and flow processing for every installed site."""

from __future__ import annotations

import json

import frappe

from frappe_whatsapp_core.consent import is_opt_out_event, suppress_conversation
from frappe_whatsapp_core.flow_responses import (
	complete_meta_submission,
	record_meta_submission,
)
from frappe_whatsapp_core.flow_router import route_inbound
from frappe_whatsapp_core.message_media import media_descriptor
from frappe_whatsapp_core.outbound import (
	outbound_ready,
	queue_choice,
	queue_rich_internal,
	queue_template_internal,
	queue_text_internal,
)
from frappe_whatsapp_core.realtime import (
	publish_call_changes,
	publish_invalidation,
	publish_message_changes,
)


def handle_core_event(payload, event) -> dict:
	messages = frappe.get_all(
		"WhatsApp Core Message",
		filters={
			"relay_event": event.name,
			"direction": "Inbound",
		},
		fields=[
			"name",
			"conversation",
			"message_type",
			"body",
			"content",
			"provider_timestamp",
			"delivery_status",
			"channel",
		],
		order_by="provider_timestamp asc",
		limit_page_length=500,
	)
	results = []
	calls = frappe.get_all(
		"WhatsApp Core Call",
		filters={"relay_event": event.name},
		fields=[
			"name", "call_id", "channel", "direction", "status", "remote_number",
			"remote_user_id", "remote_username", "started_at", "ended_at", "session",
			"recording_media_id", "transcript_media_id", "last_event",
		],
		order_by="modified asc",
		limit_page_length=100,
	)
	if calls and not frappe.flags.whatsapp_core_batch_processing:
		publish_call_changes([call.name for call in calls])
	groups = frappe.get_all(
		"WhatsApp Core Group",
		filters={"relay_event": event.name},
		fields=[
			"name", "group_id", "channel", "subject", "status", "participant_count",
			"last_event_type", "last_synced",
		],
		limit_page_length=100,
	)
	for group in groups:
		if not frappe.flags.whatsapp_core_batch_processing:
			publish_invalidation("whatsapp_core_group")
	for message in messages:
		if not frappe.flags.whatsapp_core_batch_processing:
			publish_message_changes([{
				"kind": "message",
				"status": "created",
				"name": message.name,
			}])
		flow_event = _flow_event(message)
		response_doc = (
			record_meta_submission(message, event, flow_event)
			if flow_event.get("meta_flow_response")
			else None
		)
		try:
			event_key = f"{event.name}:{message.name}"
			flow_result = (
				{
					"handled": True,
					"kind": "opt_out",
					"commands": [],
					**suppress_conversation(message.conversation, event_key),
				}
				if is_opt_out_event(flow_event)
				else route_inbound(message.conversation, event_key, flow_event)
				if _automation_enabled() or flow_event.get("meta_flow_response")
				else {"status": "skipped", "reason": "Visual automation disabled"}
			)
			if response_doc:
				complete_meta_submission(response_doc, flow_result)
		except Exception as exception:
			if response_doc:
				complete_meta_submission(response_doc, error=str(exception))
			raise
		results.append({
			"message": message.name,
			"flow": flow_result,
			"outbound": _dispatch_commands(
				message.conversation,
				flow_result.get("commands") or [],
			),
		})
	return {
		"status": "success",
		"kind": "core",
		"messages": len(messages),
		"calls": len(calls),
		"groups": len(groups),
		"results": results,
	}


def _flow_event(message) -> dict:
	content = _json_dict(message.content)
	inbound = {
		"message": message.name,
		"type": message.message_type,
		"body": message.body or "",
		"channel": message.channel,
		"content": content,
	}
	media = media_descriptor(message.message_type, content)
	if media:
		inbound["media"] = media
	if message.message_type == "button":
		button = content.get("button") or {}
		inbound.update({
			"button_id": button.get("payload") or button.get("text"),
			"interactive_value": button.get("text"),
		})
	if message.message_type == "interactive":
		interactive = content.get("interactive") or {}
		reply = (
			interactive.get("button_reply")
			or interactive.get("list_reply")
			or {}
		)
		inbound.update({
			"interactive_id": reply.get("id"),
			"interactive_value": reply.get("title") or reply.get("id"),
		})
		flow_reply = interactive.get("nfm_reply") or {}
		if flow_reply:
			response = flow_reply.get("response_json")
			try:
				response = json.loads(response) if isinstance(response, str) else response
			except (TypeError, ValueError):
				pass
			inbound.update({
				"meta_flow_response": True,
				"flow_token": flow_reply.get("flow_token"),
				"flow_name": flow_reply.get("name"),
				"flow_response": response,
			})
	return inbound


def _automation_enabled() -> bool:
	"""Visual automation is enabled unless the site explicitly disables it."""
	return bool(frappe.conf.get("whatsapp_core_enable_automation", True))


def _dispatch_commands(
	conversation: str,
	commands: list[dict],
) -> list[dict]:
	results = []
	conversation_doc = frappe.get_doc("WhatsApp Core Conversation", conversation)
	channel = conversation_doc.channel
	# The signed transport endpoint already authenticated a dedicated machine
	# principal before the event reached this handler.  Flow-generated replies
	# must not be forced through an operator's row permission check: the transport
	# user intentionally owns no Desk roles.  A private batch context bypasses
	# only that duplicate check while retaining channel/account validation and
	# the durable outbound queue.
	trusted_context = {"conversation": conversation_doc}
	for command in commands:
		command_type = command.get("type")
		if command_type not in {
			"send_message",
			"send_template",
			"send_flow",
			"ask_text",
			"ask_choice",
			"ask_input",
		}:
			continue
		if not outbound_ready(channel):
			results.append({
				"type": command_type,
				"status": "blocked",
				"reason": "Core outbound is not configured and enabled",
			})
			continue
		if command_type in {"send_message", "ask_text"} or (
			command_type == "ask_input"
			and command.get("input_type", "text")
			in {"text", "number", "multi_select", "attachment"}
		):
			message = queue_text_internal(
				conversation,
				_multi_select_prompt(command)
				if command.get("input_type") == "multi_select"
				else command.get("message") or "",
				source="Core Flow",
				_batch_context=trusted_context,
			)
		elif command_type == "ask_choice" or command_type == "ask_input":
			message = queue_choice(
				conversation,
				command.get("message") or "",
				command.get("options") or [],
				command.get("button_label") or "Choose",
				_batch_context=trusted_context,
			)
		elif command_type == "send_template":
			message = queue_template_internal(
				conversation,
				command["template"],
				command.get("language", "en"),
				command.get("components"),
				source="Core Flow",
				_batch_context=trusted_context,
			)
		else:
			flow_action = command.get("flow_action") or "navigate"
			parameters = {
				"flow_message_version": "3",
				"flow_id": command["flow_id"],
				"flow_token": command["flow_token"],
				"flow_cta": command.get("flow_cta") or "Open",
				"flow_action": flow_action,
			}
			if flow_action == "navigate":
				flow_action_payload = {"screen": command.get("screen") or ""}
				# Meta rejects an explicitly empty ``data`` value for a Flow CTA
				# (131009: it must be a dynamic_object). The field is optional for
				# static screens, so only send it when the Flow actually has data.
				if command.get("data"):
					flow_action_payload["data"] = command["data"]
				parameters["flow_action_payload"] = flow_action_payload
			message = queue_rich_internal(
				conversation,
				"interactive",
				{
					"type": "flow",
					"body": {"text": command.get("body") or "Please complete this form."},
					"action": {"name": "flow", "parameters": parameters},
				},
				command.get("body") or "Please complete this form.",
				source="Core Flow",
				_batch_context=trusted_context,
			)
		results.append({
			"type": command_type,
			"status": "queued",
			"message": message["name"],
		})
	return results


def _multi_select_prompt(command: dict) -> str:
	"""Render deterministic multi-choice input for WhatsApp's single-select controls."""
	lines = [str(command.get("message") or "").strip()]
	for index, option in enumerate(command.get("options") or [], start=1):
		label = option.get("label") if isinstance(option, dict) else option
		lines.append(f"{index}. {label}")
	lines.append("Reply with one or more option numbers separated by commas.")
	return "\n".join(line for line in lines if line)


def _json_dict(value) -> dict:
	if isinstance(value, dict):
		return dict(value)
	if not value:
		return {}
	try:
		parsed = json.loads(value)
		return parsed if isinstance(parsed, dict) else {}
	except (TypeError, ValueError):
		return {}
