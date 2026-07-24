"""Versioned, tenant-local WhatsApp flow publication and execution foundation."""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

import frappe
from frappe.utils import add_to_date, now

from frappe_whatsapp_core.flow_schema import (
	QUESTION_TYPES,
	assert_valid_graph,
	evaluate_condition,
	validate_graph,
)


MAX_AUTOMATIC_STEPS = 50


def canonical_json(value: Any) -> str:
	return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def graph_sha256(graph: dict[str, Any]) -> str:
	return hashlib.sha256(canonical_json(graph).encode()).hexdigest()


def validate_flow_graph(graph: dict[str, Any] | str) -> list[str]:
	return validate_graph(_as_dict(graph))


def publish_flow(flow_name: str) -> dict[str, Any]:
	"""Publish an immutable graph version and atomically activate it."""
	flow = frappe.get_doc("WhatsApp Core Flow", flow_name)
	graph = _as_dict(flow.draft_graph)
	assert_valid_graph(graph)
	digest = graph_sha256(graph)

	current = None
	if flow.active_version:
		current = frappe.get_doc("WhatsApp Core Flow Version", flow.active_version)
		if current.graph_sha256 == digest:
			return {
				"flow": flow.name,
				"version": current.version_number,
				"flow_version": current.name,
				"sha256": digest,
				"status": "unchanged",
			}

	version_number = (
		frappe.db.sql(
			"""
			select coalesce(max(version_number), 0)
			from `tabWhatsApp Core Flow Version`
			where flow = %s
			""",
			flow.name,
		)[0][0]
		+ 1
	)
	version_key = f"{flow.flow_key}:v{version_number}"
	version = frappe.get_doc({
		"doctype": "WhatsApp Core Flow Version",
		"version_key": version_key,
		"flow": flow.name,
		"version_number": version_number,
		"status": "Published",
		"graph": canonical_json(graph),
		"graph_sha256": digest,
		"published_at": now(),
		"published_by": frappe.session.user,
	}).insert(ignore_permissions=True)

	for trigger in graph.get("triggers", []):
		frappe.get_doc({
			"doctype": "WhatsApp Core Flow Trigger",
			"trigger_key": f"{version_key}:{trigger['key']}",
			"flow": flow.name,
			"flow_version": version.name,
			"trigger_type": trigger["type"],
			"match_value": trigger.get("match", ""),
			"priority": trigger.get("priority", 100),
			"config": canonical_json(trigger.get("config", {})),
			"enabled": 1,
		}).insert(ignore_permissions=True)

	if current:
		current.status = "Superseded"
		current.save(ignore_permissions=True)
	flow.active_version = version.name
	flow.status = "Published"
	flow.save(ignore_permissions=True)
	return {
		"flow": flow.name,
		"version": version_number,
		"flow_version": version.name,
		"sha256": digest,
		"status": "published",
	}


def start_flow(
	flow_name: str,
	conversation: str,
	event_key: str,
	initial_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
	"""Start the active version; running instances remain pinned to that version."""
	flow = frappe.get_doc("WhatsApp Core Flow", flow_name)
	if not flow.enabled or flow.status != "Published" or not flow.active_version:
		frappe.throw("Flow is not published and enabled")
	if frappe.db.exists(
		"WhatsApp Core Flow Instance",
		{"conversation": conversation, "status": ["in", ["Running", "Waiting"]]},
	):
		frappe.throw("This conversation already has an active flow")

	context = dict(initial_context or {})
	context.setdefault("answers", {})
	context.setdefault("edge_visits", {})
	version = frappe.get_doc("WhatsApp Core Flow Version", flow.active_version)
	graph = _as_dict(version.graph)
	start_node = next(node for node in graph["nodes"] if node["type"] == "start")
	instance = frappe.get_doc({
		"doctype": "WhatsApp Core Flow Instance",
		"instance_key": str(uuid.uuid4()),
		"flow": flow.name,
		"flow_version": version.name,
		"conversation": conversation,
		"status": "Running",
		"current_node_id": start_node["id"],
		"context": canonical_json(context),
		"lock_version": 0,
		"last_event_key": event_key,
		"started_at": now(),
		"last_activity_at": now(),
		"expires_at": add_to_date(now(), days=7),
	}).insert(ignore_permissions=True)
	return advance_instance(instance.name, event_key)


def resume_flow(
	instance_name: str,
	event_key: str,
	answer: Any,
) -> dict[str, Any]:
	"""Validate one reply and continue exactly once."""
	instance = _lock_instance(instance_name)
	if instance.status not in {"Waiting", "Running"}:
		return {"status": instance.status.lower(), "instance": instance.name, "commands": []}
	if instance.last_event_key == event_key:
		return {"status": "duplicate", "instance": instance.name, "commands": []}

	graph = _as_dict(frappe.db.get_value("WhatsApp Core Flow Version", instance.flow_version, "graph"))
	node = _node_by_id(graph, instance.current_node_id)
	if node["type"] not in QUESTION_TYPES and node["type"] != "wait":
		frappe.throw("Flow is not waiting for a reply")

	context = _as_dict(instance.context)
	if node["type"] in QUESTION_TYPES:
		ok, normalized, error = _validate_answer(node, answer)
		if not ok:
			return {
				"status": "invalid",
				"instance": instance.name,
				"commands": [{
					"type": "send_message",
					"message": error or node.get("config", {}).get("validation_message", "Please try again."),
				}],
			}
		context.setdefault("answers", {})[node["config"]["answer_key"]] = normalized
	else:
		context.setdefault("events", {})[event_key] = answer

	instance.context = canonical_json(context)
	instance.status = "Running"
	instance.last_event_key = event_key
	instance.last_activity_at = now()
	instance.lock_version = (instance.lock_version or 0) + 1
	instance.save(ignore_permissions=True)
	return advance_instance(instance.name, event_key, move_from_current=True)


def advance_instance(
	instance_name: str,
	event_key: str,
	move_from_current: bool = False,
) -> dict[str, Any]:
	"""Execute deterministic nodes until the next question/wait/end boundary."""
	instance = _lock_instance(instance_name)
	graph = _as_dict(frappe.db.get_value("WhatsApp Core Flow Version", instance.flow_version, "graph"))
	node = _node_by_id(graph, instance.current_node_id)
	context = _as_dict(instance.context)
	commands: list[dict[str, Any]] = []

	if move_from_current:
		node = _select_next_node(graph, node, context)

	for _ in range(MAX_AUTOMATIC_STEPS):
		run_key = hashlib.sha256(
			f"{instance.name}:{node['id']}:{event_key}:{instance.lock_version}".encode()
		).hexdigest()
		if frappe.db.exists("WhatsApp Core Flow Step Run", run_key):
			return {"status": "duplicate", "instance": instance.name, "commands": commands}
		run = _start_step_run(run_key, instance, node, event_key, context)
		try:
			node_type = node["type"]
			config = node.get("config", {})
			if node_type in {"send_message", "send_template"}:
				command = {
					"type": node_type,
					**config,
					"correlation": {"flow_instance": instance.name, "node_id": node["id"]},
				}
				commands.append(command)
				_complete_step_run(run, {"command": command})
				node = _select_next_node(graph, node, context)
				continue
			if node_type in QUESTION_TYPES:
				command = {
					"type": node_type,
					**config,
					"correlation": {"flow_instance": instance.name, "node_id": node["id"]},
				}
				commands.append(command)
				_complete_step_run(run, {"command": command})
				_save_instance(instance, node["id"], "Waiting", context, event_key)
				return {"status": "waiting", "instance": instance.name, "commands": commands}
			if node_type == "wait":
				_complete_step_run(run, {"resume_on": config["resume_on"]})
				_save_instance(instance, node["id"], "Waiting", context, event_key)
				return {"status": "waiting", "instance": instance.name, "commands": commands}
			if node_type == "action":
				result = _execute_action(config["action"], config.get("input", {}), context, instance)
				output_key = config.get("output_key")
				if output_key:
					context.setdefault("actions", {})[output_key] = result
				_complete_step_run(run, result)
				node = _select_next_node(graph, node, context)
				continue
			if node_type == "condition" or node_type == "start":
				_complete_step_run(run, {})
				node = _select_next_node(graph, node, context)
				continue
			if node_type == "human_handoff":
				_complete_step_run(run, {"reason": config.get("reason")})
				_save_instance(instance, node["id"], "Completed", context, event_key)
				return {
					"status": "human_handoff",
					"instance": instance.name,
					"commands": commands,
				}
			if node_type == "end":
				_complete_step_run(run, {})
				_save_instance(instance, node["id"], "Completed", context, event_key)
				return {"status": "completed", "instance": instance.name, "commands": commands}
			frappe.throw(f"Unsupported node type: {node_type}")
		except Exception:
			run.status = "Failed"
			run.error = frappe.get_traceback()
			run.completed_at = now()
			run.save(ignore_permissions=True)
			instance.status = "Failed"
			instance.error = run.error
			instance.save(ignore_permissions=True)
			raise

	frappe.throw(f"Flow exceeded {MAX_AUTOMATIC_STEPS} automatic steps")


def _select_next_node(
	graph: dict[str, Any], node: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
	edges = [edge for edge in graph["edges"] if edge["source"] == node["id"]]
	for edge in sorted(edges, key=lambda item: item.get("priority", 100)):
		if edge.get("default") is True:
			continue
		if "when" not in edge or evaluate_condition(edge["when"], context):
			_check_cycle_guard(edge, context)
			return _node_by_id(graph, edge["target"])
	default = next((edge for edge in edges if edge.get("default") is True), None)
	if default:
		_check_cycle_guard(default, context)
		return _node_by_id(graph, default["target"])
	frappe.throw(f"No branch matched node {node['id']}")


def _validate_answer(node: dict[str, Any], answer: Any) -> tuple[bool, Any, str | None]:
	config = node.get("config", {})
	if node["type"] == "ask_text":
		value = str(answer or "").strip()
		if config.get("required", True) and not value:
			return False, value, config.get("validation_message") or "A reply is required."
		min_length = int(config.get("min_length", 0))
		max_length = int(config.get("max_length", 4096))
		if not min_length <= len(value) <= max_length:
			return False, value, config.get("validation_message") or "That reply is not valid."
		return True, value, None
	options = config.get("options", [])
	allowed = {
		str(option.get("value", option.get("label"))) if isinstance(option, dict) else str(option)
		for option in options
	}
	value = str(answer)
	if value not in allowed:
		return False, value, config.get("validation_message") or "Please select one of the options."
	return True, value, None


def _execute_action(
	action_key: str,
	action_input: dict[str, Any],
	context: dict[str, Any],
	instance,
) -> Any:
	handlers = frappe.get_hooks("whatsapp_core_flow_actions") or {}
	handler_path = handlers.get(action_key) if isinstance(handlers, dict) else None
	if not handler_path:
		frappe.throw(f"Flow action is not registered: {action_key}")
	if isinstance(handler_path, (list, tuple)):
		handler_path = handler_path[-1]
	handler = frappe.get_attr(handler_path)
	return handler(
		action_input=_resolve_action_input(action_input, context),
		context=context,
		flow_instance=instance,
	)


def _check_cycle_guard(edge: dict[str, Any], context: dict[str, Any]) -> None:
	if "max_traversals" not in edge:
		return
	visits = context.setdefault("edge_visits", {})
	visits[edge["id"]] = visits.get(edge["id"], 0) + 1
	if visits[edge["id"]] > edge["max_traversals"]:
		frappe.throw(f"Flow cycle limit exceeded at edge {edge['id']}")


def _start_step_run(run_key, instance, node, event_key, context):
	return frappe.get_doc({
		"doctype": "WhatsApp Core Flow Step Run",
		"run_key": run_key,
		"flow_instance": instance.name,
		"node_id": node["id"],
		"node_type": node["type"],
		"event_key": event_key,
		"status": "Processing",
		"attempts": 1,
		"input": canonical_json(context),
		"started_at": now(),
	}).insert(ignore_permissions=True)


def _complete_step_run(run, output: Any) -> None:
	run.status = "Completed"
	run.output = canonical_json(output)
	run.completed_at = now()
	run.save(ignore_permissions=True)


def _save_instance(instance, node_id, status, context, event_key) -> None:
	instance.current_node_id = node_id
	instance.status = status
	instance.context = canonical_json(context)
	instance.last_event_key = event_key
	instance.last_activity_at = now()
	instance.lock_version = (instance.lock_version or 0) + 1
	if status == "Completed":
		instance.completed_at = now()
	instance.save(ignore_permissions=True)


def _lock_instance(instance_name: str):
	frappe.db.sql(
		"select name from `tabWhatsApp Core Flow Instance` where name = %s for update",
		instance_name,
	)
	return frappe.get_doc("WhatsApp Core Flow Instance", instance_name)


def _node_by_id(graph: dict[str, Any], node_id: str) -> dict[str, Any]:
	for node in graph["nodes"]:
		if node["id"] == node_id:
			return node
	raise ValueError(f"Unknown flow node: {node_id}")


def _as_dict(value: dict[str, Any] | str | None) -> dict[str, Any]:
	if isinstance(value, dict):
		return value
	if not value:
		return {}
	return json.loads(value)


def _resolve_action_input(value: Any, context: dict[str, Any]) -> Any:
	if isinstance(value, dict):
		if set(value) == {"var"}:
			current: Any = context
			for part in value["var"].split("."):
				if not isinstance(current, dict) or part not in current:
					return None
				current = current[part]
			return current
		return {key: _resolve_action_input(item, context) for key, item in value.items()}
	if isinstance(value, list):
		return [_resolve_action_input(item, context) for item in value]
	return value
