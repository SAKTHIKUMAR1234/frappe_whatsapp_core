"""Reusable conversation, message, team, and outbound APIs for `/whatsapp`."""

from __future__ import annotations

import json

import frappe

from frappe_whatsapp_core.conversation_reads import mark_conversation_read
from frappe_whatsapp_core.permissions import (
	CORE_MANAGEMENT_ROLES,
	require_core_access,
)


@frappe.whitelist()
@require_core_access()
def list_conversations(
	search: str | None = None,
	status: str | None = None,
	team: str | None = None,
	limit: int = 50,
	offset: int = 0,
) -> dict:
	limit = min(max(int(limit or 50), 1), 100)
	offset = max(int(offset or 0), 0)
	conditions, values = _conversation_conditions("conversation")
	if status:
		conditions.append("conversation.status = %(status)s")
		values["status"] = status
	if team:
		conditions.append("conversation.assigned_team = %(team)s")
		values["team"] = team
	if search:
		conditions.append(
			"""(
				identity.display_value LIKE %(search)s
				OR identity.normalized_value LIKE %(search)s
				OR conversation.conversation_key LIKE %(search)s
				OR last_message.body LIKE %(search)s
			)"""
		)
		values["search"] = f"%{search.strip()}%"
	values.update({"limit": limit, "offset": offset, "user": frappe.session.user})
	where = " AND ".join(conditions)
	rows = frappe.db.sql(
		f"""
		SELECT
			conversation.name,
			conversation.conversation_key,
			conversation.status,
			conversation.channel,
			conversation.assigned_team,
			conversation.assigned_user,
			conversation.last_inbound_at,
			conversation.last_message_at,
			identity.name AS identity,
			identity.display_value,
			identity.normalized_value,
			identity.attributes,
			last_message.body AS last_message_body,
			last_message.message_type AS last_message_type,
			last_message.direction AS last_message_direction,
			COALESCE(SUM(
				CASE
					WHEN message.direction = 'Inbound'
						AND message.provider_timestamp > COALESCE(reader.last_read_at, '1970-01-01')
					THEN 1 ELSE 0
				END
			), 0) AS unread_count
		FROM `tabWhatsApp Core Conversation` conversation
		JOIN `tabWhatsApp Core Identity` identity
			ON identity.name = conversation.remote_identity
		LEFT JOIN `tabWhatsApp Core Message` last_message
			ON last_message.name = (
				SELECT newest.name
				FROM `tabWhatsApp Core Message` newest
				WHERE newest.conversation = conversation.name
				ORDER BY newest.provider_timestamp DESC, newest.creation DESC
				LIMIT 1
			)
		LEFT JOIN `tabWhatsApp Core Message` message
			ON message.conversation = conversation.name
		LEFT JOIN `tabWhatsApp Core Conversation Read` reader
			ON reader.conversation = conversation.name AND reader.user = %(user)s
		WHERE {where}
		GROUP BY conversation.name
		ORDER BY conversation.last_message_at DESC
		LIMIT %(limit)s OFFSET %(offset)s
		""",
		values,
		as_dict=True,
	)
	for row in rows:
		row.unread_count = int(row.unread_count or 0)
		row.attributes = _json_dict(row.attributes)
	return {
		"rows": rows,
		"limit": limit,
		"offset": offset,
		"has_more": len(rows) == limit,
	}


@frappe.whitelist()
@require_core_access()
def get_conversation(conversation: str) -> dict:
	_assert_conversation_access(conversation)
	doc = frappe.get_doc("WhatsApp Core Conversation", conversation)
	identity = frappe.get_doc("WhatsApp Core Identity", doc.remote_identity)
	return {
		**doc.as_dict(),
		"identity": {
			"name": identity.name,
			"display_value": identity.display_value,
			"normalized_value": identity.normalized_value,
			"attributes": _json_dict(identity.attributes),
		},
		"readers": frappe.get_all(
			"WhatsApp Core Conversation Read",
			filters={"conversation": conversation},
			fields=["user", "last_read_message", "last_read_at"],
			order_by="last_read_at desc",
			limit_page_length=100,
		),
	}


@frappe.whitelist()
@require_core_access()
def list_messages(
	conversation: str,
	before: str | None = None,
	limit: int = 50,
	search: str | None = None,
) -> dict:
	_assert_conversation_access(conversation)
	limit = min(max(int(limit or 50), 1), 100)
	filters = ["conversation = %(conversation)s"]
	values = {"conversation": conversation, "limit": limit + 1}
	if before:
		filters.append("provider_timestamp < %(before)s")
		values["before"] = before
	if search:
		filters.append("body LIKE %(search)s")
		values["search"] = f"%{search.strip()}%"
	rows = frappe.db.sql(
		f"""
		SELECT
			name, message_key, provider_message_id, direction, message_type,
			body, content, provider_timestamp, delivery_status, failure, creation
		FROM `tabWhatsApp Core Message`
		WHERE {" AND ".join(filters)}
		ORDER BY provider_timestamp DESC, creation DESC
		LIMIT %(limit)s
		""",
		values,
		as_dict=True,
	)
	has_more = len(rows) > limit
	rows = rows[:limit]
	for row in rows:
		row.content = _json_dict(row.content)
		row.failure = _json_dict(row.failure)
	return {
		"rows": rows,
		"has_more": has_more,
		"next_before": rows[-1].provider_timestamp if has_more and rows else None,
	}


@frappe.whitelist()
@require_core_access()
def mark_read(conversation: str, message: str | None = None) -> dict:
	_assert_conversation_access(conversation)
	return mark_conversation_read(conversation, message)


@frappe.whitelist()
@require_core_access()
def send_text(conversation: str, body: str) -> dict:
	_assert_conversation_access(conversation)
	body = (body or "").strip()
	if not body:
		frappe.throw("Message cannot be empty", frappe.ValidationError)
	if len(body) > 4096:
		frappe.throw("Message cannot exceed 4096 characters", frappe.ValidationError)
	return _outbound_handler("whatsapp_core_outbound_text_sender")(
		conversation,
		body,
	)


@frappe.whitelist()
@require_core_access()
def send_template(
	conversation: str,
	template_name: str,
	language_code: str = "en",
	components=None,
) -> dict:
	_assert_conversation_access(conversation)
	if isinstance(components, str):
		components = frappe.parse_json(components)
	if components is not None and not isinstance(components, list):
		frappe.throw("Template components must be a list", frappe.ValidationError)
	return _outbound_handler("whatsapp_core_outbound_template_sender")(
		conversation,
		(template_name or "").strip(),
		(language_code or "en").strip(),
		components or [],
	)


@frappe.whitelist()
@require_core_access()
def assign_conversation(
	conversation: str,
	team: str | None = None,
	user: str | None = None,
	status: str | None = None,
) -> dict:
	_assert_conversation_access(conversation)
	if (team is not None or user is not None) and not (
		set(frappe.get_roles()) & CORE_MANAGEMENT_ROLES
	):
		frappe.throw(
			"WhatsApp Core management access is required for assignment",
			frappe.PermissionError,
		)
	if team and not frappe.db.exists("WhatsApp Core Team", {"name": team, "enabled": 1}):
		frappe.throw("Enabled team not found", frappe.ValidationError)
	if user and team and not frappe.db.exists(
		"WhatsApp Core Team Member",
		{"parent": team, "user": user, "enabled": 1},
	):
		frappe.throw("Assigned user is not an enabled member of the team")
	if status and status not in {"Open", "Pending", "Resolved"}:
		frappe.throw("Invalid conversation status", frappe.ValidationError)
	values = {}
	if team is not None:
		values["assigned_team"] = team
	if user is not None:
		values["assigned_user"] = user
	if status:
		values["status"] = status
	if values:
		frappe.db.set_value("WhatsApp Core Conversation", conversation, values)
	return get_conversation(conversation)


@frappe.whitelist()
@require_core_access()
def list_teams() -> list[dict]:
	teams = frappe.get_all(
		"WhatsApp Core Team",
		fields=["name", "team_name", "description", "enabled"],
		order_by="team_name asc",
		limit_page_length=500,
	)
	for team in teams:
		team["members"] = frappe.get_all(
			"WhatsApp Core Team Member",
			filters={"parent": team.name},
			fields=["user", "team_role", "enabled"],
			order_by="idx asc",
		)
	return teams


@frappe.whitelist()
@require_core_access(manage=True)
def upsert_team(
	team_name: str,
	description: str = "",
	enabled: int | bool = 1,
	members=None,
) -> dict:
	if isinstance(members, str):
		members = frappe.parse_json(members)
	if members is None:
		members = []
	if not isinstance(members, list):
		frappe.throw("members must be a list", frappe.ValidationError)
	name = (team_name or "").strip()
	if not name:
		frappe.throw("Team name is required", frappe.ValidationError)
	doc = (
		frappe.get_doc("WhatsApp Core Team", name)
		if frappe.db.exists("WhatsApp Core Team", name)
		else frappe.new_doc("WhatsApp Core Team")
	)
	doc.team_name = name
	doc.description = description or ""
	doc.enabled = 1 if _as_bool(enabled) else 0
	doc.set("members", [])
	seen = set()
	for member in members:
		user = (member.get("user") or "").strip() if isinstance(member, dict) else ""
		if not user or user in seen:
			continue
		if not frappe.db.exists("User", user):
			frappe.throw(f"User not found: {user}", frappe.ValidationError)
		seen.add(user)
		doc.append("members", {
			"user": user,
			"team_role": member.get("team_role") or "Agent",
			"enabled": 1 if member.get("enabled", True) else 0,
		})
	doc.save(ignore_permissions=True)
	return doc.as_dict()


def _outbound_handler(hook_name: str):
	paths = frappe.get_hooks(hook_name)
	if len(paths) > 1:
		frappe.throw(
			f"At most one {hook_name} hook may be configured",
			frappe.ValidationError,
		)
	if paths:
		return frappe.get_attr(paths[0])
	from frappe_whatsapp_core.outbound import queue_template, queue_text

	defaults = {
		"whatsapp_core_outbound_text_sender": queue_text,
		"whatsapp_core_outbound_template_sender": queue_template,
	}
	handler = defaults.get(hook_name)
	if not handler:
		frappe.throw(
			f"No default outbound handler exists for {hook_name}",
			frappe.ValidationError,
		)
	return handler


def _assert_conversation_access(conversation: str) -> None:
	if not frappe.db.exists("WhatsApp Core Conversation", conversation):
		frappe.throw("Conversation not found", frappe.DoesNotExistError)
	roles = set(frappe.get_roles())
	if roles & (CORE_MANAGEMENT_ROLES | {"WhatsApp Core Analyst"}):
		return
	assigned_team, assigned_user = frappe.db.get_value(
		"WhatsApp Core Conversation",
		conversation,
		["assigned_team", "assigned_user"],
	)
	if assigned_user == frappe.session.user:
		return
	if not assigned_team:
		return
	if frappe.db.exists(
		"WhatsApp Core Team Member",
		{
			"parent": assigned_team,
			"user": frappe.session.user,
			"enabled": 1,
		},
	):
		return
	frappe.throw("You are not assigned to this conversation", frappe.PermissionError)


def _conversation_conditions(alias: str) -> tuple[list[str], dict]:
	conditions = ["1 = 1"]
	values = {}
	roles = set(frappe.get_roles())
	if roles & (CORE_MANAGEMENT_ROLES | {"WhatsApp Core Analyst"}):
		return conditions, values
	teams = frappe.get_all(
		"WhatsApp Core Team Member",
		filters={"user": frappe.session.user, "enabled": 1},
		pluck="parent",
	)
	values["current_user"] = frappe.session.user
	if teams:
		values["teams"] = tuple(teams)
		conditions.append(
			f"""(
				COALESCE({alias}.assigned_team, '') = ''
				OR {alias}.assigned_team IN %(teams)s
				OR {alias}.assigned_user = %(current_user)s
			)"""
		)
	else:
		conditions.append(
			f"""(
				COALESCE({alias}.assigned_team, '') = ''
				OR {alias}.assigned_user = %(current_user)s
			)"""
		)
	return conditions, values


def _json_dict(value) -> dict:
	if isinstance(value, dict):
		return value
	if not value:
		return {}
	try:
		parsed = json.loads(value)
		return parsed if isinstance(parsed, dict) else {}
	except (TypeError, ValueError):
		return {}


def _as_bool(value) -> bool:
	if isinstance(value, str):
		return value.strip().lower() in {"1", "true", "yes", "on"}
	return bool(value)
