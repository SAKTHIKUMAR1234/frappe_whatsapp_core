"""Built-in Core inbox, realtime and flow processing for every installed site."""

from __future__ import annotations

import json

import frappe

from frappe_whatsapp_core.flow_router import route_inbound
from frappe_whatsapp_core.outbound import (
	outbound_ready,
	queue_choice,
	queue_template_internal,
	queue_text_internal,
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
		],
		order_by="provider_timestamp asc",
		limit_page_length=500,
	)
	results = []
	for message in messages:
		frappe.publish_realtime(
			"whatsapp_core_message",
			{
				"conversation": message.conversation,
				"message": message,
			},
			after_commit=True,
		)
		flow_event = _flow_event(message)
		flow_result = (
			route_inbound(message.conversation, f"{event.name}:{message.name}", flow_event)
			if _legacy_automation_enabled() and not flow_event.get("meta_flow_response")
			else {"status": "skipped", "reason": "Meta-native Flow response" if flow_event.get("meta_flow_response") else "Legacy local automation disabled"}
		)
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
		"results": results,
	}


def _flow_event(message) -> dict:
	content = _json_dict(message.content)
	inbound = {
		"message": message.name,
		"type": message.message_type,
		"body": message.body or "",
	}
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


def _legacy_automation_enabled() -> bool:
	"""Local prompt-by-prompt flows are compatibility-only and opt-in."""
	return bool(frappe.conf.get("whatsapp_core_enable_legacy_automation", False))


def _dispatch_commands(
	conversation: str,
	commands: list[dict],
) -> list[dict]:
	results = []
	for command in commands:
		command_type = command.get("type")
		if command_type not in {
			"send_message",
			"send_template",
			"ask_text",
			"ask_choice",
		}:
			continue
		if not outbound_ready():
			results.append({
				"type": command_type,
				"status": "blocked",
				"reason": "Core outbound is not configured and enabled",
			})
			continue
		if command_type in {"send_message", "ask_text"}:
			message = queue_text_internal(
				conversation,
				command.get("message") or "",
				source="Core Flow",
			)
		elif command_type == "ask_choice":
			message = queue_choice(
				conversation,
				command.get("message") or "",
				command.get("options") or [],
				command.get("button_label") or "Choose",
			)
		else:
			message = queue_template_internal(
				conversation,
				command["template"],
				command.get("language", "en"),
				command.get("components"),
				source="Core Flow",
			)
		results.append({
			"type": command_type,
			"status": "queued",
			"message": message["name"],
		})
	return results


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
