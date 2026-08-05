"""Auditable tool contracts for an external MCP transport and AI client."""

from __future__ import annotations

import json

import frappe

from frappe_whatsapp_core.cases import create_case
from frappe_whatsapp_core.party_bindings import upsert_party_binding
from frappe_whatsapp_core.permissions import require_core_access
from frappe_whatsapp_core.topics import (
	list_topics,
	unclassified_messages,
	upsert_topic,
)

TOOL_DEFINITIONS = [
	{
		"name": "whatsapp.list_conversations",
		"description": "List the shared inbox with identity, verified party, latest message and unread context.",
		"inputSchema": {
			"type": "object",
			"properties": {
				"limit": {"type": "integer", "minimum": 1, "maximum": 500},
			},
		},
	},
	{
		"name": "whatsapp.get_conversation",
		"description": "Read one conversation with its messages, topics and verified party bindings.",
		"inputSchema": {
			"type": "object",
			"required": ["conversation"],
			"properties": {
				"conversation": {"type": "string"},
				"message_limit": {
					"type": "integer",
					"minimum": 1,
					"maximum": 250,
				},
			},
		},
	},
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
		"name": "whatsapp.search_parties",
		"description": "Search business parties through installed company adapters before binding an identity.",
		"inputSchema": {
			"type": "object",
			"required": ["query"],
			"properties": {
				"query": {"type": "string", "minLength": 2},
				"party_role": {"type": "string"},
				"limit": {
					"type": "integer",
					"minimum": 1,
					"maximum": 25,
				},
			},
		},
	},
	{
		"name": "whatsapp.bind_party",
		"description": "Bind an exact WhatsApp identity to a selected local business record.",
		"inputSchema": {
			"type": "object",
			"required": [
				"identity",
				"party_doctype",
				"party_name",
				"workspace_key",
			],
			"properties": {
				"identity": {"type": "string"},
				"party_doctype": {"type": "string"},
				"party_name": {"type": "string"},
				"workspace_key": {"type": "string"},
				"party_role": {"type": "string"},
				"attributes": {"type": "object"},
			},
		},
	},
	{
		"name": "whatsapp.send_reply",
		"description": "Queue an optimistic free-form reply through Core and the durable relay.",
		"inputSchema": {
			"type": "object",
			"required": ["conversation", "body"],
			"properties": {
				"conversation": {"type": "string"},
				"body": {
					"type": "string",
					"minLength": 1,
					"maxLength": 4096,
				},
			},
		},
	},
	{
		"name": "whatsapp.start_conversation",
		"description": "Create or find a site-local conversation for a WhatsApp phone number.",
		"inputSchema": {
			"type": "object",
			"required": ["channel", "phone_number"],
			"properties": {
				"channel": {"type": "string"},
				"phone_number": {"type": "string"},
				"display_name": {"type": "string"},
			},
		},
	},
	{
		"name": "whatsapp.send_template",
		"description": "Queue an approved site template, including outside the customer-service window.",
		"inputSchema": {
			"type": "object",
			"required": ["conversation", "template"],
			"properties": {
				"conversation": {"type": "string"},
				"template": {"type": "string"},
				"language_code": {"type": "string"},
				"components": {"type": "array"},
			},
		},
	},
	{
		"name": "whatsapp.update_conversation",
		"description": "Update a conversation status or team assignment.",
		"inputSchema": {
			"type": "object",
			"required": ["conversation"],
			"properties": {
				"conversation": {"type": "string"},
				"status": {
					"type": "string",
					"enum": ["Open", "Pending", "Resolved"],
				},
				"assigned_user": {"type": "string"},
			},
		},
	},
	{
		"name": "whatsapp.get_outbound_status",
		"description": "Inspect relay readiness and whether free-form messaging is permitted now.",
		"inputSchema": {
			"type": "object",
			"properties": {"conversation": {"type": "string"}},
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
		"whatsapp.list_conversations": lambda: _list_conversations(
			arguments.get("limit", 100),
		),
		"whatsapp.get_conversation": lambda: _conversation_snapshot(
			arguments["conversation"],
			arguments.get("message_limit", 100),
		),
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
		"whatsapp.search_parties": lambda: _search_parties(
			arguments["query"],
			arguments.get("party_role"),
			arguments.get("limit", 10),
		),
		"whatsapp.bind_party": lambda: upsert_party_binding(
			identity=arguments["identity"],
			party_doctype=arguments["party_doctype"],
			party_name=arguments["party_name"],
			workspace_key=arguments["workspace_key"],
			party_role=arguments.get("party_role"),
			is_primary=True,
			status="Verified",
			source="External AI",
			attributes=arguments.get("attributes"),
		).as_dict(),
		"whatsapp.send_reply": lambda: _send_reply(
			arguments["conversation"],
			arguments["body"],
		),
		"whatsapp.start_conversation": lambda: _start_conversation(arguments),
		"whatsapp.send_template": lambda: _send_template(arguments),
		"whatsapp.update_conversation": lambda: _update_conversation(arguments),
		"whatsapp.get_outbound_status": lambda: _outbound_status(
			arguments.get("conversation"),
		),
	}
	handler = handlers.get(name)
	if not handler:
		frappe.throw("Unknown Core MCP tool")
	return handler()


def _list_conversations(limit: int) -> list[dict]:
	from frappe_whatsapp_core.inbox import conversations

	return conversations(limit)


def _conversation_snapshot(conversation: str, message_limit: int = 100) -> dict:
	from frappe_whatsapp_core.inbox import conversation as conversation_snapshot

	return conversation_snapshot(
		conversation,
		max(1, min(int(message_limit), 250)),
	)


def _search_parties(
	query: str,
	party_role: str | None = None,
	limit: int = 10,
) -> list[dict]:
	query = str(query or "").strip()
	if len(query) < 2:
		frappe.throw("Party search requires at least two characters")
	limit = max(1, min(int(limit), 25))
	results = []
	for searcher_path in frappe.get_hooks("whatsapp_core_party_searchers"):
		searcher = frappe.get_attr(searcher_path)
		rows = searcher(query=query, party_role=party_role, limit=limit)
		if not isinstance(rows, list):
			frappe.throw(
				f"Party searcher {searcher_path} returned an invalid result"
			)
		for row in rows:
			if isinstance(row, dict):
				results.append(row)
			if len(results) >= limit:
				return results
	return results


def _send_reply(conversation: str, body: str) -> dict:
	from frappe_whatsapp_core.outbound import queue_text

	body = str(body or "").strip()
	if not body:
		frappe.throw("Reply cannot be empty")
	if len(body) > 4096:
		frappe.throw("Reply cannot exceed 4096 characters")
	result = queue_text(
		conversation,
		body,
		source="External AI",
	)
	return {
		"message": result.name,
		"conversation": conversation,
		"delivery_status": result.delivery_status,
	}


def _start_conversation(arguments: dict) -> dict:
	from frappe_whatsapp_core.outbound import start_conversation

	return start_conversation(
		arguments["channel"],
		arguments["phone_number"],
		arguments.get("display_name", ""),
	)


def _send_template(arguments: dict) -> dict:
	from frappe_whatsapp_core.outbound import queue_template

	return queue_template(
		arguments["conversation"],
		arguments["template"],
		arguments.get("language_code", ""),
		arguments.get("components"),
		source="External AI",
	)


def _update_conversation(arguments: dict) -> dict:
	from frappe_whatsapp_core.inbox import update_conversation

	return update_conversation(
		arguments["conversation"],
		arguments.get("status"),
		arguments.get("assigned_user"),
	)


def _outbound_status(conversation: str | None) -> dict:
	from frappe_whatsapp_core.outbound import outbound_state

	return outbound_state(conversation)


def _arguments(arguments) -> dict:
	if arguments is None:
		return {}
	if isinstance(arguments, str):
		arguments = json.loads(arguments)
	if not isinstance(arguments, dict):
		frappe.throw("Tool arguments must be an object")
	return arguments
