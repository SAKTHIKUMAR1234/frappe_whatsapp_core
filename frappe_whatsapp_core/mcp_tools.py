"""Auditable tool contracts for an external MCP transport and AI client."""

from __future__ import annotations

import json

import frappe

from frappe_whatsapp_core.calling import (
	build_call_deep_link as whatsapp_build_call_deep_link,
)
from frappe_whatsapp_core.calling import (
	call_action as whatsapp_call_action,
)
from frappe_whatsapp_core.calling import (
	calling_workspace as whatsapp_calling_workspace,
)
from frappe_whatsapp_core.calling import (
	get_call_artifact as whatsapp_get_call_artifact,
)
from frappe_whatsapp_core.calling import (
	get_call_permission as whatsapp_get_call_permission,
)
from frappe_whatsapp_core.calling import (
	request_call_permission as whatsapp_request_call_permission,
)
from frappe_whatsapp_core.calling import (
	send_call_button as whatsapp_send_call_button,
)
from frappe_whatsapp_core.calling import (
	send_call_button_template as whatsapp_send_call_button_template,
)
from frappe_whatsapp_core.calling import (
	update_call_settings as whatsapp_update_call_settings,
)
from frappe_whatsapp_core.calling import (
	upload_voicemail_announcement as whatsapp_upload_voicemail_announcement,
)
from frappe_whatsapp_core.cases import create_case
from frappe_whatsapp_core.flow_actions import registered_action_catalog
from frappe_whatsapp_core.flow_api import (
	create_flow as create_automation_flow,
)
from frappe_whatsapp_core.flow_api import (
	get_builder as get_automation_flow,
)
from frappe_whatsapp_core.flow_api import (
	list_flows as list_automation_flows,
)
from frappe_whatsapp_core.flow_api import (
	publish as publish_automation_flow,
)
from frappe_whatsapp_core.flow_api import (
	request_approval as request_automation_flow_approval,
)
from frappe_whatsapp_core.flow_api import (
	save_draft as save_automation_flow,
)
from frappe_whatsapp_core.flow_api import (
	start as start_automation_flow,
)
from frappe_whatsapp_core.flow_api import (
	validate_draft as validate_automation_flow,
)
from frappe_whatsapp_core.flow_responses import list_flow_responses
from frappe_whatsapp_core.groups import (
	change_join_requests as whatsapp_change_join_requests,
)
from frappe_whatsapp_core.groups import (
	create_group as whatsapp_create_group,
)
from frappe_whatsapp_core.groups import (
	delete_group as whatsapp_delete_group,
)
from frappe_whatsapp_core.groups import (
	get_group as whatsapp_get_group,
)
from frappe_whatsapp_core.groups import (
	get_invite_link as whatsapp_get_invite_link,
)
from frappe_whatsapp_core.groups import (
	group_activity as whatsapp_group_activity,
)
from frappe_whatsapp_core.groups import (
	group_workspace as whatsapp_group_workspace,
)
from frappe_whatsapp_core.groups import (
	list_join_requests as whatsapp_list_join_requests,
)
from frappe_whatsapp_core.groups import (
	pin_group_message as whatsapp_pin_group_message,
)
from frappe_whatsapp_core.groups import (
	remove_participants as whatsapp_remove_participants,
)
from frappe_whatsapp_core.groups import (
	reset_invite_link as whatsapp_reset_invite_link,
)
from frappe_whatsapp_core.groups import (
	send_group_invite_template as whatsapp_send_group_invite_template,
)
from frappe_whatsapp_core.groups import (
	send_group_message as whatsapp_send_group_message,
)
from frappe_whatsapp_core.groups import (
	update_group as whatsapp_update_group,
)
from frappe_whatsapp_core.groups import (
	update_group_picture as whatsapp_update_group_picture,
)
from frappe_whatsapp_core.meta_flows import (
	create_flow as create_meta_flow,
)
from frappe_whatsapp_core.meta_flows import (
	delete_flow as delete_meta_flow,
)
from frappe_whatsapp_core.meta_flows import (
	deprecate_flow as deprecate_meta_flow,
)
from frappe_whatsapp_core.meta_flows import (
	flow_endpoint_status as meta_flow_endpoint_status,
)
from frappe_whatsapp_core.meta_flows import (
	flow_workspace as meta_flow_workspace,
)
from frappe_whatsapp_core.meta_flows import (
	get_business_public_key as get_meta_flow_public_key,
)
from frappe_whatsapp_core.meta_flows import (
	get_flow as get_meta_flow,
)
from frappe_whatsapp_core.meta_flows import (
	migrate_flows as migrate_meta_flows,
)
from frappe_whatsapp_core.meta_flows import (
	provision_flow_endpoint as provision_meta_flow_endpoint,
)
from frappe_whatsapp_core.meta_flows import (
	publish_flow as publish_meta_flow,
)
from frappe_whatsapp_core.meta_flows import (
	set_business_public_key as set_meta_flow_public_key,
)
from frappe_whatsapp_core.meta_flows import (
	update_flow as update_meta_flow,
)
from frappe_whatsapp_core.meta_flows import (
	upload_flow_json as upload_meta_flow_json,
)
from frappe_whatsapp_core.party_bindings import upsert_party_binding
from frappe_whatsapp_core.permissions import CORE_MANAGEMENT_ROLES, FLOW_BUILDER_ROLES
from frappe_whatsapp_core.template_catalog import (
	get_template as get_template_projection,
)
from frappe_whatsapp_core.template_catalog import request_template_upsert
from frappe_whatsapp_core.template_catalog import submit_template as submit_template_projection
from frappe_whatsapp_core.topics import (
	list_topics,
	unclassified_messages,
	upsert_topic,
)
from frappe_whatsapp_core.ai_summaries import (
	get_identity_summary,
	summarize_identities,
	summarize_identity,
)
from frappe_whatsapp_core.summary_rollups import get_summary_context
from frappe_whatsapp_core.workspace_api import (
	assign_conversation,
	list_messages,
	list_teams,
	upsert_team,
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
		"name": "whatsapp.get_contact_summary",
		"description": "Read or incrementally refresh the auditable AI summary for one contact.",
		"inputSchema": {
			"type": "object",
			"required": ["identity"],
			"properties": {
				"identity": {"type": "string"},
				"refresh": {"type": "boolean"},
			},
		},
	},
	{
		"name": "whatsapp.summarize_contacts",
		"description": "Compose existing per-contact summaries into one group management overview without resending raw histories.",
		"inputSchema": {
			"type": "object",
			"required": ["identities"],
			"properties": {
				"identities": {"type": "array", "items": {"type": "string"}, "minItems": 1},
				"scope_key": {"type": "string"},
				"refresh": {"type": "boolean"},
			},
		},
	},
	{
		"name": "whatsapp.get_summary_context",
		"description": "Read retained daily, weekly, monthly and yearly context layers for one contact without rescanning raw messages.",
		"inputSchema": {
			"type": "object",
			"required": ["identity"],
			"properties": {
				"identity": {"type": "string"},
				"reference_date": {"type": "string", "format": "date"},
			},
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
	{
		"name": "whatsapp.list_messages",
		"description": "Read a searchable page of messages for infinite-scroll history.",
		"inputSchema": {
			"type": "object",
			"required": ["conversation"],
			"properties": {
				"conversation": {"type": "string"},
				"before": {"type": "string"},
				"before_creation": {"type": "string"},
				"before_name": {"type": "string"},
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
		"name": "whatsapp.send_rich_message",
		"description": "Queue a native media, sticker, reaction, location, contacts, or interactive reply.",
		"inputSchema": {
			"type": "object",
			"required": ["conversation", "message_type", "payload"],
			"properties": {
				"conversation": {"type": "string"},
				"message_type": {
					"type": "string",
					"enum": [
						"audio",
						"contacts",
						"document",
						"image",
						"interactive",
						"location",
						"reaction",
						"sticker",
						"video",
					],
				},
				"payload": {"type": "object"},
				"body": {"type": "string"},
			},
		},
	},
	{
		"name": "whatsapp.mark_conversation_read",
		"description": "Advance the operator read cursor and queue Meta's read receipt for the latest inbound message.",
		"inputSchema": {
			"type": "object",
			"required": ["conversation"],
			"properties": {"conversation": {"type": "string"}, "message": {"type": "string"}},
		},
	},
	{
		"name": "whatsapp.show_typing",
		"description": "Send Meta's typing indicator for the latest inbound message in a conversation.",
		"inputSchema": {
			"type": "object",
			"required": ["conversation"],
			"properties": {"conversation": {"type": "string"}},
		},
	},
	{
		"name": "whatsapp.toggle_message_bookmark",
		"description": "Bookmark or unbookmark a message for the authenticated operator.",
		"inputSchema": {
			"type": "object",
			"required": ["message"],
			"properties": {"message": {"type": "string"}},
		},
	},
	{
		"name": "whatsapp.assign_conversation",
		"description": "Assign a conversation to a team or user and optionally update status.",
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
		"description": "List enabled and disabled support teams with their members.",
		"inputSchema": {"type": "object", "properties": {}},
	},
	{
		"name": "whatsapp.upsert_team",
		"description": "Create or update a support team and its members.",
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
		"description": "List the site-scoped template catalog, exact approval state and account mapping.",
		"inputSchema": {
			"type": "object",
			"properties": {
				"start": {"type": "integer", "minimum": 0},
				"limit": {"type": "integer", "minimum": 1, "maximum": 500},
			},
		},
	},
	{
		"name": "whatsapp.get_template",
		"description": "Read one template projection including canonical Meta components and status diagnostics.",
		"inputSchema": {
			"type": "object",
			"required": ["template_key"],
			"properties": {"template_key": {"type": "string", "minLength": 1}},
		},
	},
	{
		"name": "whatsapp.create_template",
		"description": "Create and assign a lossless WhatsApp template draft, optionally submitting it to Meta.",
		"inputSchema": {
			"type": "object",
			"required": ["account_name", "template_name", "language_code", "category", "components"],
			"additionalProperties": False,
			"properties": {
				"account_name": {"type": "string", "minLength": 1},
				"template_name": {"type": "string", "pattern": "^[a-z0-9_]+$", "maxLength": 512},
				"language_code": {"type": "string", "default": "en", "maxLength": 32},
				"category": {"type": "string", "enum": ["MARKETING", "UTILITY", "AUTHENTICATION"]},
				"parameter_format": {"type": "string", "enum": ["POSITIONAL", "NAMED"], "default": "POSITIONAL"},
				"message_send_ttl_seconds": {"type": "integer", "minimum": 1},
				"components": {
					"type": "array",
					"minItems": 1,
					"maxItems": 100,
					"items": {"type": "object", "required": ["type"]},
				},
				"submit": {"type": "boolean", "default": False},
			},
		},
	},
	{
		"name": "whatsapp.update_template",
		"description": "Save a complete assigned template draft or submit its revision to Meta.",
		"inputSchema": {
			"type": "object",
			"required": ["template_key", "components"],
			"additionalProperties": False,
			"properties": {
				"template_key": {"type": "string", "minLength": 1},
				"category": {"type": "string", "enum": ["MARKETING", "UTILITY", "AUTHENTICATION"]},
				"parameter_format": {"type": "string", "enum": ["POSITIONAL", "NAMED"]},
				"message_send_ttl_seconds": {"type": "integer", "minimum": 1},
				"components": {
					"type": "array",
					"minItems": 1,
					"maxItems": 100,
					"items": {"type": "object", "required": ["type"]},
				},
				"submit": {"type": "boolean", "default": False},
			},
		},
	},
	{
		"name": "whatsapp.submit_template",
		"description": "Submit an existing complete DRAFT template to Meta without changing its component document.",
		"inputSchema": {
			"type": "object",
			"required": ["template_key"],
			"properties": {"template_key": {"type": "string", "minLength": 1}},
		},
	},
	{
		"name": "whatsapp.list_campaigns",
		"description": "List campaign workspace data and delivery metrics.",
		"inputSchema": {"type": "object", "properties": {}},
	},
	{
		"name": "whatsapp.create_campaign",
		"description": "Create a campaign draft using an approved template.",
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
		"description": "Launch a prepared and explicitly authorized campaign.",
		"inputSchema": {
			"type": "object",
			"required": ["campaign_name"],
			"properties": {"campaign_name": {"type": "string"}},
		},
	},
	{
		"name": "whatsapp.prepare_campaign",
		"description": "Replace a draft campaign audience with exact Core identity references.",
		"inputSchema": {
			"type": "object",
			"required": ["campaign_name", "recipients"],
			"properties": {
				"campaign_name": {"type": "string"},
				"recipients": {"type": "array", "items": {"type": "object"}, "maxItems": 10000},
			},
		},
	},
	{
		"name": "whatsapp.authorize_campaign",
		"description": "Record the explicit human send authorization. Confirmation must match AUTHORIZE <campaign key>.",
		"inputSchema": {
			"type": "object",
			"required": ["campaign_name", "confirmation"],
			"properties": {"campaign_name": {"type": "string"}, "confirmation": {"type": "string"}},
		},
	},
	{
		"name": "whatsapp.revoke_campaign_authorization",
		"description": "Revoke authorization before a campaign starts.",
		"inputSchema": {
			"type": "object",
			"required": ["campaign_name"],
			"properties": {"campaign_name": {"type": "string"}},
		},
	},
	{
		"name": "whatsapp.schedule_campaign",
		"description": "Schedule an authorized campaign for a future datetime.",
		"inputSchema": {
			"type": "object",
			"required": ["campaign_name", "scheduled_for"],
			"properties": {"campaign_name": {"type": "string"}, "scheduled_for": {"type": "string"}},
		},
	},
	{
		"name": "whatsapp.cancel_campaign",
		"description": "Cancel a campaign and skip unsent recipients. Requires confirmation=CANCEL.",
		"inputSchema": {
			"type": "object",
			"required": ["campaign_name", "confirmation"],
			"properties": {
				"campaign_name": {"type": "string"},
				"confirmation": {"type": "string", "enum": ["CANCEL"]},
			},
		},
	},
	{
		"name": "whatsapp.list_automation_flows",
		"description": "List site-local visual automation flows.",
		"inputSchema": {
			"type": "object",
			"properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 500}},
		},
	},
	{
		"name": "whatsapp.get_automation_flow",
		"description": "Read a visual automation graph and its registered action catalog.",
		"inputSchema": {
			"type": "object",
			"required": ["flow_name"],
			"properties": {"flow_name": {"type": "string"}},
		},
	},
	{
		"name": "whatsapp.list_flow_actions",
		"description": "List allowlisted Python action paths and their parameter schemas.",
		"inputSchema": {"type": "object", "properties": {}},
	},
	{
		"name": "whatsapp.create_automation_flow",
		"description": "Create a site-local visual automation draft.",
		"inputSchema": {
			"type": "object",
			"required": ["title", "flow_key"],
			"properties": {
				"title": {"type": "string"},
				"flow_key": {"type": "string"},
				"description": {"type": "string"},
				"graph": {"type": "object"},
			},
		},
	},
	{
		"name": "whatsapp.save_automation_flow",
		"description": "Save and validate a complete visual automation graph.",
		"inputSchema": {
			"type": "object",
			"required": ["flow_name", "graph"],
			"properties": {
				"flow_name": {"type": "string"},
				"graph": {"type": "object"},
			},
		},
	},
	{
		"name": "whatsapp.validate_automation_flow",
		"description": "Validate the saved visual graph without publishing it.",
		"inputSchema": {
			"type": "object",
			"required": ["flow_name"],
			"properties": {"flow_name": {"type": "string"}},
		},
	},
	{
		"name": "whatsapp.request_automation_flow_approval",
		"description": "Submit a valid visual automation draft for WhatsApp Manager review.",
		"inputSchema": {
			"type": "object",
			"required": ["flow_name"],
			"properties": {"flow_name": {"type": "string"}},
		},
	},
	{
		"name": "whatsapp.publish_automation_flow",
		"description": "Publish an immutable visual automation version. Requires confirmation=PUBLISH.",
		"inputSchema": {
			"type": "object",
			"required": ["flow_name", "confirmation"],
			"properties": {
				"flow_name": {"type": "string"},
				"confirmation": {"type": "string", "enum": ["PUBLISH"]},
			},
		},
	},
	{
		"name": "whatsapp.list_flow_responses",
		"description": "List durable visual automation, Meta submission, and data-exchange responses.",
		"inputSchema": {
			"type": "object",
			"properties": {
				"flow": {"type": "string"},
				"conversation": {"type": "string"},
				"response_type": {
					"type": "string",
					"enum": ["Automation", "Meta Submission", "Data Exchange"],
				},
				"limit": {"type": "integer", "minimum": 1, "maximum": 500},
			},
		},
	},
	{
		"name": "whatsapp.start_automation_flow",
		"description": "Start one published automation for an accessible conversation. Requires confirmation=START.",
		"inputSchema": {
			"type": "object",
			"required": ["flow_name", "conversation", "confirmation"],
			"properties": {
				"flow_name": {"type": "string"},
				"conversation": {"type": "string"},
				"confirmation": {"type": "string", "enum": ["START"]},
			},
		},
	},
	{
		"name": "whatsapp.list_flows",
		"description": "List native WhatsApp Flows from Meta for a configured Hub account.",
		"inputSchema": {"type": "object", "properties": {"account_name": {"type": "string"}}},
	},
	{
		"name": "whatsapp.get_flow",
		"description": "Read one Meta Flow and its current flow.json asset.",
		"inputSchema": {
			"type": "object",
			"required": ["account_name", "flow_id"],
			"properties": {"account_name": {"type": "string"}, "flow_id": {"type": "string"}},
		},
	},
	{
		"name": "whatsapp.create_flow",
		"description": "Create a draft native WhatsApp Flow directly in Meta.",
		"inputSchema": {
			"type": "object",
			"required": ["account_name", "flow_name", "categories"],
			"properties": {
				"account_name": {"type": "string"},
				"flow_name": {"type": "string"},
				"categories": {"type": "array", "items": {"type": "string"}},
				"endpoint_uri": {"type": "string"},
				"clone_flow_id": {"type": "string"},
			},
		},
	},
	{
		"name": "whatsapp.upload_flow_json",
		"description": "Upload a flow.json asset to Meta and return Meta validation errors.",
		"inputSchema": {
			"type": "object",
			"required": ["account_name", "flow_id", "flow_json"],
			"properties": {
				"account_name": {"type": "string"},
				"flow_id": {"type": "string"},
				"flow_json": {"type": "object"},
			},
		},
	},
	{
		"name": "whatsapp.publish_flow",
		"description": "Irreversibly publish a validated Meta Flow. Requires confirmation=PUBLISH.",
		"inputSchema": {
			"type": "object",
			"required": ["account_name", "flow_id", "confirmation"],
			"properties": {
				"account_name": {"type": "string"},
				"flow_id": {"type": "string"},
				"confirmation": {"type": "string", "enum": ["PUBLISH"]},
			},
		},
	},
	{
		"name": "whatsapp.update_flow",
		"description": "Update draft Meta Flow metadata.",
		"inputSchema": {
			"type": "object",
			"required": ["account_name", "flow_id"],
			"properties": {
				"account_name": {"type": "string"},
				"flow_id": {"type": "string"},
				"flow_name": {"type": "string"},
				"categories": {"type": "array", "items": {"type": "string"}},
				"endpoint_uri": {"type": "string"},
			},
		},
	},
	{
		"name": "whatsapp.deprecate_flow",
		"description": "Deprecate a published Meta Flow. Requires confirmation=DEPRECATE.",
		"inputSchema": {
			"type": "object",
			"required": ["account_name", "flow_id", "confirmation"],
			"properties": {
				"account_name": {"type": "string"},
				"flow_id": {"type": "string"},
				"confirmation": {"type": "string", "enum": ["DEPRECATE"]},
			},
		},
	},
	{
		"name": "whatsapp.delete_flow",
		"description": "Delete an unpublished Meta Flow. Requires confirmation=DELETE.",
		"inputSchema": {
			"type": "object",
			"required": ["account_name", "flow_id", "confirmation"],
			"properties": {
				"account_name": {"type": "string"},
				"flow_id": {"type": "string"},
				"confirmation": {"type": "string", "enum": ["DELETE"]},
			},
		},
	},
	{
		"name": "whatsapp.migrate_flows",
		"description": "Migrate selected native Flows from a source WABA into the mapped destination WABA.",
		"inputSchema": {
			"type": "object",
			"required": ["account_name", "source_waba_id"],
			"properties": {
				"account_name": {"type": "string"},
				"source_waba_id": {"type": "string"},
				"source_flow_names": {"type": "array", "items": {"type": "string"}},
			},
		},
	},
	{
		"name": "whatsapp.get_flow_public_key",
		"description": "Read the business public key used for encrypted WhatsApp Flow data exchange.",
		"inputSchema": {
			"type": "object",
			"required": ["account_name"],
			"properties": {"account_name": {"type": "string"}},
		},
	},
	{
		"name": "whatsapp.set_flow_public_key",
		"description": "Set the business public key used for encrypted WhatsApp Flow data exchange.",
		"inputSchema": {
			"type": "object",
			"required": ["account_name", "business_public_key"],
			"properties": {"account_name": {"type": "string"}, "business_public_key": {"type": "string"}},
		},
	},
	{
		"name": "whatsapp.get_flow_endpoint_status",
		"description": "Read the Integration-owned encrypted Meta Flow endpoint URI and key status.",
		"inputSchema": {
			"type": "object",
			"required": ["account_name"],
			"properties": {"account_name": {"type": "string"}},
		},
	},
	{
		"name": "whatsapp.provision_flow_endpoint",
		"description": "Provision or rotate the Integration-owned encrypted Meta Flow endpoint key and register its public key in Meta.",
		"inputSchema": {
			"type": "object",
			"required": ["account_name"],
			"properties": {"account_name": {"type": "string"}, "rotate": {"type": "boolean"}},
		},
	},
	{
		"name": "whatsapp.list_groups",
		"description": "List Meta-hosted WhatsApp groups for a mapped Hub account.",
		"inputSchema": {
			"type": "object",
			"properties": {
				"account_name": {"type": "string"},
				"limit": {"type": "integer", "minimum": 1, "maximum": 1024},
			},
		},
	},
	{
		"name": "whatsapp.get_group",
		"description": "Read group metadata, participants and approval mode.",
		"inputSchema": {
			"type": "object",
			"required": ["account_name", "group_id"],
			"properties": {"account_name": {"type": "string"}, "group_id": {"type": "string"}},
		},
	},
	{
		"name": "whatsapp.get_group_activity",
		"description": "Read durable Core group state, participants and per-participant message receipts.",
		"inputSchema": {
			"type": "object",
			"required": ["group_id"],
			"properties": {"group_id": {"type": "string"}},
		},
	},
	{
		"name": "whatsapp.create_group",
		"description": "Create a Meta-hosted WhatsApp group.",
		"inputSchema": {
			"type": "object",
			"required": ["account_name", "subject"],
			"properties": {
				"account_name": {"type": "string"},
				"subject": {"type": "string"},
				"description": {"type": "string"},
				"join_approval_mode": {"type": "string", "enum": ["auto_approve", "approval_required"]},
			},
		},
	},
	{
		"name": "whatsapp.update_group",
		"description": "Update group subject or description.",
		"inputSchema": {
			"type": "object",
			"required": ["account_name", "group_id"],
			"properties": {
				"account_name": {"type": "string"},
				"group_id": {"type": "string"},
				"subject": {"type": "string"},
				"description": {"type": "string"},
			},
		},
	},
	{
		"name": "whatsapp.update_group_picture",
		"description": "Upload a base64-encoded group picture.",
		"inputSchema": {
			"type": "object",
			"required": ["account_name", "group_id", "file_content_b64"],
			"properties": {
				"account_name": {"type": "string"},
				"group_id": {"type": "string"},
				"file_content_b64": {"type": "string"},
				"filename": {"type": "string"},
			},
		},
	},
	{
		"name": "whatsapp.delete_group",
		"description": "Delete a WhatsApp group. Requires confirmation=DELETE.",
		"inputSchema": {
			"type": "object",
			"required": ["account_name", "group_id", "confirmation"],
			"properties": {
				"account_name": {"type": "string"},
				"group_id": {"type": "string"},
				"confirmation": {"type": "string", "enum": ["DELETE"]},
			},
		},
	},
	{
		"name": "whatsapp.get_group_invite_link",
		"description": "Read the current group invite link.",
		"inputSchema": {
			"type": "object",
			"required": ["account_name", "group_id"],
			"properties": {"account_name": {"type": "string"}, "group_id": {"type": "string"}},
		},
	},
	{
		"name": "whatsapp.reset_group_invite_link",
		"description": "Invalidate and replace a group invite link. Requires confirmation=RESET.",
		"inputSchema": {
			"type": "object",
			"required": ["account_name", "group_id", "confirmation"],
			"properties": {
				"account_name": {"type": "string"},
				"group_id": {"type": "string"},
				"confirmation": {"type": "string", "enum": ["RESET"]},
			},
		},
	},
	{
		"name": "whatsapp.list_group_join_requests",
		"description": "List pending join requests for a group.",
		"inputSchema": {
			"type": "object",
			"required": ["account_name", "group_id"],
			"properties": {"account_name": {"type": "string"}, "group_id": {"type": "string"}},
		},
	},
	{
		"name": "whatsapp.decide_group_join_requests",
		"description": "Approve or reject selected group join requests.",
		"inputSchema": {
			"type": "object",
			"required": ["account_name", "group_id", "join_requests", "approve"],
			"properties": {
				"account_name": {"type": "string"},
				"group_id": {"type": "string"},
				"join_requests": {"type": "array", "items": {"type": "object"}},
				"approve": {"type": "boolean"},
			},
		},
	},
	{
		"name": "whatsapp.remove_group_participants",
		"description": "Remove participants from a group. Requires confirmation=REMOVE.",
		"inputSchema": {
			"type": "object",
			"required": ["account_name", "group_id", "participants", "confirmation"],
			"properties": {
				"account_name": {"type": "string"},
				"group_id": {"type": "string"},
				"participants": {"type": "array", "items": {"type": "string"}},
				"confirmation": {"type": "string", "enum": ["REMOVE"]},
			},
		},
	},
	{
		"name": "whatsapp.send_group_message",
		"description": "Send a supported text, media or template message to a WhatsApp group.",
		"inputSchema": {
			"type": "object",
			"required": ["account_name", "group_id", "message_type", "content"],
			"properties": {
				"account_name": {"type": "string"},
				"group_id": {"type": "string"},
				"message_type": {
					"type": "string",
					"enum": ["text", "image", "video", "audio", "document", "template"],
				},
				"content": {"type": "object"},
				"idempotency_key": {"type": "string"},
			},
		},
	},
	{
		"name": "whatsapp.send_group_invite_template",
		"description": "Send an approved Meta group-invite template with the required group_id body parameter.",
		"inputSchema": {
			"type": "object",
			"required": ["account_name", "group_id", "template_name"],
			"properties": {
				"account_name": {"type": "string"},
				"group_id": {"type": "string"},
				"template_name": {"type": "string"},
				"language_code": {"type": "string"},
				"to_number": {"type": "string"},
				"recipient": {"type": "string"},
				"additional_body_parameters": {"type": "array", "items": {"type": "object"}},
				"idempotency_key": {"type": "string"},
			},
		},
	},
	{
		"name": "whatsapp.pin_group_message",
		"description": "Pin or unpin a group message.",
		"inputSchema": {
			"type": "object",
			"required": ["account_name", "group_id", "message_id", "operation"],
			"properties": {
				"account_name": {"type": "string"},
				"group_id": {"type": "string"},
				"message_id": {"type": "string"},
				"operation": {"type": "string", "enum": ["pin", "unpin"]},
				"expiration_days": {"type": "integer", "minimum": 1},
			},
		},
	},
	{
		"name": "whatsapp.get_call_settings",
		"description": "Read Calling API settings and recent durable call logs.",
		"inputSchema": {"type": "object", "properties": {"account_name": {"type": "string"}}},
	},
	{
		"name": "whatsapp.update_call_settings",
		"description": "Update Meta Calling API settings.",
		"inputSchema": {
			"type": "object",
			"required": ["account_name", "calling"],
			"properties": {"account_name": {"type": "string"}, "calling": {"type": "object"}},
		},
	},
	{
		"name": "whatsapp.get_call_permission",
		"description": "Check WhatsApp calling permission for a user or business-scoped recipient.",
		"inputSchema": {
			"type": "object",
			"required": ["account_name"],
			"properties": {
				"account_name": {"type": "string"},
				"user_wa_id": {"type": "string"},
				"recipient": {"type": "string"},
				"identity": {"type": "string"},
			},
		},
	},
	{
		"name": "whatsapp.request_call_permission",
		"description": "Send Meta's native call-permission request interaction.",
		"inputSchema": {
			"type": "object",
			"required": ["account_name", "body_text"],
			"properties": {
				"account_name": {"type": "string"},
				"body_text": {"type": "string"},
				"to_number": {"type": "string"},
				"recipient": {"type": "string"},
				"identity": {"type": "string"},
			},
		},
	},
	{
		"name": "whatsapp.send_call_button",
		"description": "Send Meta's native WhatsApp call button interaction.",
		"inputSchema": {
			"type": "object",
			"required": ["account_name", "body_text"],
			"properties": {
				"account_name": {"type": "string"},
				"body_text": {"type": "string"},
				"to_number": {"type": "string"},
				"recipient": {"type": "string"},
				"identity": {"type": "string"},
				"display_text": {"type": "string"},
				"ttl_minutes": {"type": "integer"},
				"payload": {"type": "string"},
				"idempotency_key": {"type": "string"},
			},
		},
	},
	{
		"name": "whatsapp.send_call_button_template",
		"description": "Send an approved template containing a WhatsApp voice-call button.",
		"inputSchema": {
			"type": "object",
			"required": ["account_name", "template_name"],
			"properties": {
				"account_name": {"type": "string"},
				"template_name": {"type": "string"},
				"language_code": {"type": "string"},
				"to_number": {"type": "string"},
				"recipient": {"type": "string"},
				"identity": {"type": "string"},
				"ttl_minutes": {"type": "integer"},
				"payload": {"type": "string"},
				"idempotency_key": {"type": "string"},
			},
		},
	},
	{
		"name": "whatsapp.build_call_deep_link",
		"description": "Build the official wa.me/call deep link for a configured business phone number.",
		"inputSchema": {
			"type": "object",
			"required": ["account_name"],
			"properties": {"account_name": {"type": "string"}, "biz_payload": {"type": "string"}},
		},
	},
	{
		"name": "whatsapp.get_call_artifact",
		"description": "Resolve a Meta call recording or transcript media URL.",
		"inputSchema": {
			"type": "object",
			"required": ["account_name", "media_id"],
			"properties": {"account_name": {"type": "string"}, "media_id": {"type": "string"}},
		},
	},
	{
		"name": "whatsapp.upload_voicemail_announcement",
		"description": "Upload an OPUS OGG Core File for Meta's voicemail announcement use case.",
		"inputSchema": {
			"type": "object",
			"required": ["account_name", "file_url"],
			"properties": {
				"account_name": {"type": "string"},
				"file_url": {"type": "string"},
				"description": {"type": "string"},
			},
		},
	},
	{
		"name": "whatsapp.call_action",
		"description": "Perform a WhatsApp call signaling action using WebRTC SDP.",
		"inputSchema": {
			"type": "object",
			"required": ["account_name", "action"],
			"properties": {
				"account_name": {"type": "string"},
				"action": {
					"type": "string",
					"enum": ["connect", "pre_accept", "accept", "reject", "terminate"],
				},
				"call_id": {"type": "string"},
				"to_number": {"type": "string"},
				"recipient": {"type": "string"},
				"identity": {"type": "string"},
				"sdp_type": {"type": "string", "enum": ["offer", "answer"]},
				"sdp": {"type": "string"},
				"biz_opaque_callback_data": {"type": "string"},
				"recording": {"type": "object"},
				"transcription": {"type": "object"},
			},
		},
	},
]


FLOW_AUTHORING_TOOL_NAMES = {
	"whatsapp.list_automation_flows",
	"whatsapp.get_automation_flow",
	"whatsapp.list_flow_actions",
	"whatsapp.create_automation_flow",
	"whatsapp.save_automation_flow",
	"whatsapp.validate_automation_flow",
	"whatsapp.request_automation_flow_approval",
}


@frappe.whitelist()
def manifest() -> dict:
	permitted = _permitted_tool_names()
	return {
		"name": "frappe-whatsapp-core",
		"version": "0.1.0",
		"tools": [tool for tool in TOOL_DEFINITIONS if tool["name"] in permitted],
		"note": "Bind these audited contracts to the selected MCP transport.",
	}


@frappe.whitelist()
def call_tool(name: str, arguments: dict | str | None = None) -> dict | list:
	if name not in _permitted_tool_names():
		frappe.throw("This MCP role cannot call that WhatsApp tool", frappe.PermissionError)
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
		"whatsapp.list_conversation_topics": (lambda: list_topics(arguments["conversation"])),
		"whatsapp.get_contact_summary": lambda: (
			summarize_identity(arguments["identity"])
			if arguments.get("refresh")
			else get_identity_summary(arguments["identity"])
		),
		"whatsapp.summarize_contacts": lambda: summarize_identities(
			arguments["identities"],
			scope_key=arguments.get("scope_key"),
			force=bool(arguments.get("refresh")),
		),
		"whatsapp.get_summary_context": lambda: get_summary_context(
			arguments["identity"],
			arguments.get("reference_date"),
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
		"whatsapp.list_messages": lambda: list_messages(**arguments),
		"whatsapp.send_text": lambda: _send_reply(
			arguments["conversation"],
			arguments["body"],
		),
		"whatsapp.send_rich_message": lambda: _send_rich_message(arguments),
		"whatsapp.mark_conversation_read": lambda: _mark_conversation_read(arguments),
		"whatsapp.show_typing": lambda: _show_typing(arguments["conversation"]),
		"whatsapp.toggle_message_bookmark": lambda: _toggle_message_bookmark(arguments["message"]),
		"whatsapp.assign_conversation": lambda: assign_conversation(**arguments),
		"whatsapp.list_teams": list_teams,
		"whatsapp.upsert_team": lambda: upsert_team(**arguments),
		"whatsapp.list_templates": lambda: _frontend_call("template_catalog", arguments),
		"whatsapp.get_template": lambda: get_template_projection(arguments["template_key"]),
		"whatsapp.create_template": lambda: request_template_upsert(
			template={key: value for key, value in arguments.items() if key != "submit"},
			submit=arguments.get("submit", False),
		),
		"whatsapp.update_template": lambda: request_template_upsert(
			template={
				key: value
				for key, value in arguments.items()
				if key not in {"template_key", "submit"}
			},
			template_key=arguments["template_key"],
			submit=arguments.get("submit", False),
		),
		"whatsapp.submit_template": lambda: submit_template_projection(
			arguments["template_key"]
		),
		"whatsapp.list_campaigns": lambda: _frontend_call("campaign_workspace"),
		"whatsapp.create_campaign": lambda: _frontend_call(
			"create_campaign_draft",
			arguments,
		),
		"whatsapp.launch_campaign": lambda: _frontend_call(
			"launch_campaign_send",
			{"campaign_name": arguments["campaign_name"]},
		),
		"whatsapp.prepare_campaign": lambda: _frontend_call(
			"prepare_campaign_audience",
			arguments,
		),
		"whatsapp.authorize_campaign": lambda: _frontend_call(
			"authorize_campaign_send",
			arguments,
		),
		"whatsapp.revoke_campaign_authorization": lambda: _frontend_call(
			"revoke_campaign_send",
			arguments,
		),
		"whatsapp.schedule_campaign": lambda: _frontend_call(
			"schedule_campaign_send",
			arguments,
		),
		"whatsapp.cancel_campaign": lambda: _cancel_campaign(arguments),
		"whatsapp.list_automation_flows": lambda: list_automation_flows(
			arguments.get("limit", 500)
		),
		"whatsapp.get_automation_flow": lambda: get_automation_flow(arguments["flow_name"]),
		"whatsapp.list_flow_actions": registered_action_catalog,
		"whatsapp.create_automation_flow": lambda: create_automation_flow(**arguments),
		"whatsapp.save_automation_flow": lambda: save_automation_flow(
			arguments["flow_name"], arguments["graph"]
		),
		"whatsapp.validate_automation_flow": lambda: validate_automation_flow(
			arguments["flow_name"]
		),
		"whatsapp.request_automation_flow_approval": lambda: request_automation_flow_approval(
			arguments["flow_name"]
		),
		"whatsapp.publish_automation_flow": lambda: _publish_automation_flow(arguments),
		"whatsapp.list_flow_responses": lambda: list_flow_responses(**arguments),
		"whatsapp.start_automation_flow": lambda: _start_automation_flow(arguments),
		"whatsapp.list_flows": lambda: meta_flow_workspace(arguments.get("account_name")),
		"whatsapp.get_flow": lambda: get_meta_flow(arguments["account_name"], arguments["flow_id"]),
		"whatsapp.create_flow": lambda: create_meta_flow(**arguments),
		"whatsapp.upload_flow_json": lambda: upload_meta_flow_json(**arguments),
		"whatsapp.publish_flow": lambda: _publish_meta_flow(arguments),
		"whatsapp.update_flow": lambda: update_meta_flow(**arguments),
		"whatsapp.deprecate_flow": lambda: _confirmed_meta_flow(arguments, "DEPRECATE", deprecate_meta_flow),
		"whatsapp.delete_flow": lambda: _confirmed_meta_flow(arguments, "DELETE", delete_meta_flow),
		"whatsapp.migrate_flows": lambda: migrate_meta_flows(**arguments),
		"whatsapp.get_flow_public_key": lambda: get_meta_flow_public_key(**arguments),
		"whatsapp.set_flow_public_key": lambda: set_meta_flow_public_key(**arguments),
		"whatsapp.get_flow_endpoint_status": lambda: meta_flow_endpoint_status(**arguments),
		"whatsapp.provision_flow_endpoint": lambda: provision_meta_flow_endpoint(**arguments),
		"whatsapp.list_groups": lambda: whatsapp_group_workspace(**arguments),
		"whatsapp.get_group": lambda: whatsapp_get_group(**arguments),
		"whatsapp.get_group_activity": lambda: whatsapp_group_activity(**arguments),
		"whatsapp.create_group": lambda: whatsapp_create_group(**arguments),
		"whatsapp.update_group": lambda: whatsapp_update_group(**arguments),
		"whatsapp.update_group_picture": lambda: whatsapp_update_group_picture(**arguments),
		"whatsapp.delete_group": lambda: _confirmed_group_action(arguments, "DELETE", whatsapp_delete_group),
		"whatsapp.get_group_invite_link": lambda: whatsapp_get_invite_link(**arguments),
		"whatsapp.reset_group_invite_link": lambda: _confirmed_group_action(
			arguments, "RESET", whatsapp_reset_invite_link
		),
		"whatsapp.list_group_join_requests": lambda: whatsapp_list_join_requests(**arguments),
		"whatsapp.decide_group_join_requests": lambda: whatsapp_change_join_requests(
			arguments["account_name"],
			arguments["group_id"],
			arguments["join_requests"],
			1 if arguments["approve"] else 0,
		),
		"whatsapp.remove_group_participants": lambda: _confirmed_group_action(
			arguments,
			"REMOVE",
			whatsapp_remove_participants,
			"participants",
		),
		"whatsapp.send_group_message": lambda: whatsapp_send_group_message(**arguments),
		"whatsapp.send_group_invite_template": lambda: whatsapp_send_group_invite_template(**arguments),
		"whatsapp.pin_group_message": lambda: whatsapp_pin_group_message(**arguments),
		"whatsapp.get_call_settings": lambda: whatsapp_calling_workspace(
			account_name=arguments.get("account_name"),
			include_sip_credentials=0,
		),
		"whatsapp.update_call_settings": lambda: whatsapp_update_call_settings(**arguments),
		"whatsapp.get_call_permission": lambda: whatsapp_get_call_permission(**arguments),
		"whatsapp.request_call_permission": lambda: whatsapp_request_call_permission(**arguments),
		"whatsapp.send_call_button": lambda: whatsapp_send_call_button(**arguments),
		"whatsapp.send_call_button_template": lambda: whatsapp_send_call_button_template(**arguments),
		"whatsapp.build_call_deep_link": lambda: whatsapp_build_call_deep_link(**arguments),
		"whatsapp.get_call_artifact": lambda: whatsapp_get_call_artifact(**arguments),
		"whatsapp.upload_voicemail_announcement": lambda: whatsapp_upload_voicemail_announcement(**arguments),
		"whatsapp.call_action": lambda: whatsapp_call_action(**arguments),
	}
	handler = handlers.get(name)
	if not handler:
		frappe.throw("Unknown Core MCP tool")
	return handler()


def _permitted_tool_names() -> set[str]:
	if frappe.session.user == "Guest":
		frappe.throw("Authentication required", frappe.AuthenticationError)
	roles = set(frappe.get_roles())
	if roles & CORE_MANAGEMENT_ROLES:
		return {tool["name"] for tool in TOOL_DEFINITIONS}
	if roles & FLOW_BUILDER_ROLES:
		return set(FLOW_AUTHORING_TOOL_NAMES)
	frappe.throw("WhatsApp MCP access is required", frappe.PermissionError)


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
			frappe.throw(f"Party searcher {searcher_path} returned an invalid result")
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


def _frontend_call(method: str, arguments: dict | None = None):
	handler = frappe.get_attr(f"frappe_whatsapp_core.frontend_api.{method}")
	return handler(**(arguments or {}))


def _publish_meta_flow(arguments: dict):
	if arguments.get("confirmation") != "PUBLISH":
		frappe.throw("Publishing a Meta Flow requires confirmation=PUBLISH", frappe.ValidationError)
	return publish_meta_flow(arguments["account_name"], arguments["flow_id"])


def _publish_automation_flow(arguments: dict):
	if arguments.get("confirmation") != "PUBLISH":
		frappe.throw(
			"Publishing a visual automation requires confirmation=PUBLISH",
			frappe.ValidationError,
		)
	return publish_automation_flow(arguments["flow_name"])


def _start_automation_flow(arguments: dict):
	if arguments.get("confirmation") != "START":
		frappe.throw(
			"Starting a visual automation requires confirmation=START",
			frappe.ValidationError,
		)
	return start_automation_flow(arguments["flow_name"], arguments["conversation"])


def _cancel_campaign(arguments: dict):
	if arguments.get("confirmation") != "CANCEL":
		frappe.throw(
			"Cancelling a campaign requires confirmation=CANCEL",
			frappe.ValidationError,
		)
	return _frontend_call(
		"cancel_campaign_send",
		{"campaign_name": arguments["campaign_name"]},
	)


def _confirmed_meta_flow(arguments: dict, confirmation: str, handler):
	if arguments.pop("confirmation", None) != confirmation:
		frappe.throw(
			f"This Meta Flow action requires confirmation={confirmation}",
			frappe.ValidationError,
		)
	return handler(arguments["account_name"], arguments["flow_id"])


def _confirmed_group_action(
	arguments: dict,
	confirmation: str,
	handler,
	extra_argument: str | None = None,
):
	if arguments.pop("confirmation", None) != confirmation:
		frappe.throw(
			f"This group action requires confirmation={confirmation}",
			frappe.ValidationError,
		)
	values = [arguments["account_name"], arguments["group_id"]]
	if extra_argument:
		values.append(arguments[extra_argument])
	return handler(*values)


def _send_rich_message(arguments: dict) -> dict:
	from frappe_whatsapp_core.outbound import queue_rich

	return queue_rich(
		arguments["conversation"],
		arguments["message_type"],
		arguments["payload"],
		arguments.get("body", ""),
		source="External AI",
	)


def _mark_conversation_read(arguments: dict) -> dict:
	from frappe_whatsapp_core.conversation_reads import mark_conversation_read

	return mark_conversation_read(
		arguments["conversation"],
		arguments.get("message"),
	)


def _show_typing(conversation: str) -> dict:
	from frappe_whatsapp_core.conversation_reads import show_typing

	return show_typing(conversation)


def _toggle_message_bookmark(message: str) -> dict:
	from frappe_whatsapp_core.inbox import toggle_message_bookmark

	return toggle_message_bookmark(message)


def _arguments(arguments) -> dict:
	if arguments is None:
		return {}
	if isinstance(arguments, str):
		arguments = json.loads(arguments)
	if not isinstance(arguments, dict):
		frappe.throw("Tool arguments must be an object")
	return arguments
