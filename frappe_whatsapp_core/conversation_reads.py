"""Per-user conversation read cursors.

Provider delivery/read receipts and operator read state are different facts.
This service records only which authenticated operator opened which local
conversation, without changing the provider message status.
"""

from __future__ import annotations

import hashlib

import frappe
from frappe.utils import now_datetime
from frappe_whatsapp_core.permissions import assert_conversation_access, require_core_access


MAX_READ_BATCH = 100


def attach_message_readers(messages: list) -> list:
	"""Attach exact persisted readers to one bounded message page."""
	readers = message_readers([_get(message, "name") for message in messages])
	for message in messages:
		_set(message, "read_by", readers.get(_get(message, "name"), []))
	return messages


def message_readers(message_names: list[str]) -> dict[str, list[dict]]:
	"""Load the exact `(message, user)` ledger for one bounded message page."""
	names = list(dict.fromkeys(str(name) for name in message_names or [] if name))
	if not names:
		return {}
	rows = frappe.db.sql(
		"""
		SELECT
			message_read.message,
			message_read.user,
			message_read.read_at,
			COALESCE(user.full_name, message_read.user) AS full_name,
			COALESCE(user.user_image, '') AS user_image
		FROM `tabWhatsApp Core Message Read` message_read
		LEFT JOIN `tabUser` user ON user.name = message_read.user
		WHERE message_read.message IN %(messages)s
		ORDER BY message_read.read_at ASC, message_read.user ASC
		""",
		{"messages": tuple(names)},
		as_dict=True,
	)
	result = {}
	for row in rows:
		result.setdefault(row.message, []).append({
			"user": row.user,
			"full_name": row.full_name or row.user,
			"user_image": row.user_image or "",
			"read_at": row.read_at,
		})
	return result


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
			["name", "conversation", "provider_timestamp", "creation"],
			as_dict=True,
		)
		if not target or target.conversation != conversation:
			frappe.throw("The read cursor message does not belong to this conversation")
	else:
		target = frappe.db.get_value(
			"WhatsApp Core Message",
			{"conversation": conversation, "message_type": ["!=", "reaction"]},
			["name", "conversation", "provider_timestamp", "creation"],
			order_by="provider_timestamp desc, creation desc, name desc",
			as_dict=True,
		)
		message = target.name if target else None
	if not target:
		return {
			"conversation": conversation,
			"user": frappe.session.user,
			"last_read_message": None,
			"last_read_at": None,
			"last_read_creation": None,
			"messages": [],
			"recorded": 0,
		}
	recorded = _record_message_reads(conversation, [target], frappe.session.user)
	return _advance_conversation_cursor(conversation, target, recorded)


def _advance_conversation_cursor(conversation: str, target, recorded: list[str]) -> dict:
	"""Advance the aggregate navigation cursor without stale-Document saves.

	Exact reads live in ``WhatsApp Core Message Read``.  This row is only the
	monotonic navigation/provider-receipt projection. Concurrent browser tabs can
	therefore upsert it atomically instead of racing Frappe's ``modified`` check.
	"""
	user = frappe.session.user
	read_key = hashlib.sha256(f"{conversation}:{user}".encode()).hexdigest()
	changed_at = now_datetime()
	position_advances = """(
		VALUES(last_read_at) > COALESCE(last_read_at, '1970-01-01 00:00:00')
		OR (
			VALUES(last_read_at) = last_read_at
			AND (
				VALUES(last_read_creation) > COALESCE(last_read_creation, '1970-01-01 00:00:00')
				OR (
					VALUES(last_read_creation) = last_read_creation
					AND VALUES(last_read_message) > COALESCE(last_read_message, '')
				)
			)
		)
	)"""
	frappe.db.sql(
		f"""
		INSERT INTO `tabWhatsApp Core Conversation Read` (
			name, creation, modified, modified_by, owner, docstatus, idx,
			read_key, conversation, user, last_read_message, last_read_at,
			last_read_creation
		) VALUES (
			%(name)s, %(changed_at)s, %(changed_at)s, %(user)s, %(user)s, 0, 0,
			%(name)s, %(conversation)s, %(user)s, %(message)s, %(read_at)s,
			%(read_creation)s
		)
		ON DUPLICATE KEY UPDATE
			modified = IF({position_advances}, VALUES(modified), modified),
			modified_by = IF({position_advances}, VALUES(modified_by), modified_by),
			last_read_message = IF(
				{position_advances}, VALUES(last_read_message), last_read_message
			),
			last_read_creation = IF(
				{position_advances}, VALUES(last_read_creation), last_read_creation
			),
			last_read_at = IF({position_advances}, VALUES(last_read_at), last_read_at)
		""",
		{
			"name": read_key,
			"changed_at": changed_at,
			"user": user,
			"conversation": conversation,
			"message": _get(target, "name"),
			"read_at": _get(target, "provider_timestamp") or _get(target, "creation"),
			"read_creation": _get(target, "creation"),
		},
	)
	cursor_changed = bool(frappe.db.sql("SELECT ROW_COUNT()", pluck=True)[0])
	row = frappe.db.get_value(
		"WhatsApp Core Conversation Read",
		read_key,
		[
			"conversation",
			"user",
			"last_read_message",
			"last_read_at",
			"last_read_creation",
		],
		as_dict=True,
	)
	read_state = _read_state(row, recorded)
	if cursor_changed or recorded:
		frappe.publish_realtime(
			"whatsapp_core_conversation_read",
			read_state,
			after_commit=True,
		)
	provider_message = (
		_latest_inbound_provider_message(conversation, at_or_before=target)
		if cursor_changed
		else None
	)
	if provider_message:
		frappe.enqueue(
			"frappe_whatsapp_core.conversation_reads.sync_provider_read",
			queue="short",
			enqueue_after_commit=True,
			channel=provider_message.channel,
			message_id=provider_message.provider_message_id,
		)
	return read_state


@frappe.whitelist()
@require_core_access()
def mark_messages_read(conversation: str, messages: list[str] | str) -> dict:
	"""Persist one exact read row per visible message using one batched request."""
	assert_conversation_access(conversation)
	frappe.has_permission(
		"WhatsApp Core Conversation",
		"read",
		conversation,
		throw=True,
	)
	if isinstance(messages, str):
		messages = frappe.parse_json(messages)
	if not isinstance(messages, list):
		frappe.throw("messages must be a list", frappe.ValidationError)
	names = [str(name).strip() for name in dict.fromkeys(messages) if str(name).strip()]
	if not names:
		return {"conversation": conversation, "processed": 0}
	if len(names) > MAX_READ_BATCH:
		frappe.throw(
			f"A read batch cannot exceed {MAX_READ_BATCH} messages",
			frappe.ValidationError,
		)
	rows = frappe.get_all(
		"WhatsApp Core Message",
		filters={
			"name": ["in", names],
			"conversation": conversation,
			"message_type": ["!=", "reaction"],
		},
		fields=["name", "conversation", "provider_timestamp", "creation"],
		limit_page_length=len(names),
	)
	if len(rows) != len(names):
		frappe.throw(
			"One or more read messages do not belong to this conversation",
			frappe.ValidationError,
		)
	target = max(
		rows,
		key=lambda row: (
			str(row.provider_timestamp or ""),
			str(row.creation or ""),
			str(row.name or ""),
		),
	)
	recorded = _record_message_reads(conversation, rows, frappe.session.user)
	read_state = _advance_conversation_cursor(conversation, target, recorded)
	read_state["processed"] = len(rows)
	read_state["recorded"] = len(recorded)
	return read_state


def _record_message_reads(conversation: str, messages: list, user: str) -> list[str]:
	"""Insert missing ledger rows once; concurrent tabs are deduplicated by key."""
	if not messages:
		return []
	contact = frappe.db.get_value(
		"WhatsApp Core Conversation",
		conversation,
		"remote_identity",
	)
	if not contact:
		frappe.throw("Conversation contact was not found", frappe.DoesNotExistError)
	keyed = {
		hashlib.sha256(f"{_get(message, 'name')}:{user}".encode()).hexdigest(): _get(message, "name")
		for message in messages
	}
	existing = set(frappe.get_all(
		"WhatsApp Core Message Read",
		filters={"name": ["in", list(keyed)]},
		pluck="name",
		limit_page_length=len(keyed),
	))
	read_at = now_datetime()
	new_rows = sorted(
		[
		(read_key, message_name)
		for read_key, message_name in keyed.items()
		if read_key not in existing
		],
		key=lambda row: row[0],
	)
	if not new_rows:
		return []
	fields = [
		"name", "creation", "modified", "modified_by", "owner", "docstatus", "idx",
		"read_key", "message", "conversation", "contact", "user", "read_at",
	]
	frappe.db.bulk_insert(
		"WhatsApp Core Message Read",
		fields=fields,
		values=[
			(
				read_key, read_at, read_at, user, user, 0, 0, read_key,
				message_name, conversation, contact, user, read_at,
			)
			for read_key, message_name in new_rows
		],
		ignore_duplicates=True,
	)
	return [message_name for _read_key, message_name in new_rows]


def _cursor_advances(doc, target) -> bool:
	if not doc.last_read_at:
		return True
	existing = (str(doc.last_read_at), str(doc.last_read_creation or ""))
	incoming = (str(target.provider_timestamp), str(target.creation or ""))
	return incoming > existing


def _get(value, key):
	return value.get(key) if isinstance(value, dict) else getattr(value, key, None)


def _set(value, key, item) -> None:
	if isinstance(value, dict):
		value[key] = item
	else:
		setattr(value, key, item)


def _read_state(doc, messages: list[str] | None = None) -> dict:
	return {
		"conversation": doc.conversation,
		"user": doc.user,
		"last_read_message": doc.last_read_message,
		"last_read_at": doc.last_read_at,
		"last_read_creation": doc.last_read_creation,
		"messages": list(messages or []),
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


def _latest_inbound_provider_message(conversation: str, at_or_before=None):
	"""Return the latest real inbound message inside the operator's read window."""
	position_filter = ""
	values = {"conversation": conversation}
	if at_or_before:
		position_filter = """
			AND (
				provider_timestamp < %(read_at)s
				OR (
					provider_timestamp = %(read_at)s
					AND (
						creation < %(read_creation)s
						OR (
							creation = %(read_creation)s
							AND name <= %(read_message)s
						)
					)
				)
			)
		"""
		values.update({
			"read_at": _get(at_or_before, "provider_timestamp") or _get(at_or_before, "creation"),
			"read_creation": _get(at_or_before, "creation"),
			"read_message": _get(at_or_before, "name"),
		})
	rows = frappe.db.sql(
		f"""
		SELECT channel, provider_message_id
		FROM `tabWhatsApp Core Message`
		WHERE conversation = %(conversation)s
			AND direction = 'Inbound'
			AND message_type != 'reaction'
			AND provider_message_id NOT LIKE 'local:%%'
			{position_filter}
		ORDER BY provider_timestamp DESC, creation DESC, name DESC
		LIMIT 1
		""",
		values,
		as_dict=True,
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
