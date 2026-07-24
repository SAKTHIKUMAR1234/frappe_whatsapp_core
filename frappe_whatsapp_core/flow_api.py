"""Desk API for the Core visual flow builder."""

import json

import frappe

from frappe_whatsapp_core.flow_schema import validate_graph
from frappe_whatsapp_core.flows import publish_flow
from frappe_whatsapp_core.permissions import require_document_permission


@frappe.whitelist()
@require_document_permission("WhatsApp Core Flow", "read", name_argument="flow_name")
def get_builder(flow_name):
	doc = frappe.get_doc("WhatsApp Core Flow", flow_name)
	graph = frappe.parse_json(doc.draft_graph) if doc.draft_graph else _empty_graph()
	return {
		"name": doc.name,
		"flow_key": doc.flow_key,
		"title": doc.title,
		"status": doc.status,
		"active_version": doc.active_version,
		"graph": graph,
		"errors": validate_graph(graph),
	}


@frappe.whitelist()
@require_document_permission("WhatsApp Core Flow", "write", name_argument="flow_name")
def save_draft(flow_name, graph):
	graph = frappe.parse_json(graph)
	errors = validate_graph(graph)
	doc = frappe.get_doc("WhatsApp Core Flow", flow_name)
	doc.draft_graph = json.dumps(graph, separators=(",", ":"), ensure_ascii=False)
	doc.validation_errors = "\n".join(errors)
	doc.save()
	return {"flow": doc.name, "errors": errors}


@frappe.whitelist()
@require_document_permission("WhatsApp Core Flow", "read", name_argument="flow_name")
def validate_draft(flow_name):
	doc = frappe.get_doc("WhatsApp Core Flow", flow_name)
	return {"flow": doc.name, "errors": validate_graph(frappe.parse_json(doc.draft_graph))}


@frappe.whitelist()
@require_document_permission("WhatsApp Core Flow", "write", name_argument="flow_name")
def publish(flow_name):
	return publish_flow(flow_name)


def _empty_graph():
	return {
		"schema_version": 1,
		"triggers": [],
		"nodes": [
			{
				"id": "start",
				"type": "start",
				"position": {"x": 80, "y": 180},
				"config": {"label": "Start"},
			},
			{
				"id": "end",
				"type": "end",
				"position": {"x": 540, "y": 180},
				"config": {"label": "End"},
			},
		],
		"edges": [{"id": "edge-start-end", "source": "start", "target": "end"}],
	}
