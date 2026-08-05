"""Match tenant-local triggers and correlate replies to active flow instances."""

from __future__ import annotations

import fnmatch
from typing import Any

import frappe

from frappe_whatsapp_core.flows import resume_flow, start_flow


def route_inbound(
	conversation: str,
	event_key: str,
	event: dict[str, Any],
) -> dict[str, Any]:
	"""Resume the active conversation flow or start the best matching trigger."""
	active = frappe.db.get_value(
		"WhatsApp Core Flow Instance",
		{"conversation": conversation, "status": ["in", ["Running", "Waiting"]]},
		["name", "status"],
		as_dict=True,
		order_by="started_at desc",
	)
	if active:
		if active.status == "Waiting":
			return {
				"handled": True,
				"kind": "resume",
				**resume_flow(active.name, event_key, _extract_answer(event)),
			}
		return {
			"handled": True,
			"kind": "busy",
			"status": "running",
			"instance": active.name,
			"commands": [],
		}

	for trigger_type, value in _candidate_trigger_values(event):
		trigger = _find_trigger(trigger_type, value)
		if not trigger:
			continue
		result = start_flow(
			trigger.flow,
			conversation,
			event_key,
			{
				"trigger": {
					"type": trigger_type,
					"value": value,
					"trigger_key": trigger.trigger_key,
				},
				"inbound": event,
			},
		)
		return {"handled": True, "kind": "start", "trigger": trigger.trigger_key, **result}
	return {"handled": False, "kind": "unmatched", "commands": []}


def route_named_trigger(
	trigger_type: str,
	match_value: str,
	conversation: str,
	event_key: str,
	context: dict[str, Any] | None = None,
) -> dict[str, Any]:
	"""Start API, schedule or case-event flows without pretending they are messages."""
	trigger = _find_trigger(trigger_type, match_value)
	if not trigger:
		return {"handled": False, "kind": "unmatched", "commands": []}
	result = start_flow(
		trigger.flow,
		conversation,
		event_key,
		{
			**(context or {}),
			"trigger": {
				"type": trigger_type,
				"value": match_value,
				"trigger_key": trigger.trigger_key,
			},
		},
	)
	return {"handled": True, "kind": "start", "trigger": trigger.trigger_key, **result}


def _candidate_trigger_values(event: dict[str, Any]):
	interactive_id = (
		event.get("interactive_id")
		or event.get("button_id")
		or event.get("template_button_id")
	)
	if interactive_id:
		yield "template_button", str(interactive_id)
	body = str(event.get("body") or event.get("text") or "").strip()
	if body.startswith("/"):
		yield "command", body.split(maxsplit=1)[0]
	if body:
		yield "inbound_pattern", body


def _find_trigger(trigger_type: str, value: str):
	candidates = frappe.get_all(
		"WhatsApp Core Flow Trigger",
		filters={"trigger_type": trigger_type, "enabled": 1},
		fields=[
			"name",
			"trigger_key",
			"flow",
			"flow_version",
			"match_value",
			"priority",
		],
		order_by="priority asc, creation asc",
		limit_page_length=100,
	)
	for trigger in candidates:
		active_version = frappe.db.get_value(
			"WhatsApp Core Flow",
			{"name": trigger.flow, "enabled": 1, "status": "Published"},
			"active_version",
		)
		if active_version != trigger.flow_version:
			continue
		if _matches(trigger_type, trigger.match_value, value):
			return trigger
	return None


def _matches(trigger_type: str, configured: str, received: str) -> bool:
	configured = str(configured or "").strip()
	received = str(received or "").strip()
	if trigger_type in {"command", "template_button", "case_event", "api"}:
		return configured.casefold() == received.casefold()
	if trigger_type == "inbound_pattern":
		return fnmatch.fnmatchcase(received.casefold(), configured.casefold())
	return configured == received


def _extract_answer(event: dict[str, Any]) -> Any:
	return (
		event.get("button_id")
		or event.get("interactive_id")
		or event.get("interactive_value")
		or event.get("body")
		or event.get("text")
		or event
	)
