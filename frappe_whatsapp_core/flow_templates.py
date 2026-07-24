"""Business-neutral starter graphs for the Core visual builder."""

import copy
import json

import frappe


BUILTIN_FLOWS = {
	"branched_review": {
		"schema_version": 1,
		"triggers": [
			{"key": "help", "type": "command", "match": "/help", "priority": 10},
			{
				"key": "review_start",
				"type": "template_button",
				"match": "start_review",
				"priority": 20,
			},
		],
		"nodes": [
			{
				"id": "start",
				"type": "start",
				"position": {"x": 40, "y": 230},
				"config": {"label": "Start"},
			},
			{
				"id": "welcome",
				"type": "send_message",
				"position": {"x": 250, "y": 230},
				"config": {
					"label": "Welcome",
					"message": "We would like to ask two quick questions.",
				},
			},
			{
				"id": "liked",
				"type": "ask_choice",
				"position": {"x": 480, "y": 230},
				"config": {
					"label": "Do they like it?",
					"message": "Do you like our products?",
					"answer_key": "liked",
					"options": [
						{"label": "Yes", "value": "yes"},
						{"label": "No", "value": "no"},
					],
				},
			},
			{
				"id": "liked_branch",
				"type": "condition",
				"position": {"x": 730, "y": 230},
				"config": {"label": "Yes or No?"},
			},
			{
				"id": "favorite_product",
				"type": "ask_text",
				"position": {"x": 980, "y": 80},
				"config": {
					"label": "Favourite product",
					"message": "Which product do you like most?",
					"answer_key": "favorite_product",
				},
			},
			{
				"id": "record_interest",
				"type": "action",
				"position": {"x": 1240, "y": 80},
				"config": {
					"label": "Categorize interest",
					"action": "customer.categorize_interest",
					"input": {"product": {"var": "answers.favorite_product"}},
				},
			},
			{
				"id": "difficulty",
				"type": "ask_text",
				"position": {"x": 980, "y": 380},
				"config": {
					"label": "Capture difficulty",
					"message": "What difficulty did you face with us?",
					"answer_key": "difficulty",
				},
			},
			{
				"id": "create_ticket",
				"type": "action",
				"position": {"x": 1240, "y": 380},
				"config": {
					"label": "Create support ticket",
					"action": "case.create",
					"input": {
						"case_type": "essdee.operations.tech_support",
						"description": {"var": "answers.difficulty"},
					},
					"output_key": "ticket",
				},
			},
			{
				"id": "thanks",
				"type": "send_message",
				"position": {"x": 1510, "y": 230},
				"config": {
					"label": "Thank customer",
					"message": "Thank you. Your response has been recorded.",
				},
			},
			{
				"id": "end",
				"type": "end",
				"position": {"x": 1750, "y": 230},
				"config": {"label": "End"},
			},
		],
		"edges": [
			{"id": "e1", "source": "start", "target": "welcome"},
			{"id": "e2", "source": "welcome", "target": "liked"},
			{"id": "e3", "source": "liked", "target": "liked_branch"},
			{
				"id": "e4",
				"source": "liked_branch",
				"target": "favorite_product",
				"when": {"op": "eq", "left": {"var": "answers.liked"}, "right": "yes"},
			},
			{"id": "e5", "source": "liked_branch", "target": "difficulty", "default": True},
			{"id": "e6", "source": "favorite_product", "target": "record_interest"},
			{"id": "e7", "source": "record_interest", "target": "thanks"},
			{"id": "e8", "source": "difficulty", "target": "create_ticket"},
			{"id": "e9", "source": "create_ticket", "target": "thanks"},
			{"id": "e10", "source": "thanks", "target": "end"},
		],
	}
}


def create_from_template(
	template_key="branched_review",
	flow_key="core.demo.branched_review",
	title="Branched Customer Review",
):
	if template_key not in BUILTIN_FLOWS:
		frappe.throw(f"Unknown flow template: {template_key}")
	if frappe.db.exists("WhatsApp Core Flow", flow_key):
		return flow_key
	graph = copy.deepcopy(BUILTIN_FLOWS[template_key])
	return frappe.get_doc({
		"doctype": "WhatsApp Core Flow",
		"flow_key": flow_key,
		"title": title,
		"description": "Template button or /help, branched questions, and typed business actions.",
		"status": "Draft",
		"enabled": 1,
		"draft_graph": json.dumps(graph, separators=(",", ":"), ensure_ascii=False),
	}).insert(ignore_permissions=True).name
