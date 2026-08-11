"""Typed, allowlisted Python actions available to visual and Meta Flows."""

from __future__ import annotations

import inspect
from copy import deepcopy
from typing import Any

import frappe

from frappe_whatsapp_core.cases import create_case
from frappe_whatsapp_core.topics import upsert_topic

DEFAULT_ACTION_DEFINITIONS = {
	"case.create": {
		"label": "Create case",
		"method": "frappe_whatsapp_core.flow_actions.create_case_action",
		"description": "Create a configured WhatsApp Core case.",
		"parameters": {
			"type": "object",
			"required": ["case_type"],
			"properties": {
				"case_type": {"type": "string", "title": "Case type key"},
				"title": {"type": "string", "title": "Title"},
				"description": {"type": "string", "title": "Description"},
				"field_values": {"type": "object", "title": "Additional fields"},
			},
		},
	},
	"context.set": {
		"label": "Set context value",
		"method": "frappe_whatsapp_core.flow_actions.set_context_action",
		"description": "Store a value in the current flow context.",
		"parameters": {
			"type": "object",
			"required": ["key"],
			"properties": {
				"key": {"type": "string", "title": "Context key"},
				"value": {"title": "Context value"},
			},
		},
	},
	"topic.upsert": {
		"label": "Categorize conversation",
		"method": "frappe_whatsapp_core.flow_actions.upsert_topic_action",
		"description": "Group the current Flow messages into an auditable conversation topic.",
		"parameters": {
			"type": "object",
			"required": ["title"],
			"properties": {
				"topic_key": {"type": "string", "title": "Stable topic key"},
				"title": {"type": "string", "title": "Topic title"},
				"summary": {"type": "string", "title": "Summary"},
				"category": {"type": "string", "title": "Category"},
				"status": {"type": "string", "title": "Status"},
				"confidence": {"type": "number", "title": "Confidence"},
				"message_names": {"type": "array", "title": "Additional messages"},
			},
		},
	},
}


def registered_action_catalog() -> list[dict[str, Any]]:
	"""Return the complete action contract exposed to builders and MCP clients.

	A graph may reference either the stable action key or the dotted method path,
	but the path must be present in this allowlisted hook catalog. Merely knowing a
	Python path never grants a Flow permission to execute it.
	"""
	hooks = frappe.get_hooks("whatsapp_core_flow_actions") or {}
	if not isinstance(hooks, dict):
		return []

	catalog = []
	for key, raw_definition in hooks.items():
		definition = _normalize_definition(str(key), raw_definition)
		if definition:
			catalog.append(definition)
	return sorted(catalog, key=lambda item: (item["label"].casefold(), item["key"]))


def registered_actions() -> list[str]:
	return [definition["key"] for definition in registered_action_catalog()]


def action_definition(reference: str) -> dict[str, Any] | None:
	reference = str(reference or "").strip()
	for definition in registered_action_catalog():
		if reference in {definition["key"], definition["method"]}:
			return definition
	return None


def validate_registered_actions(graph: dict) -> list[str]:
	errors = []
	for node in graph.get("nodes", []):
		if node.get("type") != "action":
			continue
		config = node.get("config", {})
		reference = config.get("action") or config.get("method")
		definition = action_definition(reference)
		if not definition:
			errors.append(
				f"Node {node.get('id', '?')} uses an unregistered action: {reference}"
			)
			continue
		errors.extend(
			f"Node {node.get('id', '?')}: {error}"
			for error in validate_action_input(definition, config.get("input") or {})
		)
	return errors


def execute_registered_action(
	reference: str,
	action_input: dict[str, Any] | None,
	*,
	context: dict[str, Any] | None = None,
	flow_instance=None,
	flow_response=None,
	flow_payload: dict[str, Any] | None = None,
) -> Any:
	"""Validate and invoke one allowlisted action with a stable keyword contract."""
	definition = action_definition(reference)
	if not definition:
		frappe.throw(f"Flow action is not registered: {reference}", frappe.ValidationError)
	action_input = dict(action_input or {})
	errors = validate_action_input(definition, action_input)
	if errors:
		frappe.throw("; ".join(errors), frappe.ValidationError)
	handler = frappe.get_attr(definition["method"])
	available = {
		"action_input": action_input,
		"context": context or {},
		"flow_instance": flow_instance,
		"flow_response": flow_response,
		"flow_payload": flow_payload or {},
	}
	signature = inspect.signature(handler)
	if any(parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in signature.parameters.values()):
		return handler(**available)
	return handler(**{key: value for key, value in available.items() if key in signature.parameters})


def validate_action_input(definition: dict[str, Any], value: Any) -> list[str]:
	schema = definition.get("parameters") or {"type": "object"}
	if not isinstance(value, dict):
		return ["Action input must be an object"]
	errors = []
	properties = schema.get("properties") or {}
	for key in schema.get("required") or []:
		if key not in value or value[key] in (None, ""):
			errors.append(f"Action input requires {key}")
	for key, item in value.items():
		property_schema = properties.get(key)
		if not property_schema:
			if schema.get("additionalProperties") is False:
				errors.append(f"Action input does not allow {key}")
			continue
		expected = property_schema.get("type")
		if isinstance(item, dict) and set(item) == {"var"} and isinstance(item.get("var"), str):
			continue
		if expected and not _matches_json_type(item, expected):
			errors.append(f"Action input {key} must be {expected}")
	return errors


def create_case_action(action_input, context, flow_instance=None, flow_response=None):
	case_type = action_input["case_type"]
	conversation = getattr(flow_instance, "conversation", None)
	if not conversation and flow_response:
		conversation = getattr(flow_response, "conversation", None)
	title = action_input.get("title") or f"WhatsApp request from {conversation or 'Flow'}"
	field_values = dict(action_input.get("field_values") or {})
	if action_input.get("description"):
		field_values.setdefault("description", action_input["description"])
	case = create_case(case_type, title, field_values, conversation=conversation)
	return {"case": case.name, "case_type": case.case_type, "stage": case.stage_key}


def set_context_action(action_input, context, flow_instance=None, flow_response=None):
	key = action_input["key"]
	context.setdefault("variables", {})[key] = action_input.get("value")
	return {"key": key, "value": action_input.get("value")}


def upsert_topic_action(
	action_input,
	context,
	flow_instance=None,
	flow_response=None,
	flow_payload=None,
):
	"""Categorize a completed Flow without letting automation overwrite human work."""
	flow_payload = flow_payload or {}
	conversation = (
		getattr(flow_instance, "conversation", None)
		or getattr(flow_response, "conversation", None)
		or flow_payload.get("conversation")
		or context.get("conversation")
	)
	if not conversation:
		frappe.throw("A conversation is required to categorize a Flow", frappe.ValidationError)

	topic_key = str(action_input.get("topic_key") or action_input["title"]).strip().casefold()
	topic_names = context.setdefault("topics", {})
	message_names = _flow_message_names(action_input, context, conversation)
	attributes = {
		"topic_key": topic_key,
		"flow": getattr(flow_instance, "flow", None) or flow_payload.get("flow"),
		"flow_instance": getattr(flow_instance, "name", None) or flow_payload.get("flow_instance"),
		"trigger": (context.get("trigger") or {}).get("trigger_key"),
	}
	topic = upsert_topic(
		conversation=conversation,
		title=action_input["title"],
		summary=action_input.get("summary") or "",
		category=action_input.get("category") or "",
		status=action_input.get("status") or "Resolved",
		confidence=action_input.get("confidence", 100),
		message_names=message_names,
		source="Flow",
		topic_name=topic_names.get(topic_key),
		attributes=attributes,
	)
	topic_names[topic_key] = topic.name
	return {
		"topic": topic.name,
		"category": topic.category,
		"status": topic.status,
		"messages": topic.message_count,
	}


def _flow_message_names(action_input, context, conversation: str) -> list[str]:
	"""Collect only unclassified messages from this Flow's inbound event ledger."""
	candidates = list(action_input.get("message_names") or [])
	inbound = context.get("inbound") or {}
	if inbound.get("message"):
		candidates.append(inbound["message"])
	for input_record in (context.get("inputs") or {}).values():
		if isinstance(input_record, dict) and input_record.get("message"):
			candidates.append(input_record["message"])

	ordered_names = list(dict.fromkeys(
		message_name
		for candidate in candidates
		if (message_name := str(candidate or "").strip())
	))
	if not ordered_names:
		return []
	valid_names = {
		row.name
		for row in frappe.get_all(
			"WhatsApp Core Message",
			filters={"name": ["in", ordered_names], "conversation": conversation},
			fields=["name"],
			limit_page_length=len(ordered_names),
		)
	}
	assigned_names = {
		row.message
		for row in frappe.get_all(
			"WhatsApp Core Topic Message",
			filters={"message": ["in", ordered_names]},
			fields=["message"],
			limit_page_length=len(ordered_names),
		)
	}
	return [
		message_name
		for message_name in ordered_names
		if message_name in valid_names and message_name not in assigned_names
	]


def _normalize_definition(key: str, raw_definition) -> dict[str, Any] | None:
	if isinstance(raw_definition, (list, tuple)):
		raw_definition = raw_definition[-1] if raw_definition else None
	if isinstance(raw_definition, str):
		definition = deepcopy(DEFAULT_ACTION_DEFINITIONS.get(key) or {})
		definition["method"] = raw_definition
	elif isinstance(raw_definition, dict):
		definition = _normalize_hook_definition(raw_definition)
	else:
		return None
	method = str(definition.get("method") or definition.get("path") or "").strip()
	if not method or "." not in method:
		return None
	defaults = DEFAULT_ACTION_DEFINITIONS.get(key) or {}
	return {
		"key": key,
		"label": str(definition.get("label") or defaults.get("label") or key),
		"method": method,
		"description": str(definition.get("description") or defaults.get("description") or ""),
		"parameters": deepcopy(
			definition.get("parameters")
			or definition.get("input_schema")
			or defaults.get("parameters")
			or {"type": "object", "properties": {}}
		),
	}


def _normalize_hook_definition(raw_definition: dict[str, Any]) -> dict[str, Any]:
	"""Undo Frappe's singleton-list merge for scalar action metadata."""
	definition = deepcopy(raw_definition)
	for field in ("label", "method", "path", "description"):
		value = definition.get(field)
		if isinstance(value, (list, tuple)):
			definition[field] = value[-1] if value else None
	parameters = definition.get("parameters") or definition.get("input_schema")
	if isinstance(parameters, dict):
		definition["parameters"] = _normalize_json_schema(parameters)
	return definition


def _normalize_json_schema(schema: dict[str, Any]) -> dict[str, Any]:
	normalized = deepcopy(schema)
	for field in ("type", "title", "description", "format", "default", "additionalProperties"):
		value = normalized.get(field)
		if isinstance(value, (list, tuple)):
			normalized[field] = value[-1] if value else None
	properties = normalized.get("properties")
	if isinstance(properties, dict):
		normalized["properties"] = {
			name: _normalize_json_schema(value) if isinstance(value, dict) else value
			for name, value in properties.items()
		}
	if isinstance(normalized.get("items"), dict):
		normalized["items"] = _normalize_json_schema(normalized["items"])
	return normalized


def _matches_json_type(value: Any, expected: str) -> bool:
	if value is None:
		return True
	types = {
		"string": str,
		"object": dict,
		"array": list,
		"boolean": bool,
		"integer": int,
		"number": (int, float),
	}
	python_type = types.get(expected)
	if not python_type:
		return True
	if expected in {"integer", "number"} and isinstance(value, bool):
		return False
	return isinstance(value, python_type)
