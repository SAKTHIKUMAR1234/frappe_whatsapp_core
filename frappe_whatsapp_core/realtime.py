"""Permission-scoped realtime projections for the Core web application."""

from __future__ import annotations

from collections import defaultdict

import frappe


MESSAGE_CHANGE_KINDS = {"message", "status", "edit", "revoke"}


def publish_invalidation(event: str, *, after_commit: bool = True) -> None:
	"""Wake clients without placing protected row data on the site-wide room.

	This remains the compatibility path for configuration/catalog screens. Inbox
	traffic must use the permission-scoped publishers below.
	"""
	frappe.publish_realtime(
		str(event),
		{"changed": True},
		after_commit=after_commit,
	)


def conversation_recipients(conversation_names: list[str]) -> dict[str, set[str]]:
	"""Return users whose existing Core scope permits each conversation.

	Frappe already joins every authenticated Socket.IO client to its ``user`` room.
	Publishing to those rooms is tighter than a client-selected team room and avoids
	putting protected message rows on the site-wide room. The SQL below mirrors the
	canonical manager, contact-team, assignment-team and unassigned-chat rules in
	``permissions.py`` in one bounded query for the whole committed event batch.
	"""
	from frappe_whatsapp_core.permissions import (
		CORE_ACCESS_ROLES,
		CORE_MANAGEMENT_ROLES,
	)

	names = _unique_strings(conversation_names)
	if not names:
		return {}
	rows = frappe.db.sql(
		"""
		SELECT DISTINCT
			conversation.name AS conversation,
			candidate.name AS user
		FROM `tabWhatsApp Core Conversation` AS conversation
		JOIN `tabUser` AS candidate
			ON candidate.enabled = 1
			AND candidate.user_type = 'System User'
		WHERE conversation.name IN %(conversation_names)s
			AND (
				candidate.name = 'Administrator'
				OR EXISTS (
					SELECT 1
					FROM `tabHas Role` AS access_role
					WHERE access_role.parent = candidate.name
						AND access_role.parenttype = 'User'
						AND access_role.parentfield = 'roles'
						AND access_role.role IN %(access_roles)s
				)
			)
			AND (
				candidate.name = 'Administrator'
				OR EXISTS (
					SELECT 1
					FROM `tabHas Role` AS manager_role
					WHERE manager_role.parent = candidate.name
						AND manager_role.parenttype = 'User'
						AND manager_role.parentfield = 'roles'
						AND manager_role.role IN %(management_roles)s
				)
				OR (
					(
						(
							EXISTS (
								SELECT 1
								FROM `tabWhatsApp Core Team Member` AS user_team
								JOIN `tabWhatsApp Core Team` AS enabled_user_team
									ON enabled_user_team.name = user_team.parent
									AND enabled_user_team.enabled = 1
								WHERE user_team.parenttype = 'WhatsApp Core Team'
									AND user_team.parentfield = 'members'
									AND user_team.enabled = 1
									AND user_team.user = candidate.name
							)
							AND EXISTS (
								SELECT 1
								FROM `tabWhatsApp Core Team Contact` AS visible_contact
								JOIN `tabWhatsApp Core Team` AS visible_team
									ON visible_team.name = visible_contact.parent
									AND visible_team.enabled = 1
								JOIN `tabWhatsApp Core Team Member` AS visible_member
									ON visible_member.parent = visible_contact.parent
									AND visible_member.parenttype = 'WhatsApp Core Team'
									AND visible_member.parentfield = 'members'
									AND visible_member.enabled = 1
									AND visible_member.user = candidate.name
								WHERE visible_contact.parenttype = 'WhatsApp Core Team'
									AND visible_contact.parentfield = 'contacts'
									AND visible_contact.enabled = 1
									AND visible_contact.identity = conversation.remote_identity
							)
						)
						OR (
							NOT EXISTS (
								SELECT 1
								FROM `tabWhatsApp Core Team Member` AS user_team
								JOIN `tabWhatsApp Core Team` AS enabled_user_team
									ON enabled_user_team.name = user_team.parent
									AND enabled_user_team.enabled = 1
								WHERE user_team.parenttype = 'WhatsApp Core Team'
									AND user_team.parentfield = 'members'
									AND user_team.enabled = 1
									AND user_team.user = candidate.name
							)
							AND NOT EXISTS (
								SELECT 1
								FROM `tabWhatsApp Core Team Contact` AS scoped_contact
								JOIN `tabWhatsApp Core Team` AS scoped_team
									ON scoped_team.name = scoped_contact.parent
									AND scoped_team.enabled = 1
								WHERE scoped_contact.parenttype = 'WhatsApp Core Team'
									AND scoped_contact.parentfield = 'contacts'
									AND scoped_contact.enabled = 1
									AND scoped_contact.identity = conversation.remote_identity
							)
						)
					)
					AND (
						(
							COALESCE(conversation.assigned_team, '') = ''
							AND COALESCE(conversation.assigned_user, '') = ''
						)
						OR conversation.assigned_user = candidate.name
						OR EXISTS (
							SELECT 1
							FROM `tabWhatsApp Core Team Member` AS assigned_member
							WHERE assigned_member.parent = conversation.assigned_team
								AND assigned_member.parenttype = 'WhatsApp Core Team'
								AND assigned_member.parentfield = 'members'
								AND assigned_member.enabled = 1
								AND assigned_member.user = candidate.name
						)
					)
				)
			)
		""",
		{
			"conversation_names": tuple(names),
			"access_roles": tuple(sorted(CORE_ACCESS_ROLES)),
			"management_roles": tuple(sorted(CORE_MANAGEMENT_ROLES)),
		},
		as_dict=True,
	)
	result = {name: set() for name in names}
	for row in rows:
		result.setdefault(row.conversation, set()).add(row.user)
	return result


def publish_message_changes(changes, *, after_commit: bool = True) -> int:
	"""Publish complete message/list deltas to authorized per-user rooms.

	A created message carries the same enriched projection as the paged API. Status,
	edit and revoke changes carry only the fields needed to patch a row already in
	the browser. Every payload also includes the authoritative conversation list row
	for that recipient, including their own unread count.
	"""
	normalized = _normalized_changes(changes)
	if not normalized:
		return 0
	message_rows = _message_projections(
		[change["name"] for change in normalized],
		full_names=[
			change["name"] for change in normalized if change["kind"] != "status"
		],
	)
	normalized = [change for change in normalized if change["name"] in message_rows]
	if not normalized:
		return 0

	conversation_names = _unique_strings(
		message_rows[change["name"]].get("conversation") for change in normalized
	)
	recipients = conversation_recipients(conversation_names)
	if not any(recipients.values()):
		return 0

	from frappe_whatsapp_core.inbox import _unread_counts, conversation_rows_for_realtime

	created_conversations = set(
		message_rows[change["name"]].get("conversation")
		for change in normalized
		if change["status"] == "created"
	)
	base_rows = {}
	if created_conversations:
		base_rows = {
			row.get("name"): dict(row)
			for row in conversation_rows_for_realtime(
				list(created_conversations),
				include_unread=False,
			)
			if row.get("name")
		}
	changes_by_conversation = defaultdict(list)
	for change in normalized:
		message = message_rows[change["name"]]
		conversation = message.get("conversation")
		changes_by_conversation[conversation].append({
			"kind": change["kind"],
			"status": change["status"],
			"message": _change_message_projection(change, message),
		})

	conversations_by_user = defaultdict(list)
	for conversation, users in recipients.items():
		for user in users:
			conversations_by_user[user].append(conversation)

	published = 0
	for user, visible_conversations in conversations_by_user.items():
		visible_created = [
			conversation
			for conversation in visible_conversations
			if conversation in created_conversations
		]
		unread = _unread_counts(visible_created, user=user) if visible_created else {}
		conversation_rows = []
		message_changes = []
		kinds = []
		for conversation in visible_conversations:
			if conversation in base_rows:
				conversation_rows.append({
					**base_rows[conversation],
					"unread_count": unread.get(conversation, 0),
				})
			for change in changes_by_conversation.get(conversation, []):
				message_changes.append(change)
				kinds.append(change["kind"])
		if not message_changes:
			continue
		frappe.publish_realtime(
			"whatsapp_core_batch_committed",
			{
				"message_changes": message_changes,
				"conversation_rows": conversation_rows,
				"conversations": visible_conversations,
				"kinds": list(dict.fromkeys(kinds)),
			},
			user=user,
			after_commit=after_commit,
		)
		published += 1
	return published


def publish_conversation_read(read_state: dict, *, after_commit: bool = True) -> int:
	"""Publish one exact operator-read delta only to users who can see the chat."""
	conversation = str(read_state.get("conversation") or "").strip()
	reader = str(read_state.get("user") or "").strip()
	if not conversation or not reader:
		return 0
	recipients = conversation_recipients([conversation]).get(conversation, set())
	if not recipients:
		return 0

	from frappe_whatsapp_core.conversation_reads import _reader_display_name
	from frappe_whatsapp_core.inbox import _unread_counts

	profile = frappe.db.get_value(
		"User",
		reader,
		["first_name", "last_name", "full_name", "username", "user_image"],
		as_dict=True,
	) or {}
	display_name = _reader_display_name(profile, reader)
	payload = {
		**read_state,
		"display_name": display_name,
		"full_name": display_name,
		"user_image": profile.get("user_image") or "",
	}
	reader_unread = (
		_unread_counts([conversation], user=reader).get(conversation, 0)
		if reader in recipients
		else None
	)
	published = 0
	for user in recipients:
		user_payload = dict(payload)
		if user == reader and reader_unread is not None:
			user_payload["conversation_row"] = {
				"name": conversation,
				"unread_count": reader_unread,
			}
		frappe.publish_realtime(
			"whatsapp_core_conversation_read",
			user_payload,
			user=user,
			after_commit=after_commit,
		)
		published += 1
	return published


def publish_call_changes(call_names, *, after_commit: bool = True) -> int:
	"""Send complete call lifecycle deltas only to users in the call's inbox scope."""
	names = _unique_strings(call_names)
	if not names:
		return 0
	rows = frappe.get_all(
		"WhatsApp Core Call",
		filters={"name": ["in", names]},
		fields=[
			"name", "call_id", "channel", "conversation", "remote_identity",
			"direction", "status", "remote_number", "remote_user_id",
			"remote_username", "handled_by", "started_at", "ended_at", "session",
			"recording_media_id", "recording_mime_type", "recording_url",
			"mixed_recording_url", "mixed_recording_mime_type",
			"mixed_recording_sha256",
			"transcript_media_id", "transcript_mime_type", "transcript_url",
			"creation", "modified",
		],
		limit_page_length=len(names),
	)
	from frappe_whatsapp_core.contact_presentation import present_identity_names

	presentations = present_identity_names(
		[row.remote_identity for row in rows if row.remote_identity],
		context={"surface": "calling_realtime"},
	)
	handler_users = {row.handled_by for row in rows if row.handled_by}
	handler_names = {}
	if handler_users:
		handler_names = {
			profile.name: profile.full_name or profile.first_name or profile.name
			for profile in frappe.get_all(
				"User",
				filters={"name": ["in", list(handler_users)]},
				fields=["name", "full_name", "first_name"],
				limit_page_length=len(handler_users),
			)
		}
	recipients = conversation_recipients(
		[row.conversation for row in rows if row.conversation]
	)
	published = 0
	for row in rows:
		presentation = presentations.get(row.remote_identity) or {}
		row["display_name"] = (
			presentation.get("display_name")
			or row.remote_username
			or row.remote_number
			or "WhatsApp contact"
		)
		row["presentation"] = presentation
		row["timeline_at"] = row.started_at or row.ended_at or row.creation or row.modified
		row["provider_recording_url"] = row.recording_url
		row["recording_url"] = row.mixed_recording_url or row.recording_url
		row["handled_by_name"] = handler_names.get(
			row.handled_by, row.handled_by or ""
		)
		for user in recipients.get(row.conversation, set()):
			frappe.publish_realtime(
				"whatsapp_core_call",
				{"call": dict(row)},
				user=user,
				after_commit=after_commit,
			)
			published += 1
	return published


def publish_batch_notice(kinds, *, after_commit: bool = True) -> None:
	"""Publish a payload-free, typed notice for non-inbox batch projections."""
	safe_kinds = [kind for kind in _unique_strings(kinds) if kind not in MESSAGE_CHANGE_KINDS]
	if not safe_kinds:
		return
	frappe.publish_realtime(
		"whatsapp_core_batch_committed",
		{
			"message_changes": [],
			"conversation_rows": [],
			"conversations": [],
			"kinds": safe_kinds,
		},
		after_commit=after_commit,
	)


def _normalized_changes(changes) -> list[dict]:
	result = {}
	for value in changes or []:
		if not isinstance(value, dict):
			continue
		name = str(value.get("name") or "").strip()
		kind = str(value.get("kind") or "").strip()
		status = str(value.get("status") or "").strip()
		if not name or kind not in MESSAGE_CHANGE_KINDS or status not in {"created", "updated"}:
			continue
		previous = result.get(name)
		if not previous:
			result[name] = {"name": name, "kind": kind, "status": status}
			continue
		if status == "created":
			previous["status"] = "created"
		if kind == "message" or previous["kind"] == "status":
			previous["kind"] = kind
	return list(result.values())


def _message_projections(
	message_names: list[str],
	*,
	full_names: list[str] | None = None,
) -> dict[str, dict]:
	names = _unique_strings(message_names)
	if not names:
		return {}
	rows = frappe.db.sql(
		"""
		SELECT
			name, conversation, message_key, provider_message_id, direction,
			message_type, body, content, provider_timestamp, delivery_status,
			failure, owner, creation, 0 AS bookmarked
		FROM `tabWhatsApp Core Message`
		WHERE name IN %(message_names)s
		""",
		{"message_names": tuple(names)},
		as_dict=True,
	)
	full_name_set = set(_unique_strings(full_names))
	from frappe_whatsapp_core.workspace_api import _enrich_message_rows, _json_dict

	rows_by_conversation = defaultdict(list)
	for row in rows:
		if row.name in full_name_set:
			rows_by_conversation[row.conversation].append(row)
		else:
			row.failure = _json_dict(row.failure)
	for conversation, conversation_rows in rows_by_conversation.items():
		_enrich_message_rows(conversation_rows, conversation)
	return {row.name: dict(row) for row in rows}


def _change_message_projection(change: dict, message: dict) -> dict:
	if change["kind"] == "status":
		return {
			key: message.get(key)
			for key in (
				"name",
				"conversation",
				"provider_message_id",
				"delivery_status",
				"failure",
			)
		}
	projection = dict(message)
	if change["status"] != "created":
		projection.pop("bookmarked", None)
	return projection


def _unique_strings(values) -> list[str]:
	return list(dict.fromkeys(
		str(value).strip() for value in values or [] if str(value or "").strip()
	))
