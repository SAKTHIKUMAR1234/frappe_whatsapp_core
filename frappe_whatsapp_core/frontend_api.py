"""Site-local API consumed by the separate PrimeVue Core application."""

from __future__ import annotations

import frappe
from frappe.utils import cint

from frappe_whatsapp_core.campaigns import (
	authorize_campaign,
	campaign_summary,
	cancel_campaign,
	create_campaign,
	launch_campaign,
	prepare_campaign,
	revoke_campaign_authorization,
	schedule_campaign,
)
from frappe_whatsapp_core.flow_actions import registered_actions
from frappe_whatsapp_core.hub_client import connection_status
from frappe_whatsapp_core.mcp_tools import TOOL_DEFINITIONS
from frappe_whatsapp_core.permissions import (
	CORE_ACCESS_ROLES,
	require_core_access,
)
from frappe_whatsapp_core.topics import unclassified_messages, upsert_topic


@frappe.whitelist(allow_guest=True)
def bootstrap():
	user = frappe.session.user
	if user == "Guest":
		return {"authenticated": False, "site": frappe.local.site}
	roles = set(frappe.get_roles(user))
	return {
		"authenticated": True,
		"site": frappe.local.site,
		"user": {
			"name": user,
			"full_name": frappe.db.get_value("User", user, "full_name") or user,
			"roles": sorted(roles & CORE_ACCESS_ROLES),
		},
		"can_manage": bool(roles & {"System Manager", "WhatsApp Core Admin", "WhatsApp Core Manager"}),
		"modules": [
			"inbox",
			"dashboard",
			"templates",
			"campaigns",
			"ai-queue",
			"polls",
			"flows",
			"connectors",
			"health",
			"settings",
		],
	}


@frappe.whitelist()
@require_core_access()
def dashboard():
	return {
		"metrics": {
			"configured_flows": frappe.db.count("WhatsApp Core Flow"),
			"active_flows": frappe.db.count(
				"WhatsApp Core Flow",
				{"status": "Published", "enabled": 1},
			),
			"running_instances": frappe.db.count(
				"WhatsApp Core Flow Instance",
				{"status": ["in", ["Running", "Waiting"]]},
			),
			"failed_steps": frappe.db.count(
				"WhatsApp Core Flow Step Run",
				{"status": "Failed"},
			),
		},
		"lifecycle": {
			"draft": frappe.db.count(
				"WhatsApp Core Flow",
				{"status": "Draft"},
			),
			"published": frappe.db.count(
				"WhatsApp Core Flow",
				{"status": "Published"},
			),
			"waiting": frappe.db.count(
				"WhatsApp Core Flow Instance",
				{"status": "Waiting"},
			),
			"completed": frappe.db.count(
				"WhatsApp Core Flow Instance",
				{"status": "Completed"},
			),
		},
		"recent_flows": frappe.get_list(
			"WhatsApp Core Flow",
			fields=["name", "title", "status", "active_version", "modified"],
			order_by="modified desc",
			limit_page_length=6,
		),
	}


@frappe.whitelist()
@require_core_access()
def list_flows():
	return frappe.get_list(
		"WhatsApp Core Flow",
		fields=[
			"name",
			"flow_key",
			"title",
			"description",
			"status",
			"enabled",
			"active_version",
			"modified",
		],
		order_by="modified desc",
		limit_page_length=500,
	)


@frappe.whitelist()
@require_core_access(manage=True)
def create_starter_flow(title, flow_key):
	from frappe_whatsapp_core.flow_templates import create_from_template

	return create_from_template(
		template_key="branched_review",
		flow_key=flow_key,
		title=title,
	)


@frappe.whitelist()
@require_core_access()
def campaign_workspace():
	campaigns = frappe.get_all(
		"WhatsApp Core Campaign",
		fields=["name"],
		order_by="modified desc",
		limit_page_length=500,
	)
	summaries = [campaign_summary(row.name) for row in campaigns]
	return {
		"campaigns": summaries,
		"templates": frappe.get_all(
			"WhatsApp Core Template",
			filters={"enabled": 1},
			fields=[
				"name",
				"template_name",
				"language_code",
				"category",
				"approval_status",
				"body_text",
			],
			order_by="template_name asc",
			limit_page_length=500,
		),
		"channels": frappe.get_all(
			"WhatsApp Core Channel",
			filters={"enabled": 1},
			fields=["name", "display_name", "phone_number_id"],
			order_by="display_name asc",
			limit_page_length=100,
		),
		"metrics": {
			"drafts": sum(
				campaign["status"] in {"Draft", "Prepared"}
				for campaign in summaries
			),
			"scheduled": sum(
				campaign["status"] == "Scheduled"
				for campaign in summaries
			),
			"delivered": sum(
				campaign["delivered_count"] + campaign["read_count"]
				for campaign in summaries
			),
		},
	}


@frappe.whitelist()
@require_core_access()
def template_catalog():
	templates = frappe.get_all(
		"WhatsApp Core Template",
		fields=[
			"name",
			"template_name",
			"language_code",
			"category",
			"approval_status",
			"enabled",
			"header_type",
			"body_text",
			"last_synced_at",
		],
		order_by="template_name asc",
		limit_page_length=500,
	)
	return {
		"templates": templates,
		"metrics": {
			"approved": sum(
				template.approval_status == "APPROVED" and template.enabled
				for template in templates
			),
			"available": sum(bool(template.enabled) for template in templates),
			"disabled": sum(not template.enabled for template in templates),
		},
	}


@frappe.whitelist()
@require_core_access()
def ai_queue_workspace(limit: int = 100):
	limit = max(1, min(int(limit), 250))
	messages = unclassified_messages(limit=limit)
	invocations = frappe.get_all(
		"WhatsApp Core MCP Invocation",
		fields=[
			"name",
			"user",
			"tool_name",
			"status",
			"duration_ms",
			"error",
			"creation",
		],
		order_by="creation desc",
		limit_page_length=25,
	)
	return {
		"messages": messages,
		"invocations": invocations,
		"metrics": {
			"needs_review": len(messages),
			"mcp_completed": frappe.db.count(
				"WhatsApp Core MCP Invocation",
				{"status": "Completed"},
			),
			"mcp_failed": frappe.db.count(
				"WhatsApp Core MCP Invocation",
				{"status": "Failed"},
			),
			"open_topics": frappe.db.count(
				"WhatsApp Core Conversation Topic",
				{"status": ["in", ["Open", "Waiting"]]},
			),
		},
	}


@frappe.whitelist()
@require_core_access(manage=True)
def classify_messages(
	conversation: str,
	title: str,
	message_names,
	summary: str = "",
	category: str = "",
):
	message_names = frappe.parse_json(message_names)
	if not isinstance(message_names, list) or not message_names:
		frappe.throw("Select at least one message")
	return upsert_topic(
		conversation=conversation,
		title=title,
		summary=summary,
		category=category,
		message_names=message_names,
		source="Manual",
		confidence=100,
	)


@frappe.whitelist()
@require_core_access()
def connectors_workspace():
	extension_points = [
		_extension_point(
			"Party resolution",
			"whatsapp_core_party_resolvers",
			"Maps an exact WhatsApp identity to a business party.",
		),
		_extension_point(
			"Party search",
			"whatsapp_core_party_searchers",
			"Provides allowlisted business-party search to operators and AI.",
		),
		_extension_point(
			"Outbound preflight",
			"whatsapp_core_outbound_preflight",
			"Applies optional company safety rules before Core queues a send.",
		),
		_extension_point(
			"Campaign preflight",
			"whatsapp_core_campaign_preflight",
			"Applies company-specific safety gates before a campaign starts.",
		),
		_extension_point(
			"Campaign sender",
			"whatsapp_core_campaign_sender",
			"Resolves and queues one exact recipient at a time.",
			single=True,
		),
	]
	return {
		"mcp_endpoint": "/api/method/frappe_whatsapp_core.mcp_transport.handle",
		"mcp_tools": [
			{
				"name": tool["name"],
				"description": tool.get("description", ""),
			}
			for tool in TOOL_DEFINITIONS
		],
		"flow_actions": registered_actions(),
		"extension_points": extension_points,
		"metrics": {
			"mcp_tools": len(TOOL_DEFINITIONS),
			"flow_actions": len(registered_actions()),
			"configured_extensions": sum(
				item["configured"] for item in extension_points
			),
		},
	}


@frappe.whitelist()
@require_core_access()
def polls_workspace():
	flows = frappe.get_all(
		"WhatsApp Core Flow",
		fields=[
			"name",
			"title",
			"flow_key",
			"status",
			"enabled",
			"active_version",
			"draft_graph",
			"modified",
		],
		order_by="modified desc",
		limit_page_length=500,
	)
	question_flows = []
	for flow in flows:
		graph = frappe.parse_json(flow.draft_graph) if flow.draft_graph else {}
		question_nodes = [
			node
			for node in graph.get("nodes", [])
			if node.get("type") in {"ask_text", "ask_choice"}
		]
		if not question_nodes:
			continue
		question_flows.append({
			"name": flow.name,
			"title": flow.title,
			"flow_key": flow.flow_key,
			"status": flow.status,
			"enabled": bool(flow.enabled),
			"active_version": flow.active_version,
			"question_count": len(question_nodes),
			"choice_count": sum(
				node.get("type") == "ask_choice"
				for node in question_nodes
			),
			"modified": flow.modified,
		})
	return {
		"flows": question_flows,
		"metrics": {
			"drafts": sum(flow["status"] == "Draft" for flow in question_flows),
			"active": sum(
				flow["status"] == "Published" and flow["enabled"]
				for flow in question_flows
			),
			"responses": frappe.db.count(
				"WhatsApp Core Flow Step Run",
				{
					"node_type": ["in", ["ask_text", "ask_choice"]],
					"status": "Completed",
				},
			),
		},
	}


@frappe.whitelist()
@require_core_access()
def health_workspace():
	recent_failures = []
	for doctype, source, fields in (
		(
			"WhatsApp Core Event",
			"Event",
			["name", "event_type", "status", "attempts", "error", "modified"],
		),
		(
			"WhatsApp Core Flow Step Run",
			"Flow",
			["name", "node_id", "status", "attempts", "error", "modified"],
		),
		(
			"WhatsApp Core MCP Invocation",
			"MCP",
			["name", "tool_name", "status", "duration_ms", "error", "modified"],
		),
	):
		for row in frappe.get_all(
			doctype,
			filters={"status": "Failed"},
			fields=fields,
			order_by="modified desc",
			limit_page_length=10,
		):
			row["source"] = source
			row["label"] = (
				row.get("event_type")
				or row.get("node_id")
				or row.get("tool_name")
				or row.name
			)
			recent_failures.append(row)
	recent_failures.sort(
		key=lambda row: str(row.modified),
		reverse=True,
	)
	return {
		"metrics": {
			"pending_events": frappe.db.count(
				"WhatsApp Core Event",
				{"status": ["in", ["Pending", "Processing"]]},
			),
			"failed_events": frappe.db.count(
				"WhatsApp Core Event",
				{"status": "Failed"},
			),
			"failed_flow_steps": frappe.db.count(
				"WhatsApp Core Flow Step Run",
				{"status": "Failed"},
			),
			"failed_messages": frappe.db.count(
				"WhatsApp Core Message",
				{"delivery_status": "Failed"},
			),
		},
		"components": [
			{
				"name": "Core event processor",
				"status": "Attention"
				if frappe.db.count("WhatsApp Core Event", {"status": "Failed"})
				else "Healthy",
				"ownership": "Core",
			},
			{
				"name": "Flow engine",
				"status": "Attention"
				if frappe.db.count(
					"WhatsApp Core Flow Step Run",
					{"status": "Failed"},
				)
				else "Healthy",
				"ownership": "Core",
			},
			{
				"name": "Relay and Meta",
				"status": "External",
				"ownership": "Integration Desk",
			},
		],
		"recent_failures": recent_failures[:25],
	}


@frappe.whitelist()
@require_core_access()
def settings_workspace():
	settings = frappe.get_single("WhatsApp Core Settings")
	return {
		"site": frappe.local.site,
		"time_zone": frappe.db.get_single_value(
			"System Settings",
			"time_zone",
		) or "UTC",
		"channels": frappe.get_all(
			"WhatsApp Core Channel",
			fields=[
				"name",
				"display_name",
				"provider",
				"phone_number_id",
				"enabled",
			],
			order_by="display_name asc",
			limit_page_length=100,
		),
		"workspaces": frappe.get_all(
			"WhatsApp Core Workspace",
			fields=[
				"name",
				"workspace_key",
				"display_name",
				"solution",
				"parent_workspace",
				"enabled",
			],
			order_by="display_name asc",
			limit_page_length=500,
		),
		"solutions": frappe.get_all(
			"WhatsApp Core Solution",
			fields=[
				"name",
				"solution_key",
				"display_name",
				"version",
				"status",
			],
			order_by="display_name asc",
			limit_page_length=100,
		),
		"transport": connection_status(),
		"hub_accounts": [
			{
				"channel": row.channel,
				"account_name": row.account_name,
				"is_default": bool(row.is_default),
			}
			for row in settings.accounts
		],
		"request_timeout": settings.request_timeout or 30,
		"inventory": {
			"identities": frappe.db.count("WhatsApp Core Identity"),
			"verified_bindings": frappe.db.count(
				"WhatsApp Core Party Binding",
				{"status": "Verified"},
			),
			"conversations": frappe.db.count("WhatsApp Core Conversation"),
			"messages": frappe.db.count("WhatsApp Core Message"),
		},
	}


@frappe.whitelist()
@require_core_access(manage=True)
def save_core_settings(
	enabled=0,
	outbound_enabled=0,
	hub_url: str = "",
	accounts=None,
	request_timeout: int = 30,
	api_key: str = "",
	api_secret: str = "",
):
	settings = frappe.get_single("WhatsApp Core Settings")
	settings.enabled = int(bool(cint(enabled)))
	settings.outbound_enabled = int(bool(cint(outbound_enabled)))
	settings.hub_url = str(hub_url or "").strip()
	settings.request_timeout = max(2, min(int(request_timeout or 30), 120))
	accounts = frappe.parse_json(accounts) if accounts is not None else []
	if not isinstance(accounts, list):
		frappe.throw("Hub accounts must be a list")
	settings.set("accounts", accounts)
	if api_key:
		settings.api_key = api_key
	if api_secret:
		settings.api_secret = api_secret
	settings.save()
	return settings_workspace()


@frappe.whitelist()
@require_core_access(manage=True)
def create_campaign_draft(
	title: str,
	campaign_key: str,
	channel: str,
	template: str,
	description: str = "",
):
	doc = create_campaign(
		campaign_key=campaign_key,
		title=title,
		channel=channel,
		template=template,
		description=description,
		audience_source={"provider": "company_layer"},
	)
	return campaign_summary(doc.name)


@frappe.whitelist()
@require_core_access(manage=True)
def prepare_campaign_audience(campaign_name: str, recipients):
	return prepare_campaign(campaign_name, recipients)


@frappe.whitelist()
@require_core_access(manage=True)
def authorize_campaign_send(campaign_name: str, confirmation: str):
	return authorize_campaign(campaign_name, confirmation)


@frappe.whitelist()
@require_core_access(manage=True)
def revoke_campaign_send(campaign_name: str):
	return revoke_campaign_authorization(campaign_name)


@frappe.whitelist()
@require_core_access(manage=True)
def schedule_campaign_send(campaign_name: str, scheduled_for):
	return schedule_campaign(campaign_name, scheduled_for)


@frappe.whitelist()
@require_core_access(manage=True)
def launch_campaign_send(campaign_name: str):
	return launch_campaign(campaign_name)


@frappe.whitelist()
@require_core_access(manage=True)
def cancel_campaign_send(campaign_name: str):
	return cancel_campaign(campaign_name)


def _extension_point(
	label: str,
	hook: str,
	description: str,
	single: bool = False,
) -> dict:
	handlers = frappe.get_hooks(hook) or []
	if isinstance(handlers, dict):
		handlers = list(handlers)
	return {
		"label": label,
		"hook": hook,
		"description": description,
		"configured": len(handlers),
		"status": (
			"Healthy"
			if handlers and (not single or len(handlers) == 1)
			else "Attention"
		),
		"requirement": "Exactly one" if single else "One or more",
	}
