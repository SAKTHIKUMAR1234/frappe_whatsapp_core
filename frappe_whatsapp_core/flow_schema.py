"""Validation and safe condition evaluation for versioned WhatsApp flows."""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Any


GRAPH_VERSION = 1

NODE_TYPES = {
	"start",
	"send_template",
	"send_message",
	"ask_text",
	"ask_choice",
	"condition",
	"action",
	"wait",
	"human_handoff",
	"end",
}

TRIGGER_TYPES = {
	"command",
	"template_button",
	"inbound_pattern",
	"case_event",
	"schedule",
	"api",
}

QUESTION_TYPES = {"ask_text", "ask_choice"}
TERMINAL_TYPES = {"end", "human_handoff"}
MAX_NODES = 250
MAX_EDGES = 750


class FlowValidationError(ValueError):
	"""Raised when a graph cannot safely be published."""

	def __init__(self, errors: list[str]):
		super().__init__("; ".join(errors))
		self.errors = errors


def validate_graph(graph: dict[str, Any]) -> list[str]:
	"""Return human-readable publication errors without executing user code."""
	errors: list[str] = []
	if not isinstance(graph, dict):
		return ["Graph must be a JSON object"]
	if graph.get("schema_version") != GRAPH_VERSION:
		errors.append(f"schema_version must be {GRAPH_VERSION}")

	nodes = graph.get("nodes")
	edges = graph.get("edges")
	triggers = graph.get("triggers", [])
	if not isinstance(nodes, list):
		errors.append("nodes must be a list")
		nodes = []
	if not isinstance(edges, list):
		errors.append("edges must be a list")
		edges = []
	if not isinstance(triggers, list):
		errors.append("triggers must be a list")
		triggers = []
	if len(nodes) > MAX_NODES:
		errors.append(f"A flow may contain at most {MAX_NODES} nodes")
	if len(edges) > MAX_EDGES:
		errors.append(f"A flow may contain at most {MAX_EDGES} edges")

	node_ids: set[str] = set()
	node_by_id: dict[str, dict[str, Any]] = {}
	for index, node in enumerate(nodes):
		if not isinstance(node, dict):
			errors.append(f"Node {index + 1} must be an object")
			continue
		node_id = node.get("id")
		node_type = node.get("type")
		if not isinstance(node_id, str) or not node_id.strip():
			errors.append(f"Node {index + 1} requires a non-empty id")
			continue
		if node_id in node_ids:
			errors.append(f"Duplicate node id: {node_id}")
			continue
		node_ids.add(node_id)
		node_by_id[node_id] = node
		if node_type not in NODE_TYPES:
			errors.append(f"Node {node_id} has unsupported type: {node_type}")
		_validate_node_config(node, errors)

	start_nodes = [node for node in nodes if isinstance(node, dict) and node.get("type") == "start"]
	if len(start_nodes) != 1:
		errors.append("A flow requires exactly one start node")
	if not any(isinstance(node, dict) and node.get("type") in TERMINAL_TYPES for node in nodes):
		errors.append("A flow requires at least one end or human_handoff node")

	outgoing: dict[str, list[dict[str, Any]]] = defaultdict(list)
	incoming: dict[str, list[dict[str, Any]]] = defaultdict(list)
	edge_ids: set[str] = set()
	for index, edge in enumerate(edges):
		if not isinstance(edge, dict):
			errors.append(f"Edge {index + 1} must be an object")
			continue
		edge_id = edge.get("id")
		source = edge.get("source")
		target = edge.get("target")
		if not isinstance(edge_id, str) or not edge_id.strip():
			errors.append(f"Edge {index + 1} requires a non-empty id")
		elif edge_id in edge_ids:
			errors.append(f"Duplicate edge id: {edge_id}")
		else:
			edge_ids.add(edge_id)
		if source not in node_ids:
			errors.append(f"Edge {edge_id or index + 1} has unknown source: {source}")
		if target not in node_ids:
			errors.append(f"Edge {edge_id or index + 1} has unknown target: {target}")
		if source in node_ids and target in node_ids:
			outgoing[source].append(edge)
			incoming[target].append(edge)
		if "when" in edge:
			errors.extend(f"Edge {edge_id}: {error}" for error in validate_condition(edge["when"]))

	for node_id, node in node_by_id.items():
		node_type = node.get("type")
		node_edges = outgoing.get(node_id, [])
		if node_type in TERMINAL_TYPES and node_edges:
			errors.append(f"Terminal node {node_id} cannot have outgoing edges")
		elif node_type not in TERMINAL_TYPES and not node_edges:
			errors.append(f"Node {node_id} has no outgoing edge")
		if node_type == "condition":
			if len(node_edges) < 2:
				errors.append(f"Condition node {node_id} requires at least two branches")
			if not any(edge.get("default") is True for edge in node_edges):
				errors.append(f"Condition node {node_id} requires one default branch")
		if node_type in QUESTION_TYPES and len(node_edges) > 1:
			if not any(edge.get("default") is True for edge in node_edges):
				errors.append(f"Question node {node_id} with branches requires a default branch")

	if start_nodes:
		start_id = start_nodes[0].get("id")
		reachable = _reachable_from(start_id, outgoing)
		for node_id in sorted(node_ids - reachable):
			errors.append(f"Node {node_id} is unreachable from start")

	errors.extend(_validate_cycles(node_ids, outgoing))
	errors.extend(_validate_triggers(triggers))
	return errors


def assert_valid_graph(graph: dict[str, Any]) -> None:
	errors = validate_graph(graph)
	if errors:
		raise FlowValidationError(errors)


def validate_condition(condition: Any, path: str = "condition") -> list[str]:
	if not isinstance(condition, dict):
		return [f"{path} must be an object"]
	op = condition.get("op")
	if op in {"and", "or"}:
		items = condition.get("items")
		if not isinstance(items, list) or not items:
			return [f"{path}.{op} requires a non-empty items list"]
		errors: list[str] = []
		for index, item in enumerate(items):
			errors.extend(validate_condition(item, f"{path}.items[{index}]"))
		return errors
	if op == "not":
		return validate_condition(condition.get("item"), f"{path}.item")
	if op in {"eq", "ne", "in", "contains", "lt", "lte", "gt", "gte"}:
		if "left" not in condition or "right" not in condition:
			return [f"{path}.{op} requires left and right"]
		return _validate_operand(condition["left"], f"{path}.left") + _validate_operand(
			condition["right"], f"{path}.right"
		)
	if op == "exists":
		return _validate_operand(condition.get("value"), f"{path}.value")
	return [f"{path} has unsupported operator: {op}"]


def evaluate_condition(condition: dict[str, Any], context: dict[str, Any]) -> bool:
	"""Evaluate the constrained condition language; never eval Python or SQL."""
	op = condition["op"]
	if op == "and":
		return all(evaluate_condition(item, context) for item in condition["items"])
	if op == "or":
		return any(evaluate_condition(item, context) for item in condition["items"])
	if op == "not":
		return not evaluate_condition(condition["item"], context)
	if op == "exists":
		return _resolve_operand(condition["value"], context) is not None

	left = _resolve_operand(condition["left"], context)
	right = _resolve_operand(condition["right"], context)
	if op == "eq":
		return left == right
	if op == "ne":
		return left != right
	if op == "in":
		return left in right if isinstance(right, (list, tuple, set, str)) else False
	if op == "contains":
		return right in left if isinstance(left, (list, tuple, set, str)) else False
	if op == "lt":
		return left < right
	if op == "lte":
		return left <= right
	if op == "gt":
		return left > right
	if op == "gte":
		return left >= right
	raise ValueError(f"Unsupported condition operator: {op}")


def _validate_node_config(node: dict[str, Any], errors: list[str]) -> None:
	node_id = node.get("id", "?")
	node_type = node.get("type")
	config = node.get("config", {})
	if not isinstance(config, dict):
		errors.append(f"Node {node_id} config must be an object")
		return
	if node_type in {"send_message", "ask_text", "ask_choice"} and not config.get("message"):
		errors.append(f"Node {node_id} requires config.message")
	if node_type == "send_template" and not config.get("template"):
		errors.append(f"Node {node_id} requires config.template")
	if node_type in QUESTION_TYPES and not config.get("answer_key"):
		errors.append(f"Node {node_id} requires config.answer_key")
	if node_type == "ask_choice":
		options = config.get("options")
		if not isinstance(options, list) or len(options) < 2:
			errors.append(f"Node {node_id} requires at least two options")
		elif len(options) > 10:
			errors.append(f"Node {node_id} supports at most ten options")
		else:
			values: set[str] = set()
			for index, option in enumerate(options, start=1):
				if isinstance(option, str):
					label = value = option.strip()
				elif isinstance(option, dict):
					label = str(option.get("label") or "").strip()
					value = str(option.get("value") or label).strip()
				else:
					errors.append(
						f"Node {node_id} option {index} must be text or an object"
					)
					continue
				if not label or not value:
					errors.append(
						f"Node {node_id} option {index} requires label and value"
					)
				if len(label) > 24:
					errors.append(
						f"Node {node_id} option {index} label exceeds 24 characters"
					)
				if len(value) > 200:
					errors.append(
						f"Node {node_id} option {index} value exceeds 200 characters"
					)
				if value in values:
					errors.append(
						f"Node {node_id} has duplicate option value: {value}"
					)
				values.add(value)
	if node_type == "action" and not config.get("action"):
		errors.append(f"Node {node_id} requires a typed config.action")
	if node_type == "wait" and not config.get("resume_on"):
		errors.append(f"Node {node_id} requires config.resume_on")


def _validate_operand(value: Any, path: str) -> list[str]:
	if isinstance(value, dict):
		if set(value) != {"var"} or not isinstance(value.get("var"), str):
			return [f"{path} must be a literal or {{\"var\": \"context.path\"}}"]
	return []


def _resolve_operand(value: Any, context: dict[str, Any]) -> Any:
	if not isinstance(value, dict):
		return value
	path = value["var"]
	current: Any = context
	for part in path.split("."):
		if not isinstance(current, dict) or part not in current:
			return None
		current = current[part]
	return current


def _reachable_from(start_id: str, outgoing: dict[str, list[dict[str, Any]]]) -> set[str]:
	seen: set[str] = set()
	queue = deque([start_id])
	while queue:
		node_id = queue.popleft()
		if node_id in seen:
			continue
		seen.add(node_id)
		queue.extend(edge["target"] for edge in outgoing.get(node_id, []))
	return seen


def _validate_cycles(
	node_ids: set[str], outgoing: dict[str, list[dict[str, Any]]]
) -> list[str]:
	"""Cycles are allowed only when each strongly connected component has a guard."""
	errors: list[str] = []
	index = 0
	stack: list[str] = []
	on_stack: set[str] = set()
	indices: dict[str, int] = {}
	lowlinks: dict[str, int] = {}

	def visit(node_id: str) -> None:
		nonlocal index
		indices[node_id] = index
		lowlinks[node_id] = index
		index += 1
		stack.append(node_id)
		on_stack.add(node_id)

		for edge in outgoing.get(node_id, []):
			target = edge["target"]
			if target not in indices:
				visit(target)
				lowlinks[node_id] = min(lowlinks[node_id], lowlinks[target])
			elif target in on_stack:
				lowlinks[node_id] = min(lowlinks[node_id], indices[target])

		if lowlinks[node_id] != indices[node_id]:
			return
		component: set[str] = set()
		while stack:
			member = stack.pop()
			on_stack.remove(member)
			component.add(member)
			if member == node_id:
				break
		internal_edges = [
			edge
			for source in component
			for edge in outgoing.get(source, [])
			if edge["target"] in component
		]
		has_cycle = len(component) > 1 or any(
			edge["source"] == edge["target"] for edge in internal_edges
		)
		if has_cycle and not any(
			isinstance(edge.get("max_traversals"), int)
			and 1 <= edge["max_traversals"] <= 10
			for edge in internal_edges
		):
			errors.append(
				f"Cycle containing {', '.join(sorted(component))} requires one edge "
				"with max_traversals between 1 and 10"
			)

	for node_id in node_ids:
		if node_id not in indices:
			visit(node_id)
	return errors


def _validate_triggers(triggers: list[Any]) -> list[str]:
	errors: list[str] = []
	keys: set[str] = set()
	for index, trigger in enumerate(triggers):
		if not isinstance(trigger, dict):
			errors.append(f"Trigger {index + 1} must be an object")
			continue
		key = trigger.get("key")
		trigger_type = trigger.get("type")
		if not key:
			errors.append(f"Trigger {index + 1} requires a key")
		elif key in keys:
			errors.append(f"Duplicate trigger key: {key}")
		else:
			keys.add(key)
		if trigger_type not in TRIGGER_TYPES:
			errors.append(f"Trigger {key or index + 1} has unsupported type: {trigger_type}")
		if trigger_type in {"command", "template_button", "inbound_pattern", "case_event"}:
			if not trigger.get("match"):
				errors.append(f"Trigger {key or index + 1} requires match")
	return errors
