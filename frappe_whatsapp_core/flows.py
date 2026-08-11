"""Versioned, tenant-local WhatsApp flow publication and execution foundation."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from decimal import Decimal, InvalidOperation
from typing import Any

import frappe
from frappe.utils import add_to_date, get_datetime, now, now_datetime

from frappe_whatsapp_core.flow_actions import execute_registered_action, validate_registered_actions
from frappe_whatsapp_core.flow_responses import upsert_instance_response
from frappe_whatsapp_core.flow_schema import (
	ATTACHMENT_TYPES,
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
	action_errors = validate_registered_actions(graph)
	if action_errors:
		frappe.throw("<br>".join(action_errors), frappe.ValidationError)
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
	_assert_triggers_available(flow.name, graph.get("triggers") or [])

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


def _assert_triggers_available(flow_name: str, triggers: list[dict[str, Any]]) -> None:
	"""Reject ambiguous exact trigger matches across active published flows."""
	requested = {
		(
			str(trigger.get("type") or ""),
			str(trigger.get("match") or "").strip().casefold(),
		)
		for trigger in triggers
	}
	if not requested:
		return
	active = frappe.db.sql(
		"""
		SELECT flow_trigger.trigger_type, flow_trigger.match_value, flow_trigger.flow
		FROM `tabWhatsApp Core Flow Trigger` AS flow_trigger
		INNER JOIN `tabWhatsApp Core Flow` AS flow
			ON flow.name = flow_trigger.flow
			AND flow.active_version = flow_trigger.flow_version
		WHERE
			flow_trigger.enabled = 1
			AND flow.enabled = 1
			AND flow.status = 'Published'
			AND flow.name != %s
		""",
		flow_name,
		as_dict=True,
	)
	for row in active:
		signature = (
			str(row.trigger_type or ""),
			str(row.match_value or "").strip().casefold(),
		)
		if signature in requested:
			frappe.throw(
				f"Trigger {row.trigger_type} {row.match_value} is already active in flow {row.flow}",
				frappe.ValidationError,
			)


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
	# Serialize starts for a conversation. An existence check alone lets two
	# simultaneous webhook/API workers create competing active journeys.
	locked = frappe.db.sql(
		"select name from `tabWhatsApp Core Conversation` where name = %s for update",
		conversation,
	)
	if not locked:
		frappe.throw("Conversation not found", frappe.DoesNotExistError)
	if frappe.db.exists(
		"WhatsApp Core Flow Instance",
		{"conversation": conversation, "status": ["in", ["Running", "Waiting"]]},
	):
		frappe.throw("This conversation already has an active flow")

	context = dict(initial_context or {})
	context.setdefault("answers", {})
	context.setdefault("inputs", {})
	context.setdefault("attachments", [])
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
	if _expire_instance_if_due(instance):
		return {"status": "expired", "instance": instance.name, "commands": []}
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
		resolved_node = {**node, "config": _resolve_question_config(node, context)}
		ok, normalized, error = _validate_answer(resolved_node, answer)
		if not ok:
			# Invalid replies are still processed provider events. Persist their key
			# so a webhook retry cannot emit the validation response twice.
			instance.last_event_key = event_key
			instance.last_activity_at = now()
			instance.lock_version = (instance.lock_version or 0) + 1
			instance.save(ignore_permissions=True)
			return {
				"status": "invalid",
				"instance": instance.name,
				"commands": [{
					"type": "send_message",
					"message": error or node.get("config", {}).get("validation_message", "Please try again."),
				}],
			}
		answer_key = node["config"]["answer_key"]
		input_type = _input_type(node)
		context.setdefault("answers", {})[answer_key] = normalized
		input_record = {
			"node_id": node["id"],
			"answer_key": answer_key,
			"input_type": input_type,
			"value": normalized,
			"event_key": event_key,
		}
		if isinstance(answer, dict) and answer.get("message"):
			input_record["message"] = answer["message"]
		context.setdefault("inputs", {})[answer_key] = input_record
		context["last_input"] = input_record
		if input_type == "attachment":
			context.setdefault("attachments", []).append(normalized)
	else:
		context.setdefault("events", {})[event_key] = answer

	instance.context = canonical_json(context)
	instance.status = "Running"
	instance.last_event_key = event_key
	instance.last_activity_at = now()
	instance.lock_version = (instance.lock_version or 0) + 1
	instance.save(ignore_permissions=True)
	return advance_instance(instance.name, event_key, move_from_current=True)


def cancel_flow(instance_name: str, event_key: str, reason: str = "Exited by customer") -> dict[str, Any]:
	"""Cancel one active flow exactly once and retain its collected response ledger."""
	instance = _lock_instance(instance_name)
	if instance.status not in {"Running", "Waiting"}:
		return {"status": instance.status.lower(), "instance": instance.name, "commands": []}
	context = _as_dict(instance.context)
	context["exit"] = {"reason": reason, "event_key": event_key, "at": now()}
	instance.current_node_id = instance.current_node_id or "exit"
	instance.status = "Cancelled"
	instance.context = canonical_json(context)
	instance.last_event_key = event_key
	instance.last_activity_at = now()
	instance.completed_at = now()
	instance.waiting_flow_token = None
	instance.lock_version = (instance.lock_version or 0) + 1
	instance.save(ignore_permissions=True)
	upsert_instance_response(instance)
	return {
		"status": "cancelled",
		"instance": instance.name,
		"commands": [{"type": "send_message", "message": "The current flow has been closed."}],
	}


def resume_meta_flow_response(
	instance_name: str,
	event_key: str,
	flow_token: str,
	response: dict[str, Any],
) -> dict[str, Any]:
	"""Correlate one native Meta Flow submission and continue its visual graph."""
	instance = _lock_instance(instance_name)
	if _expire_instance_if_due(instance):
		return {"status": "expired", "instance": instance.name, "commands": []}
	if instance.status not in {"Waiting", "Running"}:
		return {"status": instance.status.lower(), "instance": instance.name, "commands": []}
	if instance.last_event_key == event_key:
		return {"status": "duplicate", "instance": instance.name, "commands": []}
	if not flow_token or flow_token != instance.waiting_flow_token:
		frappe.throw("Meta Flow response token does not match the waiting flow", frappe.PermissionError)

	graph = _as_dict(frappe.db.get_value("WhatsApp Core Flow Version", instance.flow_version, "graph"))
	node = _node_by_id(graph, instance.current_node_id)
	if node["type"] != "send_flow":
		frappe.throw("This automation is not waiting for a Meta Flow response", frappe.ValidationError)

	context = _as_dict(instance.context)
	response_key = node.get("config", {}).get("response_key") or node["id"]
	context.setdefault("responses", {})[response_key] = dict(response or {})
	context["meta_flow_response"] = dict(response or {})
	instance.context = canonical_json(context)
	instance.waiting_flow_token = None
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
					**_resolve_runtime_value(config, context),
					"correlation": {"flow_instance": instance.name, "node_id": node["id"]},
				}
				commands.append(command)
				_complete_step_run(run, {"command": command})
				node = _select_next_node(graph, node, context)
				continue
			if node_type in QUESTION_TYPES:
				resolved_config = _resolve_question_config(node, context)
				command = {
					"type": "ask_input" if node_type == "ask_input" else node_type,
					**resolved_config,
					"correlation": {"flow_instance": instance.name, "node_id": node["id"]},
				}
				commands.append(command)
				_complete_step_run(run, {"command": command})
				_save_instance(instance, node["id"], "Waiting", context, event_key)
				return {"status": "waiting", "instance": instance.name, "commands": commands}
			if node_type == "send_flow":
				flow_token = f"core_{uuid.uuid4().hex}"
				command = {
					"type": "send_flow",
					"flow_id": str(config["flow_id"]),
					"flow_token": flow_token,
					"flow_cta": config.get("flow_cta") or "Open",
					"flow_action": config.get("flow_action") or "navigate",
					"screen": config.get("screen") or "",
					"body": _render_text(
						config.get("message") or "Please complete this form.", context
					),
					"data": _resolve_action_input(config.get("data") or {}, context),
					"correlation": {"flow_instance": instance.name, "node_id": node["id"]},
				}
				commands.append(command)
				context.setdefault("meta_flows", {})[node["id"]] = {
					"flow_id": command["flow_id"],
					"flow_token": flow_token,
				}
				instance.waiting_flow_token = flow_token
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
				if config.get("message"):
					commands.append({
						"type": "send_message",
						"message": _render_text(config["message"], context),
						"correlation": {"flow_instance": instance.name, "node_id": node["id"]},
					})
				_complete_step_run(run, {"reason": config.get("reason")})
				_save_instance(instance, node["id"], "Completed", context, event_key)
				return {
					"status": "human_handoff",
					"instance": instance.name,
					"commands": commands,
				}
			if node_type == "end":
				if config.get("message"):
					commands.append({
						"type": "send_message",
						"message": _render_text(config["message"], context),
						"correlation": {"flow_instance": instance.name, "node_id": node["id"]},
					})
				_complete_step_run(run, {"commands": commands[-1:] if config.get("message") else []})
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
			upsert_instance_response(instance, "Failed")
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
	input_type = _input_type(node)
	if input_type == "attachment":
		return _validate_attachment_answer(config, answer)
	value = _answer_value(answer)
	if input_type == "number":
		try:
			number = Decimal(str(value).strip())
		except (InvalidOperation, TypeError, ValueError):
			return False, value, config.get("validation_message") or "Please enter a valid number."
		if not number.is_finite():
			return False, value, config.get("validation_message") or "Please enter a valid number."
		minimum = config.get("minimum")
		maximum = config.get("maximum")
		if minimum not in (None, "") and number < Decimal(str(minimum)):
			return False, value, config.get("validation_message") or f"Enter a value of at least {minimum}."
		if maximum not in (None, "") and number > Decimal(str(maximum)):
			return False, value, config.get("validation_message") or f"Enter a value no greater than {maximum}."
		if config.get("integer_only") and number != number.to_integral_value():
			return False, value, config.get("validation_message") or "Please enter a whole number."
		return True, int(number) if number == number.to_integral_value() else float(number), None
	if input_type == "text":
		value = str(value or "").strip()
		if config.get("required", True) and not value:
			return False, value, config.get("validation_message") or "A reply is required."
		min_length = int(config.get("min_length", 0))
		max_length = int(config.get("max_length", 4096))
		if not min_length <= len(value) <= max_length:
			return False, value, config.get("validation_message") or "That reply is not valid."
		return True, value, None
	options = config.get("options", [])
	if input_type == "multi_select":
		return _validate_multi_select_answer(config, options, value)
	allowed = {
		str(option.get("value", option.get("label"))) if isinstance(option, dict) else str(option)
		for option in options
	}
	value = str(value)
	if value not in allowed:
		return False, value, config.get("validation_message") or "Please select one of the options."
	return True, value, None


def _validate_multi_select_answer(
	config: dict[str, Any], options: list[Any], value: Any
) -> tuple[bool, Any, str | None]:
	"""Normalize one or more choices without depending on a channel-specific UI."""
	if isinstance(value, (list, tuple, set)):
		parts = [str(item).strip() for item in value]
	else:
		parts = [part.strip() for part in re.split(r"[,;\n]+", str(value or ""))]
	parts = [part for part in parts if part]
	if not parts:
		return False, [], config.get("validation_message") or "Please select at least one option."

	lookup: dict[str, str] = {}
	for index, option in enumerate(options, start=1):
		if isinstance(option, dict):
			label = str(option.get("label") or "").strip()
			option_value = str(option.get("value") or label).strip()
		else:
			label = option_value = str(option).strip()
		for candidate in (str(index), label, option_value):
			if candidate:
				lookup[candidate.casefold()] = option_value

	normalized: list[str] = []
	for part in parts:
		option_value = lookup.get(part.casefold())
		if option_value is None:
			return (
				False,
				parts,
				config.get("validation_message")
				or "Please select valid options separated by commas.",
			)
		if option_value not in normalized:
			normalized.append(option_value)
	return True, normalized, None


def _input_type(node: dict[str, Any]) -> str:
	if node["type"] == "ask_choice":
		return "select"
	if node["type"] == "ask_text":
		return "text"
	return str(node.get("config", {}).get("input_type") or "text")


def _answer_value(answer: Any) -> Any:
	if not isinstance(answer, dict):
		return answer
	return (
		answer.get("button_id")
		or answer.get("interactive_id")
		or answer.get("interactive_value")
		or answer.get("body")
		or answer.get("text")
		or ""
	)


def _validate_attachment_answer(
	config: dict[str, Any], answer: Any
) -> tuple[bool, Any, str | None]:
	if not isinstance(answer, dict):
		return False, answer, config.get("validation_message") or "Please attach a file."
	message_type = str(answer.get("type") or answer.get("message_type") or "").lower()
	accepted = set(config.get("accepted_media_types") or ATTACHMENT_TYPES)
	if message_type not in accepted:
		label = ", ".join(sorted(accepted))
		return False, answer, config.get("validation_message") or f"Please attach one of: {label}."
	media = answer.get("media") if isinstance(answer.get("media"), dict) else {}
	message_name = str(answer.get("message") or "").strip()
	if not message_name or not media.get("id"):
		return False, answer, config.get("validation_message") or "The attachment could not be identified."

	try:
		from frappe_whatsapp_core.message_media import cache_message_media

		file_doc = cache_message_media(message_name)
	except Exception:
		frappe.log_error(
			title=f"Flow attachment cache failed: {message_name}",
			message=frappe.get_traceback(),
		)
		return (
			False,
			answer,
			config.get("validation_message")
			or "We could not save that attachment. Please send it again.",
		)

	return True, {
		"message": message_name,
		"message_type": message_type,
		"caption": str(answer.get("body") or ""),
		"provider_media_id": media.get("id"),
		"filename": media.get("filename") or file_doc.file_name,
		"mime_type": media.get("mime_type") or file_doc.get("content_type") or "",
		"file": file_doc.name,
		"file_url": file_doc.file_url,
	}, None


def _execute_action(
	action_key: str,
	action_input: dict[str, Any],
	context: dict[str, Any],
	instance,
) -> Any:
	resolved_input = _resolve_action_input(action_input, context)
	return execute_registered_action(
		action_key,
		resolved_input,
		context=context,
		flow_instance=instance,
		flow_payload={
			"schema_version": 1,
			"flow": instance.flow,
			"flow_version": instance.flow_version,
			"flow_instance": instance.name,
			"conversation": instance.conversation,
			"action_input": resolved_input,
			"last_input": context.get("last_input"),
			"answers": context.get("answers") or {},
			"inputs": context.get("inputs") or {},
			"attachments": context.get("attachments") or [],
		},
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
		instance.waiting_flow_token = None
	instance.save(ignore_permissions=True)
	upsert_instance_response(instance)


def _lock_instance(instance_name: str):
	frappe.db.sql(
		"select name from `tabWhatsApp Core Flow Instance` where name = %s for update",
		instance_name,
	)
	return frappe.get_doc("WhatsApp Core Flow Instance", instance_name)


def expire_flow_if_due(instance_name: str) -> bool:
	"""Atomically expire a stale active flow and persist its final response."""
	return _expire_instance_if_due(_lock_instance(instance_name))


def _expire_instance_if_due(instance) -> bool:
	if instance.status not in {"Running", "Waiting"} or not instance.expires_at:
		return False
	if get_datetime(instance.expires_at) > now_datetime():
		return False
	context = _as_dict(instance.context)
	context["expiry"] = {
		"reason": "Flow response window expired",
		"at": str(now_datetime()),
	}
	instance.status = "Expired"
	instance.context = canonical_json(context)
	instance.completed_at = now()
	instance.last_activity_at = now()
	instance.waiting_flow_token = None
	instance.lock_version = (instance.lock_version or 0) + 1
	instance.save(ignore_permissions=True)
	upsert_instance_response(instance)
	return True


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


def _resolve_question_config(node: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
	config = _resolve_runtime_value(node.get("config", {}), context)
	options_from = node.get("config", {}).get("options_from")
	if options_from:
		resolved = _resolve_action_input(_variable_reference(options_from), context)
		if isinstance(resolved, list):
			config["options"] = resolved
	return config


def _resolve_runtime_value(value: Any, context: dict[str, Any]) -> Any:
	if isinstance(value, dict):
		if set(value) == {"var"}:
			return _resolve_action_input(value, context)
		return {key: _resolve_runtime_value(item, context) for key, item in value.items()}
	if isinstance(value, list):
		return [_resolve_runtime_value(item, context) for item in value]
	if isinstance(value, str):
		return _render_text(value, context)
	return value


def _render_text(value: str, context: dict[str, Any]) -> str:
	def replace(match):
		resolved = _resolve_action_input({"var": match.group(1)}, context)
		if resolved is None:
			return ""
		if isinstance(resolved, (dict, list)):
			return json.dumps(resolved, ensure_ascii=False, default=str)
		return str(resolved)

	return re.sub(r"\{\{\s*([a-zA-Z0-9_.-]+)\s*\}\}", replace, str(value or ""))


def _variable_reference(value: Any) -> dict[str, str]:
	if isinstance(value, dict) and isinstance(value.get("var"), str):
		return {"var": value["var"]}
	match = re.fullmatch(r"\{\{\s*([a-zA-Z0-9_.-]+)\s*\}\}", str(value or "").strip())
	return {"var": match.group(1) if match else str(value or "").strip()}
