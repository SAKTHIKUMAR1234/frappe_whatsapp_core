"""Auditable tool contracts for an external MCP transport and AI client."""

from __future__ import annotations

import json

import frappe

from frappe_whatsapp_core.cases import create_case
from frappe_whatsapp_core.permissions import require_core_access
from frappe_whatsapp_core.topics import (
	list_topics,
	unclassified_messages,
	upsert_topic,
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
