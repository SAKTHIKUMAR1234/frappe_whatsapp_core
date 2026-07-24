import unittest

from frappe_whatsapp_core.flow_schema import evaluate_condition, validate_graph


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


if __name__ == "__main__":
	unittest.main()
