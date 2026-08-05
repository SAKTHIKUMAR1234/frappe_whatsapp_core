"""Small, typed Core actions available to every solution pack."""

import frappe

from frappe_whatsapp_core.cases import create_case


def registered_actions() -> list[str]:
	handlers = frappe.get_hooks("whatsapp_core_flow_actions") or {}
	return sorted(handlers) if isinstance(handlers, dict) else []


def validate_registered_actions(graph: dict) -> list[str]:
	registered = set(registered_actions())
	return [
		f"Node {node.get('id', '?')} uses an unregistered action: "
		f"{node.get('config', {}).get('action')}"
		for node in graph.get("nodes", [])
		if node.get("type") == "action"
		and node.get("config", {}).get("action") not in registered
	]


def create_case_action(action_input, context, flow_instance):
	case_type = action_input["case_type"]
	title = action_input.get("title") or f"WhatsApp request from {flow_instance.conversation}"
	field_values = dict(action_input.get("field_values") or {})
	if action_input.get("description"):
		field_values.setdefault("description", action_input["description"])
	case = create_case(
		case_type,
		title,
		field_values,
		conversation=flow_instance.conversation,
	)
	return {"case": case.name, "case_type": case.case_type, "stage": case.stage_key}


def set_context_action(action_input, context, flow_instance):
	key = action_input["key"]
	context.setdefault("variables", {})[key] = action_input.get("value")
	return {"key": key, "value": action_input.get("value")}
