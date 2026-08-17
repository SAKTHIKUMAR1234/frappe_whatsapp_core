"""Business-neutral starter graphs for the Core visual builder.

Starter graphs demonstrate the transport and input nodes only. Business
actions (creating documents, opening tickets, fetching catalogs, and similar
operations) belong to the installed business app and must be registered with
the ``whatsapp_core_flow_actions`` hook.
"""

import copy
import json

import frappe

from frappe_whatsapp_core.naming import name_by_key

BUILTIN_FLOWS = {
	"guided_request": {
		"schema_version": 1,
		"triggers": [
			{"key": "guided_request", "type": "command", "match": "/start", "priority": 10}
		],
		"nodes": [
			{
				"id": "start",
				"type": "start",
				"position": {"x": 40, "y": 180},
				"config": {"label": "Start"},
			},
			{
				"id": "request_type",
				"type": "ask_input",
				"position": {"x": 280, "y": 180},
				"config": {
					"label": "Choose request type",
					"message": "How can we help you?",
					"answer_key": "request_type",
					"input_type": "radio",
					"required": True,
					"options": [
						{"label": "Support", "value": "support"},
						{"label": "Information", "value": "information"},
					],
				},
			},
			{
				"id": "details",
				"type": "ask_input",
				"position": {"x": 550, "y": 180},
				"config": {
					"label": "Capture details",
					"message": "Please share the details of your request.",
					"answer_key": "details",
					"input_type": "text",
					"required": True,
				},
			},
			{
				"id": "confirmation",
				"type": "send_message",
				"position": {"x": 820, "y": 180},
				"config": {
					"label": "Confirm",
					"message": "Thank you. Your response has been recorded.",
				},
			},
			{
				"id": "end",
				"type": "end",
				"position": {"x": 1080, "y": 180},
				"config": {"label": "End"},
			},
		],
		"edges": [
			{"id": "e1", "source": "start", "target": "request_type"},
			{"id": "e2", "source": "request_type", "target": "details"},
			{"id": "e3", "source": "details", "target": "confirmation"},
			{"id": "e4", "source": "confirmation", "target": "end"},
		],
	}
}


def create_from_template(
	template_key="guided_request",
	flow_key="core.starter.guided_request",
	title="Guided Request",
):
	if template_key not in BUILTIN_FLOWS:
		frappe.throw(f"Unknown flow template: {template_key}")
	if record_name := name_by_key("WhatsApp Core Flow", flow_key):
		return record_name
	graph = copy.deepcopy(BUILTIN_FLOWS[template_key])
	return frappe.get_doc({
		"doctype": "WhatsApp Core Flow",
		"flow_key": flow_key,
		"title": title,
		"description": "A business-neutral starter Flow for collecting a guided response.",
		"status": "Draft",
		"approval_status": "Draft",
		"enabled": 1,
		"draft_graph": json.dumps(graph, separators=(",", ":"), ensure_ascii=False),
	}).insert(ignore_permissions=True).name
