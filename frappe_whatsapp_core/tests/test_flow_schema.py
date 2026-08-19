import unittest

from frappe_whatsapp_core.flow_schema import evaluate_condition, validate_graph
from frappe_whatsapp_core.flows import _resolve_question_config


def valid_graph():
	return {
		"schema_version": 1,
		"triggers": [{"key": "help", "type": "command", "match": "/help"}],
		"nodes": [
			{"id": "start", "type": "start", "config": {"label": "Start"}},
			{
				"id": "liked",
				"type": "ask_choice",
				"config": {
					"message": "Do you like our products?",
					"answer_key": "liked",
					"options": [
						{"label": "Yes", "value": "yes"},
						{"label": "No", "value": "no"},
					],
				},
			},
			{"id": "branch", "type": "condition", "config": {}},
			{
				"id": "product",
				"type": "ask_text",
				"config": {"message": "Which product?", "answer_key": "product"},
			},
			{
				"id": "difficulty",
				"type": "ask_text",
				"config": {"message": "What difficulty did you face?", "answer_key": "difficulty"},
			},
			{"id": "end", "type": "end", "config": {}},
		],
		"edges": [
			{"id": "e1", "source": "start", "target": "liked"},
			{"id": "e2", "source": "liked", "target": "branch"},
			{
				"id": "e3",
				"source": "branch",
				"target": "product",
				"when": {"op": "eq", "left": {"var": "answers.liked"}, "right": "yes"},
			},
			{"id": "e4", "source": "branch", "target": "difficulty", "default": True},
			{"id": "e5", "source": "product", "target": "end"},
			{"id": "e6", "source": "difficulty", "target": "end"},
		],
	}


class TestFlowSchema(unittest.TestCase):
	def test_valid_branched_flow(self):
		self.assertEqual(validate_graph(valid_graph()), [])

	def test_rejects_unreachable_and_unsafe_condition(self):
		graph = valid_graph()
		graph["nodes"].append({"id": "orphan", "type": "end", "config": {}})
		graph["edges"][2]["when"] = {"op": "python", "code": "delete everything"}
		errors = validate_graph(graph)
		self.assertTrue(any("unreachable" in error for error in errors))
		self.assertTrue(any("unsupported operator" in error for error in errors))

	def test_cycle_requires_guard(self):
		graph = valid_graph()
		graph["edges"][4]["default"] = True
		graph["edges"].append(
			{
				"id": "loop",
				"source": "product",
				"target": "branch",
				"when": {"op": "eq", "left": {"var": "repeat"}, "right": True},
			}
		)
		errors = validate_graph(graph)
		self.assertTrue(any("max_traversals" in error for error in errors))
		graph["edges"][-1]["max_traversals"] = 3
		self.assertEqual(validate_graph(graph), [])

	def test_safe_condition_evaluator(self):
		condition = {
			"op": "and",
			"items": [
				{"op": "eq", "left": {"var": "answers.liked"}, "right": "yes"},
				{"op": "contains", "left": {"var": "tags"}, "right": "buyer"},
			],
		}
		self.assertTrue(evaluate_condition(condition, {"answers": {"liked": "yes"}, "tags": ["buyer"]}))
		self.assertFalse(evaluate_condition(condition, {"answers": {"liked": "no"}, "tags": ["buyer"]}))

	def test_unified_inputs_support_number_choice_and_attachment(self):
		for input_type, extra in (
			("number", {"minimum": 1, "maximum": 10, "integer_only": True}),
			("radio", {"options": ["Create", "Exit"]}),
			("select", {"options_from": {"var": "actions.catalog.options"}}),
			("multi_select", {"options": ["Gym Vest", "Innerwear"]}),
			("attachment", {"accepted_media_types": ["image", "document", "audio"]}),
			("content", {"accepted_media_types": ["image", "document", "audio", "sticker"]}),
		):
			graph = valid_graph()
			graph["nodes"][1] = {
				"id": "liked",
				"type": "ask_input",
				"config": {
					"message": "Provide a value",
					"answer_key": "value",
					"input_type": input_type,
					**extra,
				},
			}
			self.assertEqual(validate_graph(graph), [], input_type)

	def test_dynamic_options_require_a_context_reference(self):
		graph = valid_graph()
		graph["nodes"][1]["type"] = "ask_input"
		graph["nodes"][1]["config"].update({
			"input_type": "select",
			"options_from": "actions.catalog.options",
		})
		errors = validate_graph(graph)
		self.assertTrue(any("options_from must be a context variable" in error for error in errors))

	def test_dynamic_options_resolve_from_action_result(self):
		node = {
			"id": "catalog",
			"type": "ask_input",
			"config": {
				"message": "Choose a product",
				"answer_key": "product",
				"input_type": "select",
				"options_from": {"var": "actions.catalog.options"},
			},
		}
		options = [{"label": "Catalog A", "value": "a"}]
		resolved = _resolve_question_config(node, {"actions": {"catalog": {"options": options}}})
		self.assertEqual(resolved["options"], options)

	def test_duplicate_trigger_signature_is_rejected(self):
		graph = valid_graph()
		graph["triggers"].append({
			"key": "help-again",
			"type": "command",
			"match": " /HELP ",
		})
		errors = validate_graph(graph)
		self.assertTrue(any("Duplicate command trigger match" in error for error in errors))


if __name__ == "__main__":
	unittest.main()
