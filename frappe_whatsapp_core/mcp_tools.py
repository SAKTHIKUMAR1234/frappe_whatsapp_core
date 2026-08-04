"""Auditable tool contracts for an external MCP transport and AI client."""

from __future__ import annotations

import json

import frappe

from frappe_whatsapp_core.cases import create_case
from frappe_whatsapp_core.flow_api import get_builder
from frappe_whatsapp_core.frontend_api import (
	campaign_workspace,
	create_campaign_draft,
	launch_campaign_send,
	list_flows,
	template_catalog,
)
from frappe_whatsapp_core.permissions import require_core_access
from frappe_whatsapp_core.topics import (
	list_topics,
	unclassified_messages,
	upsert_topic,
)
from frappe_whatsapp_core.workspace_api import (
	assign_conversation,
	get_conversation,
	list_conversations,
	list_messages,
	list_teams,
	send_template,
	send_text,
	upsert_team,
)

TOOL_DEFINITIONS = [
	{
		"name": "whatsapp.list_unclassified_messages",
		"description": "List recent messages that are not assigned to a topic.",
		"inputSchema": {
			"type": "object",
			"properties": {
				"limit": {"type": "integer", "minimum": 1, "maximum": 250},
				"conversation": {"type": "string"},
			},
		},
	},
	{
		"name": "whatsapp.upsert_topic",
		"description": "Create or update a summarized conversation topic and assign messages.",
		"inputSchema": {
			"type": "object",
			"required": ["conversation", "title"],
			"properties": {
				"conversation": {"type": "string"},
				"title": {"type": "string"},
				"summary": {"type": "string"},
				"category": {"type": "string"},
				"status": {
					"type": "string",
					"enum": ["Open", "Waiting", "Resolved", "Archived"],
				},
				"confidence": {"type": "number", "minimum": 0, "maximum": 100},
				"message_names": {
					"type": "array",
					"items": {"type": "string"},
				},
				"topic_name": {"type": "string"},
				"attributes": {"type": "object"},
			},
		},
	},
	{
		"name": "whatsapp.list_conversation_topics",
		"description": "List collapsible summarized topics for one conversation.",
		"inputSchema": {
			"type": "object",
			"required": ["conversation"],
			"properties": {"conversation": {"type": "string"}},
		},
	},
	{
		"name": "whatsapp.create_case",
		"description": "Create a typed business case from a conversation or message.",
		"inputSchema": {
			"type": "object",
			"required": ["case_type", "title"],
			"properties": {
				"case_type": {"type": "string"},
				"title": {"type": "string"},
				"field_values": {"type": "object"},
				"conversation": {"type": "string"},
				"origin_message": {"type": "string"},
			},
		},
	},
	{
		"name": "whatsapp.list_conversations",
		"description": "List accessible WhatsApp conversations with identity, latest-message, and unread state.",
		"inputSchema": {
			"type": "object",
			"properties": {
				"search": {"type": "string"},
				"status": {"type": "string", "enum": ["Open", "Pending", "Resolved"]},
				"team": {"type": "string"},
				"limit": {"type": "integer", "minimum": 1, "maximum": 100},
				"offset": {"type": "integer", "minimum": 0},
			},
		},
	},
	{
		"name": "whatsapp.get_conversation",
		"description": "Get one conversation, its remote identity, assignment, and operator read state.",
		"inputSchema": {
			"type": "object",
			"required": ["conversation"],
			"properties": {"conversation": {"type": "string"}},
		},
	},
	{
		"name": "whatsapp.list_messages",
		"description": "Read one page of messages for infinite-scroll chat history.",
		"inputSchema": {
			"type": "object",
			"required": ["conversation"],
			"properties": {
				"conversation": {"type": "string"},
				"before": {"type": "string"},
				"limit": {"type": "integer", "minimum": 1, "maximum": 100},
				"search": {"type": "string"},
			},
		},
	},
	{
		"name": "whatsapp.send_text",
		"description": "Queue a text reply in an accessible conversation.",
		"inputSchema": {
			"type": "object",
			"required": ["conversation", "body"],
			"properties": {
				"conversation": {"type": "string"},
				"body": {"type": "string", "minLength": 1, "maxLength": 4096},
			},
		},
	},
	{
		"name": "whatsapp.send_template",
		"description": "Queue an approved template in an accessible conversation.",
		"inputSchema": {
			"type": "object",
			"required": ["conversation", "template_name"],
			"properties": {
				"conversation": {"type": "string"},
				"template_name": {"type": "string"},
				"language_code": {"type": "string"},
				"components": {"type": "array", "items": {"type": "object"}},
			},
		},
	},
	{
		"name": "whatsapp.assign_conversation",
		"description": "Assign a conversation to a team/user or update its workflow status.",
		"inputSchema": {
			"type": "object",
			"required": ["conversation"],
			"properties": {
				"conversation": {"type": "string"},
				"team": {"type": "string"},
				"user": {"type": "string"},
				"status": {"type": "string", "enum": ["Open", "Pending", "Resolved"]},
			},
		},
	},
	{
		"name": "whatsapp.list_teams",
		"description": "List WhatsApp operator teams and enabled members.",
		"inputSchema": {"type": "object", "properties": {}},
	},
	{
		"name": "whatsapp.upsert_team",
		"description": "Create or update a WhatsApp operator team.",
		"inputSchema": {
			"type": "object",
			"required": ["team_name"],
			"properties": {
				"team_name": {"type": "string"},
				"description": {"type": "string"},
				"enabled": {"type": "boolean"},
				"members": {"type": "array", "items": {"type": "object"}},
			},
		},
	},
	{
		"name": "whatsapp.list_templates",
		"description": "List the site-local projection of WhatsApp templates and approval state.",
		"inputSchema": {"type": "object", "properties": {}},
	},
	{
		"name": "whatsapp.list_campaigns",
		"description": "List campaign summaries, available templates/channels, and delivery metrics.",
		"inputSchema": {"type": "object", "properties": {}},
	},
	{
		"name": "whatsapp.create_campaign",
		"description": "Create a safe campaign draft. Audience preparation and SEND authorization remain separate.",
		"inputSchema": {
			"type": "object",
			"required": ["title", "campaign_key", "channel", "template"],
			"properties": {
				"title": {"type": "string"},
				"campaign_key": {"type": "string"},
				"channel": {"type": "string"},
				"template": {"type": "string"},
				"description": {"type": "string"},
			},
		},
	},
	{
		"name": "whatsapp.launch_campaign",
		"description": "Launch an already prepared and explicitly authorized campaign.",
		"inputSchema": {
			"type": "object",
			"required": ["campaign_name"],
			"properties": {"campaign_name": {"type": "string"}},
		},
	},
	{
		"name": "whatsapp.list_flows",
		"description": "List automation flows and their publication state.",
		"inputSchema": {"type": "object", "properties": {}},
	},
	{
		"name": "whatsapp.get_flow",
		"description": "Get one flow graph with validation errors.",
		"inputSchema": {
			"type": "object",
			"required": ["flow_name"],
			"properties": {"flow_name": {"type": "string"}},
		},
	},
]


@frappe.whitelist()
@require_core_access()
def manifest() -> dict:
	return {
		"name": "frappe-whatsapp-core",
		"version": "0.1.0",
		"tools": TOOL_DEFINITIONS,
		"note": "Bind these audited contracts to the selected MCP transport.",
	}


@frappe.whitelist()
@require_core_access(manage=True)
def call_tool(name: str, arguments: dict | str | None = None) -> dict | list:
	arguments = _arguments(arguments)
	handlers = {
		"whatsapp.list_unclassified_messages": (
			lambda: unclassified_messages(
				arguments.get("limit", 50),
				arguments.get("conversation"),
			)
		),
		"whatsapp.upsert_topic": lambda: upsert_topic(**arguments),
		"whatsapp.list_conversation_topics": (
			lambda: list_topics(arguments["conversation"])
		),
		"whatsapp.create_case": lambda: create_case(
			arguments["case_type"],
			arguments["title"],
			arguments.get("field_values"),
			arguments.get("conversation"),
			arguments.get("origin_message"),
		).as_dict(),
		"whatsapp.list_conversations": lambda: list_conversations(**arguments),
		"whatsapp.get_conversation": (
			lambda: get_conversation(arguments["conversation"])
		),
		"whatsapp.list_messages": lambda: list_messages(**arguments),
		"whatsapp.send_text": (
			lambda: send_text(arguments["conversation"], arguments["body"])
		),
		"whatsapp.send_template": lambda: send_template(**arguments),
		"whatsapp.assign_conversation": lambda: assign_conversation(**arguments),
		"whatsapp.list_teams": list_teams,
		"whatsapp.upsert_team": lambda: upsert_team(**arguments),
		"whatsapp.list_templates": template_catalog,
		"whatsapp.list_campaigns": campaign_workspace,
		"whatsapp.create_campaign": lambda: create_campaign_draft(**arguments),
		"whatsapp.launch_campaign": (
			lambda: launch_campaign_send(arguments["campaign_name"])
		),
		"whatsapp.list_flows": list_flows,
		"whatsapp.get_flow": lambda: get_builder(arguments["flow_name"]),
	}
	handler = handlers.get(name)
	if not handler:
		frappe.throw("Unknown Core MCP tool")
	return handler()


def _arguments(arguments) -> dict:
	if arguments is None:
		return {}
	if isinstance(arguments, str):
		arguments = json.loads(arguments)
	if not isinstance(arguments, dict):
		frappe.throw("Tool arguments must be an object")
	return arguments
