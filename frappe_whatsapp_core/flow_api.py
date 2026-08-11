"""Desk API for the Core visual flow builder."""

import json
import uuid

import frappe
from frappe.utils import now

from frappe_whatsapp_core.flow_actions import (
	registered_action_catalog,
	validate_registered_actions,
)
from frappe_whatsapp_core.flow_schema import validate_graph
from frappe_whatsapp_core.flows import canonical_json, publish_flow, start_flow
from frappe_whatsapp_core.meta_flows import flow_workspace
from frappe_whatsapp_core.permissions import (
	assert_conversation_access,
	require_document_permission,
	require_flow_builder_access,
)


@frappe.whitelist()
@require_flow_builder_access()
def list_flows(limit: int = 500):
	return frappe.get_list(
		"WhatsApp Core Flow",
		fields=[
			"name", "flow_key", "title", "description", "status", "enabled",
			"active_version", "approval_status", "approval_requested_by",
			"approval_requested_at", "approved_by", "approved_at", "owner", "modified",
		],
		order_by="modified desc",
		limit_page_length=max(1, min(int(limit or 500), 500)),
	)


@frappe.whitelist()
@require_flow_builder_access()
def create_flow(title: str, flow_key: str, graph=None, description: str = ""):
	flow_key = str(flow_key or "").strip()
	title = str(title or "").strip()
	if not flow_key or not title:
		frappe.throw("Flow title and key are required", frappe.ValidationError)
	if frappe.db.exists("WhatsApp Core Flow", flow_key):
		frappe.throw("A flow with this key already exists", frappe.DuplicateEntryError)
	graph = frappe.parse_json(graph) if graph else _empty_graph()
	doc = frappe.get_doc({
		"doctype": "WhatsApp Core Flow",
		"flow_key": flow_key,
		"title": title,
		"description": str(description or ""),
		"status": "Draft",
		"approval_status": "Draft",
		"enabled": 1,
		"draft_graph": json.dumps(graph, separators=(",", ":"), ensure_ascii=False),
		"validation_errors": "\n".join(_validation_errors(graph)),
	}).insert()
	return {"name": doc.name, "flow_key": doc.flow_key, "errors": _validation_errors(graph)}


@frappe.whitelist()
@require_flow_builder_access()
@require_document_permission("WhatsApp Core Flow", "read", name_argument="flow_name")
def get_builder(flow_name):
	doc = frappe.get_doc("WhatsApp Core Flow", flow_name)
	graph = frappe.parse_json(doc.draft_graph) if doc.draft_graph else _empty_graph()
	errors = _validation_errors(graph)
	can_manage = bool(set(frappe.get_roles()) & {"System Manager", "WhatsApp Manager"})
	meta_workspace = flow_workspace() if can_manage else {"flows": []}
	return {
		"name": doc.name,
		"flow_key": doc.flow_key,
		"title": doc.title,
		"status": doc.status,
		"approval_status": doc.approval_status,
		"approval_requested_by": doc.approval_requested_by,
		"approval_requested_at": doc.approval_requested_at,
		"approved_by": doc.approved_by,
		"approved_at": doc.approved_at,
		"rejection_reason": doc.rejection_reason,
		"active_version": doc.active_version,
		"can_manage": can_manage,
		"graph": graph,
		"errors": errors,
		"catalog": {
			"actions": registered_action_catalog(),
			"templates": frappe.get_all(
				"WhatsApp Core Template",
				filters={"enabled": 1, "approval_status": "APPROVED"},
				pluck="template_name",
				order_by="template_name asc",
				limit_page_length=500,
			),
			"meta_flows": [
				flow
				for flow in (meta_workspace.get("flows") or [])
				if str(flow.get("status") or "").upper() == "PUBLISHED"
			],
		},
	}


@frappe.whitelist()
@require_flow_builder_access()
@require_document_permission("WhatsApp Core Flow", "write", name_argument="flow_name")
def save_draft(flow_name, graph):
	graph = frappe.parse_json(graph)
	errors = _validation_errors(graph)
	doc = frappe.get_doc("WhatsApp Core Flow", flow_name)
	serialized = canonical_json(graph)
	changed = canonical_json(frappe.parse_json(doc.draft_graph or "{}")) != serialized
	doc.draft_graph = serialized
	doc.validation_errors = "\n".join(errors)
	if changed:
		doc.approval_status = "Draft"
		doc.approval_requested_by = None
		doc.approval_requested_at = None
		doc.approved_by = None
		doc.approved_at = None
		doc.rejection_reason = None
	doc.save()
	return {"flow": doc.name, "errors": errors, "approval_status": doc.approval_status}


@frappe.whitelist()
@require_flow_builder_access()
@require_document_permission("WhatsApp Core Flow", "read", name_argument="flow_name")
def validate_draft(flow_name):
	doc = frappe.get_doc("WhatsApp Core Flow", flow_name)
	return {
		"flow": doc.name,
		"errors": _validation_errors(frappe.parse_json(doc.draft_graph)),
	}


@frappe.whitelist()
@require_flow_builder_access(manage=True)
def publish(flow_name):
	doc = frappe.get_doc("WhatsApp Core Flow", flow_name)
	errors = _validation_errors(frappe.parse_json(doc.draft_graph))
	if errors:
		frappe.throw("<br>".join(errors), frappe.ValidationError)
	doc.approval_status = "Approved"
	doc.approved_by = frappe.session.user
	doc.approved_at = now()
	doc.rejection_reason = None
	doc.save(ignore_permissions=True)
	return publish_flow(flow_name)


@frappe.whitelist()
@require_flow_builder_access()
@require_document_permission("WhatsApp Core Flow", "write", name_argument="flow_name")
def request_approval(flow_name):
	doc = frappe.get_doc("WhatsApp Core Flow", flow_name)
	errors = _validation_errors(frappe.parse_json(doc.draft_graph))
	if errors:
		frappe.throw("<br>".join(errors), frappe.ValidationError)
	doc.approval_status = "Pending Approval"
	doc.approval_requested_by = frappe.session.user
	doc.approval_requested_at = now()
	doc.approved_by = None
	doc.approved_at = None
	doc.rejection_reason = None
	doc.save()
	return {"flow": doc.name, "approval_status": doc.approval_status}


@frappe.whitelist()
@require_flow_builder_access(manage=True)
def reject(flow_name, reason: str):
	doc = frappe.get_doc("WhatsApp Core Flow", flow_name)
	doc.approval_status = "Rejected"
	doc.rejection_reason = str(reason or "").strip() or "Changes requested by WhatsApp Manager"
	doc.approved_by = None
	doc.approved_at = None
	doc.save(ignore_permissions=True)
	return {
		"flow": doc.name,
		"approval_status": doc.approval_status,
		"rejection_reason": doc.rejection_reason,
	}


@frappe.whitelist()
@require_flow_builder_access(manage=True)
def start(flow_name: str, conversation: str):
	"""Start one published automation and dispatch its first commands.

	This is the bounded entry point used by managers, custom UIs and MCP. It does
	not accept arbitrary Python actions; the published graph remains the authority.
	"""
	assert_conversation_access(conversation)
	frappe.has_permission("WhatsApp Core Flow", "read", flow_name, throw=True)
	result = start_flow(
		flow_name,
		conversation,
		f"manual:{frappe.session.user}:{uuid.uuid4().hex}",
		{"started_by": frappe.session.user, "source": "Manual"},
	)
	from frappe_whatsapp_core.core_event_handler import _dispatch_commands

	return {
		**result,
		"outbound": _dispatch_commands(conversation, result.get("commands") or []),
	}


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
