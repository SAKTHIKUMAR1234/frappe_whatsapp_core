"""Desk API for the Core visual flow builder."""

import json

import frappe

from frappe_whatsapp_core.flow_actions import (
	registered_actions,
	validate_registered_actions,
)
from frappe_whatsapp_core.flow_schema import validate_graph
from frappe_whatsapp_core.flows import publish_flow
from frappe_whatsapp_core.permissions import require_document_permission


@frappe.whitelist()
@require_document_permission("WhatsApp Core Flow", "read", name_argument="flow_name")
def get_builder(flow_name):
	doc = frappe.get_doc("WhatsApp Core Flow", flow_name)
	graph = frappe.parse_json(doc.draft_graph) if doc.draft_graph else _empty_graph()
	errors = _validation_errors(graph)
	return {
		"name": doc.name,
		"flow_key": doc.flow_key,
		"title": doc.title,
		"status": doc.status,
		"active_version": doc.active_version,
		"graph": graph,
		"errors": errors,
		"catalog": {
			"actions": registered_actions(),
			"templates": frappe.get_all(
				"WhatsApp Core Template",
				filters={"enabled": 1, "approval_status": "APPROVED"},
				pluck="template_name",
				order_by="template_name asc",
				limit_page_length=500,
			),
		},
	}


@frappe.whitelist()
@require_document_permission("WhatsApp Core Flow", "write", name_argument="flow_name")
def save_draft(flow_name, graph):
	graph = frappe.parse_json(graph)
	errors = _validation_errors(graph)
	doc = frappe.get_doc("WhatsApp Core Flow", flow_name)
	doc.draft_graph = json.dumps(graph, separators=(",", ":"), ensure_ascii=False)
	doc.validation_errors = "\n".join(errors)
	doc.save()
	return {"flow": doc.name, "errors": errors}


@frappe.whitelist()
@require_document_permission("WhatsApp Core Flow", "read", name_argument="flow_name")
def validate_draft(flow_name):
	doc = frappe.get_doc("WhatsApp Core Flow", flow_name)
	return {
		"flow": doc.name,
		"errors": _validation_errors(frappe.parse_json(doc.draft_graph)),
	}


@frappe.whitelist()
@require_document_permission("WhatsApp Core Flow", "write", name_argument="flow_name")
def publish(flow_name):
	doc = frappe.get_doc("WhatsApp Core Flow", flow_name)
	errors = _validation_errors(frappe.parse_json(doc.draft_graph))
	if errors:
		frappe.throw("<br>".join(errors), frappe.ValidationError)
	return publish_flow(flow_name)


def _validation_errors(graph):
	return validate_graph(graph) + validate_registered_actions(graph)


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
