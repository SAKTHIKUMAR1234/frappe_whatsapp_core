"""Business-neutral shared inbox projections used by Core and company UIs."""

from __future__ import annotations

import hashlib
import json

import frappe

from frappe_whatsapp_core.contact_presentation import present_identity_names
from frappe_whatsapp_core.conversation_reads import conversation_readers, mark_conversation_read
from frappe_whatsapp_core.materializer import inbound_message_body
from frappe_whatsapp_core.message_media import add_media_url
from frappe_whatsapp_core.message_quotes import attach_quoted_messages
from frappe_whatsapp_core.message_reactions import attach_message_reactions
from frappe_whatsapp_core.outbound import outbound_state
from frappe_whatsapp_core.permissions import (
	CORE_MANAGEMENT_ROLES,
	assert_conversation_access,
	conversation_conditions,
	require_core_access,
)
from frappe_whatsapp_core.topics import list_topics
from frappe_whatsapp_core.ai_summaries import attach_message_insights, get_identity_summary


@frappe.whitelist()
@require_core_access()
def conversations(limit: int = 250, category: str | None = None) -> list[dict]:
	limit = max(1, min(int(limit), 500))
	conditions, values = conversation_conditions("conversation")
	category = str(category or "").strip()
	if category:
		conditions.append(
			"""EXISTS (
				SELECT 1
				FROM `tabWhatsApp Core Message Category Assignment` AS category_assignment
				WHERE category_assignment.conversation = conversation.name
					AND category_assignment.category = %(category)s
			)"""
		)
		values["category"] = category
	values["limit"] = limit
	rows = frappe.db.sql(
		f"""
		SELECT
			conversation.name,
			conversation.conversation_key,
			conversation.channel,
			conversation.remote_identity,
			conversation.status,
			conversation.workspace_key,
			conversation.assigned_team,
			conversation.assigned_user,
			conversation.last_inbound_at,
			conversation.last_message_at
		FROM `tabWhatsApp Core Conversation` AS conversation
		WHERE {" AND ".join(conditions)}
		ORDER BY conversation.last_message_at DESC
		LIMIT %(limit)s
		""",
		values,
		as_dict=True,
	)
	if not rows:
		return []
	conversation_names = [row.name for row in rows]
	identity_names = list({row.remote_identity for row in rows})
	identity_map = {
		row.name: row
		for row in frappe.get_all(
			"WhatsApp Core Identity",
			filters={"name": ["in", identity_names]},
			fields=[
				"name",
				"normalized_value",
				"display_value",
				"status",
			],
			limit_page_length=len(identity_names),
		)
	}
	bindings = _primary_bindings(identity_names)
	teams = _team_presentations({row.assigned_team for row in rows if row.assigned_team})
	contact_teams = _identity_team_presentations(identity_names)
	presentations = present_identity_names(identity_names, context={"surface": "inbox_list"})
	latest_messages = _latest_messages(conversation_names)
	unread_counts = _unread_counts(conversation_names)

	result = []
	for row in rows:
		identity = identity_map.get(row.remote_identity) or {}
		presentation = presentations.get(row.remote_identity) or {}
		display_name = presentation.get("display_name") or row.name
		result.append({
			**row,
			"assigned_team_details": teams.get(row.assigned_team),
			"contact_teams": contact_teams.get(row.remote_identity, []),
			"display_name": display_name,
			"phone_number": identity.get("normalized_value") or "",
			"identity_status": identity.get("status") or "",
			"contact_presentation": presentation,
			"party_binding": bindings.get(row.remote_identity),
			"latest_message": latest_messages.get(row.name),
			"unread_count": unread_counts.get(row.name, 0),
		})
	return result


@frappe.whitelist()
@require_core_access()
def category_catalog() -> list[dict]:
	"""Return enabled indexed message categories for inbox filtering."""
	return frappe.get_all(
		"WhatsApp Core Message Category",
		filters={"enabled": 1},
		fields=["name", "category_name", "description", "source"],
		order_by="category_name asc",
		limit_page_length=500,
	)


@frappe.whitelist()
@require_core_access()
def conversation(name: str, message_limit: int = 500) -> dict:
	message_limit = max(1, min(int(message_limit), 1000))
	assert_conversation_access(name)
	doc = frappe.get_doc("WhatsApp Core Conversation", name)
	frappe.has_permission(
		"WhatsApp Core Conversation",
		"read",
		doc=doc,
		throw=True,
	)
	identity = frappe.get_doc(
		"WhatsApp Core Identity",
		doc.remote_identity,
	)
	assigned_team = _team_presentations({doc.assigned_team}).get(doc.assigned_team)
	contact_teams = _identity_team_presentations([identity.name]).get(identity.name, [])
	presentation = present_identity_names(
		[identity.name], context={"surface": "inbox_conversation", "conversation": doc.name}
	).get(identity.name, {})
	bindings = frappe.get_all(
		"WhatsApp Core Party Binding",
		filters={
			"identity": identity.name,
			"status": "Verified",
		},
		fields=[
			"name",
			"workspace_key",
			"party_doctype",
			"party_name",
			"party_role",
			"is_primary",
			"source",
			"attributes",
		],
		order_by="is_primary desc, modified desc",
		limit_page_length=100,
	)
	readers = conversation_readers(doc.name)
	current_read = next((row for row in readers if row.user == frappe.session.user), None)
	messages, message_page, resume_message = _conversation_message_rows(
		doc.name,
		message_limit,
		current_read,
	)
	_enrich_message_senders(messages)
	attach_message_reactions(messages, doc.name)
	bookmarks = set(frappe.get_all(
		"WhatsApp Core Message Bookmark",
		filters={"user": frappe.session.user, "message": ["in", [row.name for row in messages]]},
		pluck="message",
	)) if messages else set()
	for row in messages:
		row.bookmarked = row.name in bookmarks
		add_media_url(row)
	attach_quoted_messages(messages, doc.name)
	attach_message_insights(messages)
	return {
		"conversation": doc.as_dict(),
		"assigned_team_details": assigned_team,
		"contact_teams": contact_teams,
		"identity": identity.as_dict(),
		"display_name": presentation.get("display_name") or identity.normalized_value,
		"contact_presentation": presentation,
		"party_bindings": bindings,
		"messages": messages,
		"message_page": message_page,
		"resume_message": resume_message,
		"current_user_read": current_read,
		"topics": list_topics(doc.name),
		"contact_summary": get_identity_summary(identity.name),
		"readers": readers,
		"outbound": outbound_state(doc.name),
		"templates": frappe.get_all(
			"WhatsApp Core Template",
			filters={"enabled": 1, "approval_status": "APPROVED"},
			fields=[
				"name",
				"template_name",
				"language_code",
				"approval_status",
				"enabled",
				"header_type",
				"header_content",
				"body_text",
				"footer_text",
				"components",
			],
			order_by="template_name asc",
			limit_page_length=500,
		),
	}


def _conversation_message_rows(conversation: str, limit: int, current_read) -> tuple[list, dict, str | None]:
	"""Load from an operator's durable cursor, with a small preceding context window."""
	fields = """
		name, provider_message_id, direction, message_type, body, content,
		provider_timestamp, delivery_status, failure, owner, creation
	"""
	resume_message = current_read.last_read_message if current_read else None
	anchor = None
	if resume_message:
		anchor = frappe.db.get_value(
			"WhatsApp Core Message",
			{"name": resume_message, "conversation": conversation},
			["provider_timestamp", "creation"],
			as_dict=True,
		)
	if anchor:
		values = {
			"conversation": conversation,
			"at": anchor.provider_timestamp,
			"creation": anchor.creation,
			"limit": limit + 1,
		}
		newer = frappe.db.sql(
			f"""
			SELECT {fields}
			FROM `tabWhatsApp Core Message`
			WHERE conversation = %(conversation)s AND message_type != 'reaction'
				AND (
					provider_timestamp > %(at)s
					OR (provider_timestamp = %(at)s AND creation >= %(creation)s)
				)
			ORDER BY provider_timestamp ASC, creation ASC
			LIMIT %(limit)s
			""",
			values,
			as_dict=True,
		)
		has_more_newer = len(newer) > limit
		newer = newer[:limit]
		older = frappe.db.sql(
			f"""
			SELECT {fields}
			FROM `tabWhatsApp Core Message`
			WHERE conversation = %(conversation)s AND message_type != 'reaction'
				AND (
					provider_timestamp < %(at)s
					OR (provider_timestamp = %(at)s AND creation < %(creation)s)
				)
			ORDER BY provider_timestamp DESC, creation DESC
			LIMIT 21
			""",
			values,
			as_dict=True,
		)
		has_more_older = len(older) > 20
		older = list(reversed(older[:20]))
		messages = older + newer
		oldest = messages[0] if messages else None
		return messages, {
			"has_more": has_more_older,
			"has_more_newer": has_more_newer,
			"next_before": oldest.provider_timestamp if has_more_older and oldest else None,
			"next_before_creation": oldest.creation if has_more_older and oldest else None,
		}, resume_message

	messages = frappe.db.sql(
		f"""
		SELECT {fields}
		FROM `tabWhatsApp Core Message`
		WHERE conversation = %(conversation)s AND message_type != 'reaction'
		ORDER BY provider_timestamp DESC, creation DESC
		LIMIT %(limit)s
		""",
		{"conversation": conversation, "limit": limit + 1},
		as_dict=True,
	)
	has_more = len(messages) > limit
	messages = messages[:limit]
	oldest = messages[-1] if messages else None
	messages.reverse()
	return messages, {
		"has_more": has_more,
		"has_more_newer": False,
		"next_before": oldest.provider_timestamp if has_more and oldest else None,
		"next_before_creation": oldest.creation if has_more and oldest else None,
	}, None


def _team_presentations(team_names) -> dict[str, dict]:
	names = [name for name in set(team_names or []) if name]
	if not names:
		return {}
	return {
		row.name: row
		for row in frappe.get_all(
			"WhatsApp Core Team",
			filters={"name": ["in", names]},
			fields=["name", "team_name", "icon", "enabled"],
			limit_page_length=len(names),
		)
	}


def _identity_team_presentations(identity_names) -> dict[str, list[dict]]:
	names = [name for name in set(identity_names or []) if name]
	result = {name: [] for name in names}
	if not names:
		return result
	rows = frappe.db.sql(
		"""
		SELECT
			team_contact.identity,
			team.name,
			team.team_name,
			team.icon,
			team.enabled
		FROM `tabWhatsApp Core Team Contact` AS team_contact
		JOIN `tabWhatsApp Core Team` AS team
			ON team.name = team_contact.parent
		WHERE team_contact.parenttype = 'WhatsApp Core Team'
			AND team_contact.parentfield = 'contacts'
			AND team_contact.enabled = 1
			AND team_contact.identity IN %(identities)s
		ORDER BY team.team_name ASC
		""",
		{"identities": tuple(names)},
		as_dict=True,
	)
	for row in rows:
		result.setdefault(row.identity, []).append({
			"name": row.name,
			"team_name": row.team_name,
			"icon": row.icon,
			"enabled": row.enabled,
		})
	return result


def _enrich_message_senders(messages) -> None:
	owners = {
		row.get("owner")
		for row in messages
		if row.get("direction") == "Outbound" and row.get("owner")
	}
	if not owners:
		return
	names = {
		row.name: row.full_name or row.name
		for row in frappe.get_all(
			"User",
			filters={"name": ["in", list(owners)]},
			fields=["name", "full_name"],
			limit_page_length=len(owners),
		)
	}
	for row in messages:
		row.sender_name = (
			names.get(row.get("owner"), row.get("owner"))
			if row.get("direction") == "Outbound"
			else ""
		)


@frappe.whitelist()
@require_core_access()
def read_conversation(name: str, message: str | None = None) -> dict:
	assert_conversation_access(name)
	return mark_conversation_read(name, message)


@frappe.whitelist()
@require_core_access()
def toggle_message_bookmark(message: str) -> dict:
	conversation_name = frappe.db.get_value("WhatsApp Core Message", message, "conversation")
	if not conversation_name:
		frappe.throw("Message not found", frappe.DoesNotExistError)
	assert_conversation_access(conversation_name)
	frappe.has_permission("WhatsApp Core Conversation", "read", conversation_name, throw=True)
	key = hashlib.sha256(f"{message}:{frappe.session.user}".encode()).hexdigest()
	if frappe.db.exists("WhatsApp Core Message Bookmark", key):
		frappe.delete_doc("WhatsApp Core Message Bookmark", key, ignore_permissions=True)
		return {"message": message, "bookmarked": False}
	frappe.get_doc({
		"doctype": "WhatsApp Core Message Bookmark",
		"bookmark_key": key,
		"message": message,
		"conversation": conversation_name,
		"user": frappe.session.user,
	}).insert(ignore_permissions=True)
	return {"message": message, "bookmarked": True}


@frappe.whitelist()
@require_core_access()
def update_conversation(
	name: str,
	status: str | None = None,
	assigned_user: str | None = None,
) -> dict:
	assert_conversation_access(name)
	doc = frappe.get_doc("WhatsApp Core Conversation", name)
	frappe.has_permission(
		"WhatsApp Core Conversation",
		"write",
		doc=doc,
		throw=True,
	)
	if status is not None:
		if status not in {"Open", "Pending", "Resolved"}:
			frappe.throw("Unsupported conversation status")
		doc.status = status
	if assigned_user is not None:
		if not (set(frappe.get_roles()) & CORE_MANAGEMENT_ROLES):
			frappe.throw(
				"WhatsApp Core management access is required for assignment",
				frappe.PermissionError,
			)
		if assigned_user and not frappe.db.exists(
			"User",
			{"name": assigned_user, "enabled": 1},
		):
			frappe.throw("Assigned user is not active")
		doc.assigned_user = assigned_user or None
	doc.save()
	return doc.as_dict()


def _primary_bindings(identity_names: list[str]) -> dict:
	rows = frappe.get_all(
		"WhatsApp Core Party Binding",
		filters={
			"identity": ["in", identity_names],
			"status": "Verified",
		},
		fields=[
			"name",
			"identity",
			"workspace_key",
			"party_doctype",
			"party_name",
			"party_role",
			"is_primary",
		],
		order_by="is_primary desc, modified desc",
		limit_page_length=max(100, len(identity_names) * 5),
	)
	result = {}
	for row in rows:
		result.setdefault(row.identity, row)
	return result


def _latest_messages(conversation_names: list[str]) -> dict:
	rows = frappe.db.sql(
		"""
		SELECT
			ranked.name,
			ranked.conversation,
			ranked.direction,
			ranked.message_type,
			ranked.body,
			ranked.content,
			ranked.provider_timestamp,
			ranked.delivery_status
		FROM (
			SELECT
				message.name,
				message.conversation,
				message.direction,
				message.message_type,
				message.body,
				message.content,
				message.provider_timestamp,
				message.delivery_status,
				ROW_NUMBER() OVER (
					PARTITION BY message.conversation
					ORDER BY message.provider_timestamp DESC, message.creation DESC
				) AS row_rank
			FROM `tabWhatsApp Core Message` AS message
			WHERE message.conversation IN %(conversation_names)s
				AND message.message_type != 'reaction'
		) AS ranked
		WHERE ranked.row_rank = 1
		""",
		{"conversation_names": tuple(conversation_names)},
		as_dict=True,
	)
	for row in rows:
		if row.message_type == "interactive":
			try:
				content = json.loads(row.content or "{}")
			except (TypeError, ValueError):
				content = {}
			interactive = content.get("interactive") if isinstance(content, dict) else None
			if isinstance(interactive, dict) and interactive.get("nfm_reply"):
				row.body = inbound_message_body("interactive", interactive)
		row.pop("content", None)
	return {row.conversation: row for row in rows}


def _unread_counts(conversation_names: list[str]) -> dict:
	rows = frappe.db.sql(
		"""
		SELECT
			message.conversation,
			COUNT(*) AS unread_count
		FROM `tabWhatsApp Core Message` AS message
		LEFT JOIN `tabWhatsApp Core Conversation Read` AS read_cursor
			ON read_cursor.conversation = message.conversation
			AND read_cursor.user = %(user)s
		WHERE message.conversation IN %(conversation_names)s
			AND message.direction = 'Inbound'
			AND (
				read_cursor.last_read_at IS NULL
				OR message.provider_timestamp > read_cursor.last_read_at
				OR (
					message.provider_timestamp = read_cursor.last_read_at
					AND message.creation > COALESCE(read_cursor.last_read_creation, '1970-01-01')
				)
			)
		GROUP BY message.conversation
		""",
		{
			"conversation_names": tuple(conversation_names),
			"user": frappe.session.user,
		},
		as_dict=True,
	)
	return {
		row.conversation: int(row.unread_count or 0)
		for row in rows
	}
