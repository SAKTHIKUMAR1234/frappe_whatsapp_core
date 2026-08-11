"""Per-user conversation read cursors.

Provider delivery/read receipts and operator read state are different facts.
This service records only which authenticated operator opened which local
conversation, without changing the provider message status.
"""

from __future__ import annotations

import hashlib

import frappe
from frappe_whatsapp_core.permissions import assert_conversation_access, require_core_access


@frappe.whitelist()
@require_core_access()
def mark_conversation_read(conversation: str, message: str | None = None) -> dict:
	assert_conversation_access(conversation)
	frappe.has_permission(
		"WhatsApp Core Conversation",
		"read",
		conversation,
		throw=True,
	)
	if message:
		target = frappe.db.get_value(
			"WhatsApp Core Message",
			message,
			["conversation", "provider_timestamp", "creation"],
			as_dict=True,
		)
		if not target or target.conversation != conversation:
			frappe.throw("The read cursor message does not belong to this conversation")
	else:
		target = frappe.db.get_value(
			"WhatsApp Core Message",
			{"conversation": conversation, "message_type": ["!=", "reaction"]},
			["name", "conversation", "provider_timestamp", "creation"],
			order_by="provider_timestamp desc, creation desc",
			as_dict=True,
		)
		message = target.name if target else None

	user = frappe.session.user
	read_key = hashlib.sha256(f"{conversation}:{user}".encode()).hexdigest()
	doc = (
		frappe.get_doc("WhatsApp Core Conversation Read", read_key)
		if frappe.db.exists("WhatsApp Core Conversation Read", read_key)
		else frappe.new_doc("WhatsApp Core Conversation Read")
	)
	if not doc.is_new() and target and not _cursor_advances(doc, target):
		return _read_state(doc)
	doc.read_key = read_key
	doc.conversation = conversation
	doc.user = user
	doc.last_read_message = message
	doc.last_read_at = target.provider_timestamp if target else doc.last_read_at
	doc.last_read_creation = target.creation if target else doc.last_read_creation
	doc.save(ignore_permissions=True)
	read_state = _read_state(doc)
	frappe.publish_realtime(
		"whatsapp_core_conversation_read",
		read_state,
		after_commit=True,
	)
	provider_message = _latest_inbound_provider_message(conversation)
	if provider_message:
		frappe.enqueue(
			"frappe_whatsapp_core.conversation_reads.sync_provider_read",
			queue="short",
			enqueue_after_commit=True,
			channel=provider_message.channel,
			message_id=provider_message.provider_message_id,
		)
	return read_state


def _cursor_advances(doc, target) -> bool:
	if not doc.last_read_at:
		return True
	existing = (str(doc.last_read_at), str(doc.last_read_creation or ""))
	incoming = (str(target.provider_timestamp), str(target.creation or ""))
	return incoming > existing


def _read_state(doc) -> dict:
	return {
		"conversation": doc.conversation,
		"user": doc.user,
		"last_read_message": doc.last_read_message,
		"last_read_at": doc.last_read_at,
		"last_read_creation": doc.last_read_creation,
	}


@frappe.whitelist()
@require_core_access()
def show_typing(conversation: str) -> dict:
	assert_conversation_access(conversation)
	frappe.has_permission(
		"WhatsApp Core Conversation",
		"read",
		conversation,
		throw=True,
	)
	provider_message = _latest_inbound_provider_message(conversation)
	if not provider_message:
		return {"sent": False, "reason": "No inbound provider message"}
	from frappe_whatsapp_core.hub_client import mark_message_read

	mark_message_read(
		provider_message.channel,
		provider_message.provider_message_id,
		typing_indicator=True,
	)
	return {"sent": True, "message_id": provider_message.provider_message_id}


def sync_provider_read(channel: str, message_id: str) -> None:
	from frappe_whatsapp_core.hub_client import mark_message_read

	mark_message_read(channel, message_id)


def _latest_inbound_provider_message(conversation: str):
	rows = frappe.get_all(
		"WhatsApp Core Message",
		filters={
			"conversation": conversation,
			"direction": "Inbound",
			"provider_message_id": ["not like", "local:%"],
		},
		fields=["channel", "provider_message_id"],
		order_by="provider_timestamp desc, creation desc",
		limit_page_length=1,
	)
	return rows[0] if rows else None


@frappe.whitelist()
@require_core_access()
def conversation_readers(conversation: str) -> list[dict]:
	assert_conversation_access(conversation)
	frappe.has_permission(
		"WhatsApp Core Conversation",
		"read",
		conversation,
		throw=True,
	)
	rows = frappe.get_all(
		"WhatsApp Core Conversation Read",
		filters={"conversation": conversation},
		fields=["user", "last_read_message", "last_read_at", "last_read_creation"],
		order_by="last_read_at desc",
		limit_page_length=100,
	)
	users = {row.user for row in rows}
	profiles = {
		row.name: row
		for row in frappe.get_all(
			"User",
			filters={"name": ["in", list(users)]},
			fields=["name", "full_name", "user_image"],
			limit_page_length=len(users),
		)
	} if users else {}
	for row in rows:
		profile = profiles.get(row.user) or {}
		row.full_name = profile.get("full_name") or row.user
		row.user_image = profile.get("user_image") or ""
	return rows
