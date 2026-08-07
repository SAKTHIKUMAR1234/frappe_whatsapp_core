"""Business-neutral shared inbox projections used by Core and company UIs."""

from __future__ import annotations

import hashlib

import frappe

from frappe_whatsapp_core.conversation_reads import mark_conversation_read
from frappe_whatsapp_core.message_media import add_media_url
from frappe_whatsapp_core.outbound import outbound_state
from frappe_whatsapp_core.permissions import (
	CORE_MANAGEMENT_ROLES,
	assert_conversation_access,
	conversation_conditions,
	require_core_access,
)
from frappe_whatsapp_core.topics import list_topics


@frappe.whitelist()
@require_core_access()
def conversations(limit: int = 250) -> list[dict]:
	limit = max(1, min(int(limit), 500))
	conditions, values = conversation_conditions("conversation")
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
	latest_messages = _latest_messages(conversation_names)
	unread_counts = _unread_counts(conversation_names)

	result = []
	for row in rows:
		identity = identity_map.get(row.remote_identity) or {}
		binding = bindings.get(row.remote_identity)
		display_name = (
			binding.party_name
			if binding
			else identity.get("display_value")
			or identity.get("normalized_value")
			or row.name
		)
		result.append({
			**row,
			"display_name": display_name,
			"phone_number": identity.get("normalized_value") or "",
			"identity_status": identity.get("status") or "",
			"party_binding": binding,
			"latest_message": latest_messages.get(row.name),
			"unread_count": unread_counts.get(row.name, 0),
		})
	return result


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
	messages = frappe.get_all(
		"WhatsApp Core Message",
		filters={"conversation": doc.name},
		fields=[
			"name",
			"provider_message_id",
			"direction",
			"message_type",
			"body",
			"content",
			"provider_timestamp",
			"delivery_status",
			"failure",
			"creation",
		],
		order_by="provider_timestamp desc, creation desc",
		limit_page_length=message_limit + 1,
	)
	has_more_messages = len(messages) > message_limit
	messages = messages[:message_limit]
	oldest_loaded = messages[-1] if messages else None
	messages.reverse()
	bookmarks = set(frappe.get_all(
		"WhatsApp Core Message Bookmark",
		filters={"user": frappe.session.user, "message": ["in", [row.name for row in messages]]},
		pluck="message",
	)) if messages else set()
	for row in messages:
		row.bookmarked = row.name in bookmarks
		add_media_url(row)
	return {
		"conversation": doc.as_dict(),
		"identity": identity.as_dict(),
		"display_name": (
			bindings[0].party_name
			if bindings
			else identity.display_value
			or identity.normalized_value
		),
		"party_bindings": bindings,
		"messages": messages,
		"message_page": {
			"has_more": has_more_messages,
			"next_before": (
				oldest_loaded.provider_timestamp
				if has_more_messages and oldest_loaded
				else None
			),
			"next_before_creation": (
				oldest_loaded.creation
				if has_more_messages and oldest_loaded
				else None
			),
		},
		"topics": list_topics(doc.name),
		"readers": frappe.get_all(
			"WhatsApp Core Conversation Read",
			filters={"conversation": doc.name},
			fields=["user", "last_read_message", "last_read_at"],
			order_by="last_read_at desc",
			limit_page_length=100,
		),
		"outbound": outbound_state(doc.name),
		"templates": frappe.get_all(
			"WhatsApp Core Template",
			filters={"enabled": 1, "approval_status": "APPROVED"},
			fields=[
				"name",
				"template_name",
				"language_code",
				"body_text",
			],
			order_by="template_name asc",
			limit_page_length=500,
		),
	}


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
			ranked.provider_timestamp,
			ranked.delivery_status
		FROM (
			SELECT
				message.name,
				message.conversation,
				message.direction,
				message.message_type,
				message.body,
				message.provider_timestamp,
				message.delivery_status,
				ROW_NUMBER() OVER (
					PARTITION BY message.conversation
					ORDER BY message.provider_timestamp DESC, message.creation DESC
				) AS row_rank
			FROM `tabWhatsApp Core Message` AS message
			WHERE message.conversation IN %(conversation_names)s
		) AS ranked
		WHERE ranked.row_rank = 1
		""",
		{"conversation_names": tuple(conversation_names)},
		as_dict=True,
	)
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
