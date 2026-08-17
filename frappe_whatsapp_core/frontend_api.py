"""Site-local API consumed by the separate PrimeVue Core application."""

from __future__ import annotations

import csv
import io
import re

import frappe
from frappe.utils import cint

from frappe_whatsapp_core.ai_summaries import (
	get_identity_summary,
	summarize_identities,
	summarize_identity,
)
from frappe_whatsapp_core.campaigns import (
	authorize_campaign,
	campaign_summaries,
	campaign_summary,
	cancel_campaign,
	create_campaign,
	launch_campaign,
	prepare_campaign,
	revoke_campaign_authorization,
	schedule_campaign,
)
from frappe_whatsapp_core.contact_presentation import present_identity_names
from frappe_whatsapp_core.flow_actions import registered_actions
from frappe_whatsapp_core.hub_client import call_management, connection_status
from frappe_whatsapp_core.identity import contact_options, normalize_phone
from frappe_whatsapp_core.mcp_tools import TOOL_DEFINITIONS
from frappe_whatsapp_core.naming import name_by_key, resolve_name
from frappe_whatsapp_core.permissions import (
	CORE_ACCESS_ROLES,
	CORE_APP_ROLES,
	FLOW_BUILDER_ROLES,
	require_core_access,
	require_document_permission,
	require_flow_builder_access,
	require_system_manager,
	require_transport_access,
)
from frappe_whatsapp_core.realtime import publish_invalidation
from frappe_whatsapp_core.topics import unclassified_messages, upsert_topic


@frappe.whitelist(allow_guest=True)
def bootstrap():
	user = frappe.session.user
	if user == "Guest":
		return {"authenticated": False, "authorized": False, "site": frappe.local.site}
	roles = set(frappe.get_roles(user))
	authorized = bool(roles & CORE_APP_ROLES)
	can_manage = bool(roles & {"System Manager", "WhatsApp Manager"})
	can_use_inbox = bool(roles & CORE_ACCESS_ROLES)
	can_build_flows = bool(roles & FLOW_BUILDER_ROLES)
	modules = []
	if can_manage:
		modules = [
			"inbox",
			"dashboard",
			"templates",
			"campaigns",
			"ai-queue",
			"flows",
			"groups",
			"calling",
			"health",
			"teams",
		]
	else:
		if can_use_inbox:
			modules.append("inbox")
	return {
		"authenticated": True,
		"authorized": authorized,
		"site": frappe.local.site,
		"user": {
			"name": user,
			"full_name": frappe.db.get_value("User", user, "full_name") or user,
			"roles": sorted(roles & CORE_APP_ROLES),
		},
		"can_manage": can_manage,
		"can_build_flows": can_build_flows,
		"default_module": (
			"dashboard"
			if can_manage
			else "inbox"
			if can_use_inbox
			else "access-denied"
		),
		"modules": modules,
	}


@frappe.whitelist()
@require_core_access(manage=True)
def onboarding_status():
	"""Return secret-free transport readiness for Integration activation."""
	return _transport_status_payload()


@frappe.whitelist()
@require_transport_access(capability=None)
def transport_identity():
	"""Verify a unified manager or least-privilege service identity."""
	from frappe_whatsapp_core.permissions import current_transport_capability

	capability = current_transport_capability()
	payload = {**_transport_status_payload(), "capability": capability}
	if capability in {"template", "all"}:
		settings = frappe.get_single("WhatsApp Core Settings")
		is_manager = (
			frappe.session.user == "Administrator"
			or "WhatsApp Manager" in set(frappe.get_roles(frappe.session.user))
		)
		payload["allowed_accounts"] = sorted({
			str(row.account_name or "").strip()
			for row in settings.accounts
			if str(row.account_name or "").strip()
			and (is_manager or row.template_service_user == frappe.session.user)
		})
	return payload


@frappe.whitelist(methods=["POST"])
@require_system_manager()
def provision_transport_credentials(
	user_email: str,
	rotate=0,
	capability="all",
	account_name=None,
):
	"""Create or explicitly rotate a dedicated Integration callback identity.

	The API secret is returned once and must be stored in Integration's encrypted
	Connected Site credential fields. Existing Desk/operator users are rejected so
	the machine credential cannot inherit human privileges.
	"""
	from frappe.core.doctype.user.user import generate_keys
	from frappe.utils import validate_email_address

	from frappe_whatsapp_core.permissions import (
		TRANSPORT_CAPABILITY_ROLES,
		is_dedicated_transport_user,
	)
	from frappe_whatsapp_core.setup import ensure_core_roles

	user_email = str(user_email or "").strip().lower()
	if not validate_email_address(user_email):
		frappe.throw("A valid dedicated transport email is required", frappe.ValidationError)
	capability = str(capability or "all").strip().lower()
	if capability == "all":
		role_names = set(TRANSPORT_CAPABILITY_ROLES.values())
	else:
		role_name = TRANSPORT_CAPABILITY_ROLES.get(capability)
		if not role_name:
			frappe.throw("Capability must be all, ingress, template, or flow", frappe.ValidationError)
		role_names = {role_name}
	role_label = ", ".join(sorted(role_names))
	bound_accounts = []
	if capability in {"template", "all"}:
		settings = frappe.get_single("WhatsApp Core Settings")
		mapped_accounts = [
			str(row.account_name or "").strip()
			for row in settings.accounts
			if row.account_name
		]
		requested_account = str(account_name or "").strip()
		if requested_account and requested_account not in mapped_accounts:
			frappe.throw(
				"Core service credentials reference an unmapped account_name",
				frappe.ValidationError,
			)
		if not mapped_accounts:
			frappe.throw("Map at least one Hub account before provisioning Core service credentials")
		if capability == "all":
			bound_accounts = mapped_accounts
		elif requested_account:
			bound_accounts = [requested_account]
		elif len(mapped_accounts) == 1:
			bound_accounts = mapped_accounts
		else:
			frappe.throw(
				"account_name is required when more than one Hub account is mapped",
				frappe.ValidationError,
			)
	ensure_core_roles()
	existing = frappe.db.exists("User", user_email)
	if existing:
		if not is_dedicated_transport_user(user_email, capability=capability):
			frappe.throw(
				"The existing user is not an enabled, service-only Website User with exactly "
				f"the required transport role set ({role_label}). Human, Desk, role-profile, disabled, "
				"or extra-role identities are never reused.",
				frappe.ValidationError,
			)
		user = frappe.get_doc("User", user_email)
		if user.api_key and not cint(rotate):
			frappe.throw(
				"Transport credentials already exist; confirm explicit rotation",
				frappe.ValidationError,
			)
	else:
		user = frappe.get_doc({
			"doctype": "User",
			"email": user_email,
			"first_name": "WhatsApp Core Transport",
			"enabled": 1,
			"user_type": "Website User",
			"send_welcome_email": 0,
			"roles": [{"role": role} for role in sorted(role_names)],
		}).insert(ignore_permissions=True)
	if not is_dedicated_transport_user(user.name, capability=capability):
		frappe.throw(
			"Transport identity provisioning did not produce a least-privilege service user",
			frappe.ValidationError,
		)
	if capability in {"template", "all"}:
		for row in settings.accounts:
			if row.account_name in bound_accounts:
				row.template_service_user = user.name
		settings.save(ignore_permissions=True)
	credentials = generate_keys(user.name)
	return {
		"user": user.name,
		"role": next(iter(role_names)) if len(role_names) == 1 else None,
		"roles": sorted(role_names),
		"capability": capability,
		"account_name": bound_accounts[0] if len(bound_accounts) == 1 else None,
		"allowed_accounts": bound_accounts,
		"api_key": credentials["api_key"],
		"api_secret": credentials["api_secret"],
		"rotated": bool(existing),
	}


def _transport_status_payload():
	settings = frappe.get_single("WhatsApp Core Settings")
	return {
		"site": frappe.local.site,
		"service": "frappe_whatsapp_core_transport",
		"transport": connection_status(),
		"accounts": [
			{
				"channel": row.channel,
				"account_name": row.account_name,
				"is_default": bool(row.is_default),
			}
			for row in settings.accounts
		],
	}


@frappe.whitelist()
@require_core_access(manage=True)
def dashboard():
	return {
		"metrics": {
			"open_conversations": frappe.db.count("WhatsApp Core Conversation", {"status": "Open"}),
			"active_campaigns": frappe.db.count(
				"WhatsApp Core Campaign", {"status": ["in", ["Prepared", "Scheduled", "Running"]]}
			),
			"approved_templates": frappe.db.count(
				"WhatsApp Core Template", {"approval_status": "APPROVED", "enabled": 1}
			),
			"failed_messages": frappe.db.count("WhatsApp Core Message", {"delivery_status": "Failed"}),
		},
	}


@frappe.whitelist()
@require_core_access()
def search_contact_options(search=None, limit=50):
	"""Frappe-style remote contact lookup without loading the whole address book."""
	return contact_options(limit=limit, search=search)


@frappe.whitelist()
@require_core_access(manage=True)
def new_conversation_options():
	"""Return only the operational records needed to start a conversation."""
	return {
		"channels": frappe.get_list(
			"WhatsApp Core Channel",
			filters={"enabled": 1},
			fields=["name", "display_name", "phone_number_id", "enabled"],
			order_by="display_name asc",
			limit_page_length=100,
		),
		"templates": template_catalog()["templates"],
		"contacts": contact_options(limit=50),
	}


@frappe.whitelist()
@require_flow_builder_access()
def list_flows():
	return frappe.get_list(
		"WhatsApp Core Flow",
		fields=[
			"name",
			"flow_key",
			"flow_type",
			"title",
			"description",
			"status",
			"enabled",
			"active_version",
			"approval_status",
			"approval_requested_by",
			"approval_requested_at",
			"approved_by",
			"approved_at",
			"modified",
		],
		order_by="modified desc",
		limit_page_length=500,
	)


@frappe.whitelist()
@require_flow_builder_access()
def create_starter_flow(title, flow_key):
	from frappe_whatsapp_core.flow_templates import create_from_template

	return create_from_template(
		template_key="guided_request",
		flow_key=flow_key,
		title=title,
	)


@frappe.whitelist()
@require_core_access(manage=True)
def campaign_workspace():
	summaries = campaign_summaries(limit=500)
	return {
		"campaigns": summaries,
		"templates": frappe.get_all(
			"WhatsApp Core Template",
			filters={"enabled": 1},
			fields=[
				"name",
				"account_name",
				"channel",
				"template_name",
				"language_code",
				"category",
				"approval_status",
				"body_text",
				"components",
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
		"identities": contact_options(limit=50),
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
@require_core_access(manage=True)
@require_document_permission(
	"WhatsApp Core Campaign", "read", name_argument="campaign_name"
)
def campaign_recipient_page(
	campaign_name: str,
	search: str | None = None,
	status: str | None = None,
	limit: int = 50,
	offset: int = 0,
):
	"""Return one bounded recipient ledger page for an operational campaign view."""
	if not frappe.get_list(
		"WhatsApp Core Campaign",
		filters={"name": campaign_name},
		fields=["name"],
		limit_page_length=1,
	):
		frappe.throw("Campaign not found", frappe.DoesNotExistError)

	limit = max(1, min(cint(limit), 100))
	offset = max(0, cint(offset))
	status = (status or "").strip()
	valid_statuses = {"Prepared", "Queued", "Sent", "Delivered", "Read", "Failed", "Skipped"}
	if status and status not in valid_statuses:
		frappe.throw("Invalid recipient status", frappe.ValidationError)

	filters = {"campaign": campaign_name}
	if status:
		filters["status"] = status
	search = (search or "").strip()
	or_filters = None
	if search:
		pattern = f"%{search[:120]}%"
		identity_names = frappe.get_list(
			"WhatsApp Core Identity",
			or_filters={
				"name": ["like", pattern],
				"display_value": ["like", pattern],
				"normalized_value": ["like", pattern],
			},
			pluck="name",
			limit_page_length=100,
		)
		or_filters = [
			["WhatsApp Core Campaign Recipient", "identity", "in", identity_names or ["__none__"]],
			["WhatsApp Core Campaign Recipient", "last_error", "like", pattern],
		]

	rows = frappe.get_list(
		"WhatsApp Core Campaign Recipient",
		filters=filters,
		or_filters=or_filters,
		fields=[
			"name",
			"identity",
			"status",
			"attempts",
			"last_error",
			"queued_at",
			"completed_at",
			"core_message",
		],
		order_by="creation desc, name desc",
		limit_start=offset,
		limit_page_length=limit + 1,
	)
	has_more = len(rows) > limit
	rows = rows[:limit]
	total_row = frappe.get_list(
		"WhatsApp Core Campaign Recipient",
		filters=filters,
		or_filters=or_filters,
		fields=["count(name) as count"],
		limit_page_length=1,
	)
	total = cint(total_row[0].count) if total_row else 0

	identity_names = [row.identity for row in rows]
	identities = {
		row.name: row
		for row in frappe.get_list(
			"WhatsApp Core Identity",
			filters={"name": ["in", identity_names]},
			fields=["name", "display_value", "normalized_value"],
			limit_page_length=max(1, len(identity_names)),
		)
	} if identity_names else {}
	message_names = [row.core_message for row in rows if row.core_message]
	messages = {
		row.name: row
		for row in frappe.get_list(
			"WhatsApp Core Message",
			filters={"name": ["in", message_names]},
			fields=[
				"name",
				"provider_message_id",
				"provider_timestamp",
				"delivery_status",
				"failure",
			],
			limit_page_length=max(1, len(message_names)),
		)
	} if message_names else {}
	presentations = present_identity_names(
		identity_names,
		context={"surface": "campaign_recipients", "campaign": campaign_name},
	)
	for row in rows:
		identity = identities.get(row.identity) or {}
		message = messages.get(row.core_message) or {}
		presentation = presentations.get(row.identity) or {}
		row.display_name = (
			presentation.get("display_name")
			or identity.get("display_value")
			or identity.get("normalized_value")
			or row.identity
		)
		row.secondary_text = presentation.get("secondary_text") or identity.get("normalized_value") or ""
		row.status = message.get("delivery_status") or row.status
		row.provider_message_id = message.get("provider_message_id")
		row.provider_timestamp = message.get("provider_timestamp")
		row.failure = message.get("failure")

	counts = {
		row.status: row.count
		for row in frappe.get_list(
			"WhatsApp Core Campaign Recipient",
			filters={"campaign": campaign_name},
			fields=["status", "count(name) as count"],
			group_by="status",
			limit_page_length=20,
		)
	}
	return {
		"rows": rows,
		"total": total,
		"loaded": offset + len(rows),
		"has_more": has_more,
		"counts": counts,
	}


@frappe.whitelist()
@require_core_access(manage=True)
def template_catalog(start=0, limit=100):
	"""Return the complete authoring catalog to Core management users only."""
	start = max(0, int(start or 0))
	limit = max(1, min(int(limit or 100), 500))
	templates = frappe.get_list(
		"WhatsApp Core Template",
		fields=[
			"name",
			"account_name",
			"channel",
			"template_name",
			"language_code",
			"category",
			"approval_status",
			"status_reason",
			"correct_category",
			"enabled",
			"hub_template_name",
			"template_id",
			"message_send_ttl_seconds",
			"parameter_format",
			"template_source",
			"header_type",
			"header_content",
			"body_text",
			"footer_text",
			"components",
			"last_synced_at",
		],
		order_by="template_name asc",
		limit_start=start,
		limit_page_length=limit,
	)
	total = frappe.db.count("WhatsApp Core Template")
	settings = frappe.get_single("WhatsApp Core Settings")
	accounts = [
		{
			"account_name": row.account_name,
			"channel": row.channel,
			"display_name": frappe.db.get_value(
				"WhatsApp Core Channel", row.channel, "display_name"
			) or row.account_name,
		}
		for row in settings.accounts
		if row.account_name and row.channel
	]
	return {
		"templates": templates,
		"total": total,
		"loaded": start + len(templates),
		"has_more": start + len(templates) < total,
		"accounts": accounts,
		"metrics": {
			"approved": frappe.db.count(
				"WhatsApp Core Template", {"approval_status": "APPROVED", "enabled": 1}
			),
			"available": frappe.db.count("WhatsApp Core Template", {"enabled": 1}),
			"disabled": frappe.db.count("WhatsApp Core Template", {"enabled": 0}),
		},
	}


@frappe.whitelist()
@require_core_access(manage=True)
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
@require_core_access()
def contact_summary(identity: str, refresh: int = 0):
	"""Read one incremental summary; only managers may spend AI tokens."""
	if cint(refresh):
		roles = set(frappe.get_roles())
		if not roles & {"System Manager", "WhatsApp Manager"}:
			frappe.throw("WhatsApp Core management access is required", frappe.PermissionError)
		return summarize_identity(identity)
	return get_identity_summary(identity)


@frappe.whitelist()
@require_core_access(manage=True)
def contact_group_summary(identities, scope_key: str | None = None, refresh: int = 0):
	identities = frappe.parse_json(identities) if isinstance(identities, str) else identities
	return summarize_identities(
		identities or [],
		scope_key=scope_key,
		force=bool(cint(refresh)),
	)


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
@require_core_access(manage=True)
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
@require_core_access(manage=True)
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
@require_core_access(manage=True)
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
@require_system_manager()
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
		"default_country_calling_code": settings.default_country_calling_code or "91",
		"ai_summary": {
			"enabled": bool(settings.enable_ai_summaries),
			"action": settings.summary_i2a_action or "",
			"batch_size": settings.summary_batch_size or 100,
			"max_media_mb": settings.summary_max_media_mb or 15,
			"configured": bool(
				settings.summary_i2a_action
				and frappe.db.exists("I2A Action", settings.summary_i2a_action)
			),
		},
		"i2a_actions": (
			frappe.get_all(
				"I2A Action",
				filters={"enabled": 1},
				fields=["name", "action_name", "purpose"],
				order_by="action_name asc",
				limit_page_length=100,
			)
			if frappe.db.exists("DocType", "I2A Action")
			else []
		),
		"contact_sources": _contact_sources(),
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
@require_system_manager()
def discover_hub_accounts():
	"""Return tenant-scoped Hub accounts without exposing Meta credentials."""
	result = call_management(
		"frappe_whatsapp_hub.frappe_whatsapp_hub.api.onboarding.list_site_accounts"
	)
	return result.get("accounts") or []


def _contact_sources() -> list[dict]:
	return frappe.get_all(
		"WhatsApp Core Identity Source",
		fields=[
			"name",
			"source_key",
			"display_name",
			"source_doctype",
			"enabled",
			"auto_resolve",
			"priority",
			"phone_field",
			"display_name_field",
			"entity_type_field",
			"filters",
		],
		order_by="priority asc, display_name asc",
		limit_page_length=500,
	)


@frappe.whitelist()
@require_system_manager()
def contact_source_doctypes(search: str = "") -> list[dict]:
	filters = {"istable": 0, "issingle": 0}
	if search:
		filters["name"] = ["like", f"%{str(search).strip()}%"]
	return frappe.get_all(
		"DocType",
		filters=filters,
		fields=["name", "module"],
		order_by="name asc",
		limit_page_length=500,
	)


@frappe.whitelist()
@require_system_manager()
def contact_source_fields(source_doctype: str) -> dict:
	if not frappe.db.exists("DocType", source_doctype):
		frappe.throw("Select a valid source DocType", frappe.ValidationError)
	meta = frappe.get_meta(source_doctype)
	ignored = {
		"Section Break",
		"Column Break",
		"Tab Break",
		"HTML",
		"Button",
		"Fold",
		"Heading",
	}
	fields = []
	phone_fields = []
	phone_fieldtypes = {"Data", "Phone", "Read Only", "Small Text", "Text", "Long Text"}
	for field in meta.fields:
		if field.fieldtype == "Table" and field.options:
			child_meta = frappe.get_meta(field.options)
			for child in child_meta.fields:
				if child.fieldtype in ignored or child.fieldtype in {"Table", "Table MultiSelect"}:
					continue
				option = {
					"label": f"{field.label or field.fieldname} → {child.label or child.fieldname}",
					"value": f"{field.fieldname}.{child.fieldname}",
				}
				if child.fieldtype in phone_fieldtypes:
					phone_fields.append(option)
			continue
		if field.fieldtype in ignored or field.fieldtype in {"Table", "Table MultiSelect"}:
			continue
		option = {
			"label": field.label or field.fieldname,
			"value": field.fieldname,
			"fieldtype": field.fieldtype,
		}
		fields.append(option)
		if field.fieldtype in phone_fieldtypes:
			phone_fields.append(option)
	return {"fields": fields, "phone_fields": phone_fields}


@frappe.whitelist()
@require_system_manager()
def save_contact_source(source):
	payload = frappe.parse_json(source) if isinstance(source, str) else source
	if not isinstance(payload, dict):
		frappe.throw("Contact source must be an object", frappe.ValidationError)
	source_key = frappe.scrub(payload.get("source_key") or payload.get("source_doctype") or "")
	if not source_key:
		frappe.throw("Source key is required", frappe.ValidationError)
	name = str(payload.get("name") or "").strip()
	record_name = resolve_name("WhatsApp Core Identity Source", name) if name else None
	record_name = record_name or name_by_key("WhatsApp Core Identity Source", source_key)
	doc = (
		frappe.get_doc("WhatsApp Core Identity Source", record_name)
		if record_name
		else frappe.new_doc("WhatsApp Core Identity Source")
	)
	if not doc.is_new() and doc.source_key != source_key:
		frappe.throw("Source key cannot be changed after creation", frappe.ValidationError)
	doc.update({
		"source_key": source_key,
		"display_name": str(payload.get("display_name") or payload.get("source_doctype") or "").strip(),
		"source_doctype": payload.get("source_doctype"),
		"enabled": cint(payload.get("enabled", 1)),
		"auto_resolve": cint(payload.get("auto_resolve", 1)),
		"priority": max(1, cint(payload.get("priority") or 100)),
		"phone_field": str(payload.get("phone_field") or "").strip(),
		"display_name_field": str(payload.get("display_name_field") or "").strip(),
		"entity_type_field": str(payload.get("entity_type_field") or "").strip(),
		"filters": payload.get("filters") or "{}",
	})
	if doc.is_new():
		doc.insert()
	else:
		doc.save()
	publish_invalidation("whatsapp_core_contact_sources")
	return doc.as_dict()


@frappe.whitelist()
@require_system_manager()
def save_core_settings(
	enabled=0,
	outbound_enabled=0,
	hub_url: str = "",
	relay_url: str = "",
	accounts=None,
	request_timeout: int = 30,
	default_country_calling_code: str = "91",
	api_key: str = "",
	api_secret: str = "",
):
	settings = frappe.get_single("WhatsApp Core Settings")
	settings.enabled = int(bool(cint(enabled)))
	settings.outbound_enabled = int(bool(cint(outbound_enabled)))
	settings.hub_url = str(hub_url or "").strip()
	settings.relay_url = str(relay_url or "").strip()
	settings.request_timeout = max(2, min(int(request_timeout or 30), 120))
	settings.default_country_calling_code = str(default_country_calling_code or "91")
	accounts = _validated_hub_account_mappings(accounts)
	settings.set("accounts", accounts)
	if api_key:
		settings.api_key = api_key
	if api_secret:
		settings.api_secret = api_secret
	settings.save()
	return settings_workspace()


@frappe.whitelist()
@require_system_manager()
def save_ai_summary_settings(
	enabled=0,
	action: str = "",
	batch_size: int = 50,
	max_media_mb: int = 15,
):
	settings = frappe.get_single("WhatsApp Core Settings")
	action = str(action or "").strip()
	if cint(enabled):
		if not action or not frappe.db.exists("I2A Action", action):
			frappe.throw("Select a valid Frappe Tools I2A Action", frappe.ValidationError)
		if not cint(frappe.db.get_value("I2A Action", action, "enabled")):
			frappe.throw("The selected I2A Action is disabled", frappe.ValidationError)
	settings.enable_ai_summaries = int(bool(cint(enabled)))
	settings.summary_i2a_action = action
	settings.summary_batch_size = max(1, min(cint(batch_size) or 100, 250))
	settings.summary_max_media_mb = max(1, min(cint(max_media_mb) or 15, 50))
	settings.save()
	return settings_workspace()


def _validated_hub_account_mappings(accounts) -> list[dict]:
	accounts = frappe.parse_json(accounts) if accounts is not None else []
	if not isinstance(accounts, list):
		frappe.throw("Hub accounts must be a list", frappe.ValidationError)
	normalized = []
	channels = set()
	account_names = set()
	default_count = 0
	for index, row in enumerate(accounts, start=1):
		if not isinstance(row, dict):
			frappe.throw(f"Hub account mapping row {index} is invalid", frappe.ValidationError)
		channel = str(row.get("channel") or "").strip()
		account_name = str(row.get("account_name") or "").strip()
		if not channel or not frappe.db.exists("WhatsApp Core Channel", channel):
			frappe.throw(f"Select a valid Core channel in row {index}", frappe.ValidationError)
		if not account_name:
			frappe.throw(f"Select a Hub account in row {index}", frappe.ValidationError)
		if channel in channels:
			frappe.throw(f"Core channel {channel} is mapped more than once", frappe.ValidationError)
		if account_name in account_names:
			frappe.throw(f"Hub account {account_name} is mapped more than once", frappe.ValidationError)
		is_default = bool(cint(row.get("is_default")))
		default_count += int(is_default)
		channels.add(channel)
		account_names.add(account_name)
		normalized.append({
			"channel": channel,
			"account_name": account_name,
			"is_default": is_default,
		})
	if default_count > 1:
		frappe.throw("Only one Hub account can be the default", frappe.ValidationError)
	if len(normalized) == 1 and default_count == 0:
		normalized[0]["is_default"] = True
	return normalized


@frappe.whitelist()
@require_core_access(manage=True)
def create_campaign_draft(
	title: str,
	campaign_key: str,
	channel: str,
	template: str = "",
	content_type: str = "Template",
	message_text: str = "",
	description: str = "",
):
	doc = create_campaign(
		campaign_key=campaign_key,
		title=title,
		channel=channel,
		template=template,
		content_type=content_type,
		message_text=message_text,
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
def preview_campaign_audience_csv(csv_text: str) -> dict:
	"""Resolve a bounded CSV into exact Core identities without persisting it."""
	if not isinstance(csv_text, str):
		frappe.throw("CSV content is required", frappe.ValidationError)
	if len(csv_text.encode("utf-8")) > 2_000_000:
		frappe.throw("Audience CSV cannot exceed 2 MB", frappe.ValidationError)
	reader = csv.DictReader(io.StringIO(csv_text.lstrip("\ufeff")))
	if not reader.fieldnames:
		frappe.throw("Audience CSV requires a header row", frappe.ValidationError)
	identifier_fields = ("identity", "contact", "phone", "phone_number", "mobile")
	parsed_rows = []
	errors = []
	default_country_code = (
		frappe.db.get_single_value("WhatsApp Core Settings", "default_country_calling_code")
		or "91"
	)
	for row_number, raw in enumerate(reader, start=2):
		if len(parsed_rows) + len(errors) >= 10_000:
			frappe.throw("Audience CSV cannot exceed 10,000 data rows", frappe.ValidationError)
		row = {str(key or "").strip().lower(): str(value or "").strip() for key, value in raw.items()}
		if not any(row.values()):
			continue
		identifier = next((row.get(field) for field in identifier_fields if row.get(field)), "")
		if not identifier:
			errors.append({"row": row_number, "error": "Missing identity or phone column value"})
			continue
		try:
			normalized = normalize_phone(
				identifier,
				assume_local=True,
				country_code=default_country_code,
			)
		except (TypeError, ValueError, frappe.ValidationError):
			normalized = ""
		try:
			components = _csv_template_components(row)
		except (TypeError, ValueError, frappe.ValidationError) as exception:
			errors.append({"row": row_number, "error": str(exception)})
			continue
		parsed_rows.append({
			"identifier": identifier,
			"normalized": normalized,
			"personalization": {
				"components": components,
				"text": row.get("message") or row.get("text") or "",
			},
			"source_row": row_number,
		})

	identity_by_name = _active_whatsapp_identity_map(
		"name", {row["identifier"] for row in parsed_rows}
	)
	identity_by_phone = _active_whatsapp_identity_map(
		"normalized_value", {row["normalized"] for row in parsed_rows if row["normalized"]}
	)
	rows = []
	for row in parsed_rows:
		identity = identity_by_name.get(row["identifier"]) or identity_by_phone.get(
			row["normalized"]
		)
		if not identity:
			errors.append({"row": row["source_row"], "error": "Active Core contact not found"})
			continue
		rows.append({
			"identity": identity,
			"personalization": row["personalization"],
			"source_row": row["source_row"],
		})

	deduplicated = {row["identity"]: row for row in rows}
	presentations = present_identity_names(
		list(deduplicated), context={"surface": "campaign_csv_preview"}
	)
	contacts = [
		{
			"identity": identity,
			"label": presentations.get(identity, {}).get("display_name") or identity,
			"phone_number": presentations.get(identity, {}).get("secondary_text") or "",
			"reference": presentations.get(identity, {}).get("reference") or "",
			"presentation": presentations.get(identity, {}),
		}
		for identity in deduplicated
	]
	return {
		"recipients": list(deduplicated.values()),
		"contacts": contacts,
		"errors": errors[:100],
		"error_count": len(errors),
		"resolved_count": len(deduplicated),
	}


def _active_whatsapp_identity_map(fieldname: str, values: set[str]) -> dict[str, str]:
	"""Resolve a bounded audience in chunks instead of issuing queries per CSV row."""
	if fieldname not in {"name", "normalized_value"}:
		raise ValueError("Unsupported identity lookup field")
	ordered_values = sorted(value for value in values if value)
	resolved = {}
	for offset in range(0, len(ordered_values), 500):
		chunk = ordered_values[offset : offset + 500]
		for identity in frappe.get_all(
			"WhatsApp Core Identity",
			filters={
				"identity_type": "WhatsApp",
				"status": "Active",
				fieldname: ["in", chunk],
			},
			fields=["name", "normalized_value"],
			limit_page_length=len(chunk),
		):
			key = identity.get(fieldname)
			if key:
				resolved[key] = identity.name
	return resolved


def _csv_template_components(row: dict) -> list[dict]:
	raw_components = row.get("components_json") or row.get("components")
	if raw_components:
		components = frappe.parse_json(raw_components)
		if not isinstance(components, list):
			raise frappe.ValidationError("components_json must contain a JSON list")
		return components

	components = []
	for component_type in ("header", "body"):
		values = sorted(
			(
				(int(match.group(1)), value)
				for key, value in row.items()
				if value and (match := re.fullmatch(rf"{component_type}_(\d+)", key))
			),
			key=lambda item: item[0],
		)
		if values:
			components.append({
				"type": component_type,
				"parameters": [{"type": "text", "text": value} for _, value in values],
			})
	buttons = sorted(
		(
			(int(match.group(1)), value)
			for key, value in row.items()
			if value and (match := re.fullmatch(r"button_(\d+)", key))
		),
		key=lambda item: item[0],
	)
	for index, value in buttons:
		components.append({
			"type": "button",
			"sub_type": "url",
			"index": str(index),
			"parameters": [{"type": "text", "text": value}],
		})
	return components


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
