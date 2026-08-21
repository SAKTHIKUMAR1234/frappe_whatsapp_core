"""Business-neutral shared inbox projections used by Core and company UIs."""

from __future__ import annotations

import hashlib
import json
import re

import frappe
from frappe.utils import cint

from frappe_whatsapp_core.ai_summaries import attach_message_insights, get_identity_summary
from frappe_whatsapp_core.contact_presentation import (
	present_identity_names,
	search_presented_identities,
)
from frappe_whatsapp_core.conversation_reads import (
	attach_message_readers,
	conversation_readers,
	mark_conversation_read,
)
from frappe_whatsapp_core.materializer import inbound_message_body
from frappe_whatsapp_core.message_media import add_media_url
from frappe_whatsapp_core.message_quotes import attach_quoted_messages
from frappe_whatsapp_core.message_reactions import attach_message_reactions
from frappe_whatsapp_core.naming import name_by_key
from frappe_whatsapp_core.outbound import outbound_state, template_message_snapshot
from frappe_whatsapp_core.permissions import (
	CORE_MANAGEMENT_ROLES,
	assert_conversation_access,
	conversation_conditions,
	require_core_access,
)
from frappe_whatsapp_core.profile_images import contact_avatar_url, team_avatar_url
from frappe_whatsapp_core.topics import list_topics


@frappe.whitelist()
@require_core_access()
def conversations(
	limit: int = 250,
	category: str | None = None,
	team: str | None = None,
	folder: str | None = None,
	search: str | None = None,
	unread_only=0,
	include_unread=1,
) -> list[dict]:
	limit = max(1, min(int(limit), 500))
	return _conversation_page(
		limit=limit,
		category=category,
		team=team,
		folder=folder,
		search=search,
		unread_only=unread_only,
		include_unread=include_unread,
	)[0]


@frappe.whitelist()
@require_core_access()
def conversation_page(
	limit: int = 20,
	before: str | None = None,
	before_name: str | None = None,
	category: str | None = None,
	team: str | None = None,
	folder: str | None = None,
	search: str | None = None,
	unread_only=0,
	include_unread=1,
) -> dict:
	"""Return a stable cursor page for the virtualized conversation list."""
	limit = max(1, min(int(limit or 20), 100))
	rows, has_more = _conversation_page(
		limit=limit,
		before=before,
		before_name=before_name,
		category=category,
		team=team,
		folder=folder,
		search=search,
		unread_only=unread_only,
		include_unread=include_unread,
	)
	oldest = rows[-1] if has_more and rows else None
	return {
		"rows": rows,
		"has_more": has_more,
		"next_before": oldest.get("last_message_at") if oldest else None,
		"next_before_name": oldest.get("name") if oldest else None,
	}


def _conversation_page(
	*,
	limit: int,
	before: str | None = None,
	before_name: str | None = None,
	category: str | None = None,
	team: str | None = None,
	folder: str | None = None,
	search: str | None = None,
	unread_only=0,
	include_unread=1,
) -> tuple[list[dict], bool]:
	conditions, values = conversation_conditions("conversation")
	if cint(unread_only):
		conditions.append(
			"""EXISTS (
				SELECT 1 FROM `tabWhatsApp Core Message` AS unread_filter_message
				LEFT JOIN `tabWhatsApp Core Message Read` AS unread_filter_read
					ON unread_filter_read.message = unread_filter_message.name
					AND unread_filter_read.user = %(unread_filter_user)s
				WHERE unread_filter_message.conversation = conversation.name
					AND unread_filter_message.direction = 'Inbound'
					AND unread_filter_message.message_type != 'reaction'
					AND unread_filter_read.name IS NULL
			)"""
		)
		values["unread_filter_user"] = frappe.session.user
	_add_conversation_search(
		conditions,
		values,
		search,
		presented_identities=search_presented_identities(search),
	)
	team = str(team or "").strip()
	if team:
		if not frappe.db.exists("WhatsApp Core Team", {"name": team, "enabled": 1}):
			frappe.throw("Enabled team not found", frappe.ValidationError)
		if not set(frappe.get_roles()) & CORE_MANAGEMENT_ROLES and not frappe.db.exists(
			"WhatsApp Core Team Member",
			{
				"parent": team,
				"parenttype": "WhatsApp Core Team",
				"parentfield": "members",
				"user": frappe.session.user,
				"enabled": 1,
			},
		):
			frappe.throw("This team is outside your access scope", frappe.PermissionError)
		conditions.append(
			"""EXISTS (
				SELECT 1
				FROM `tabWhatsApp Core Team Contact` AS team_filter
				WHERE team_filter.parent = %(team)s
					AND team_filter.parenttype = 'WhatsApp Core Team'
					AND team_filter.parentfield = 'contacts'
					AND team_filter.enabled = 1
					AND team_filter.identity = conversation.remote_identity
			)"""
		)
		values["team"] = team
	from frappe_whatsapp_core.customer_workspace import folder_filter_condition

	folder_condition, folder_values = folder_filter_condition(
		folder,
		identity_expression="conversation.remote_identity",
	)
	if folder_condition:
		conditions.append(folder_condition)
		values.update(folder_values)
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
	if before:
		values["before"] = before
		if before_name:
			conditions.append(
				"""(
					conversation.last_message_at < %(before)s
					OR (
						conversation.last_message_at = %(before)s
						AND conversation.name < %(before_name)s
					)
				)"""
			)
			values["before_name"] = before_name
		else:
			conditions.append("conversation.last_message_at < %(before)s")
	values["limit"] = limit + 1
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
		ORDER BY conversation.last_message_at DESC, conversation.name DESC
		LIMIT %(limit)s
		""",
		values,
		as_dict=True,
	)
	has_more = len(rows) > limit
	rows = rows[:limit]
	return _enrich_conversation_rows(rows, include_unread=bool(cint(include_unread))), has_more


@frappe.whitelist()
@require_core_access()
def conversation_unread_counts(conversations) -> dict[str, int]:
	"""Hydrate unread badges for a small, permission-scoped visible list window."""
	if isinstance(conversations, str):
		try:
			conversations = json.loads(conversations)
		except (TypeError, ValueError):
			conversations = [conversations]
	names = list(dict.fromkeys(str(name or "").strip() for name in (conversations or [])))
	names = [name for name in names if name][:100]
	if not names:
		return {}
	conditions, values = conversation_conditions("conversation")
	conditions.append("conversation.name IN %(requested_conversations)s")
	values["requested_conversations"] = tuple(names)
	visible = frappe.db.sql(
		f"""SELECT conversation.name
		FROM `tabWhatsApp Core Conversation` AS conversation
		WHERE {" AND ".join(conditions)}""",
		values,
		pluck=True,
	)
	counts = _unread_counts(visible) if visible else {}
	return {name: cint(counts.get(name)) for name in visible}


def _add_conversation_search(
	conditions: list[str],
	values: dict,
	search: str | None,
	*,
	presented_identities: list[str] | None = None,
) -> None:
	"""Add a bounded, presentation-aware candidate search to the canonical inbox query.

	The Vue client performs the final fuzzy ranking. Here we deliberately search a
	short prefix of every word so a small spelling error after the first characters
	still returns the contact as a candidate. Identity Links are included because a
	business application's display name is often different from Meta's raw identity.
	"""
	query = " ".join(str(search or "").strip().split())[:120]
	if not query:
		return
	terms = list(dict.fromkeys(re.findall(r"[^\W_]+", query.casefold())))[:6]
	if not terms:
		return
	presented_identities = list(dict.fromkeys(presented_identities or []))[:500]
	if presented_identities:
		values["search_presented_identities"] = tuple(presented_identities)
	presented_match = (
		" OR conversation.remote_identity IN %(search_presented_identities)s"
		if presented_identities
		else ""
	)
	term_conditions = []
	for index, term in enumerate(terms):
		digits = "".join(character for character in term if character.isdigit())
		fragment = digits if digits and len(digits) == len(term) else term[: min(3, len(term))]
		if not fragment:
			continue
		key = f"search_{index}"
		values[key] = f"%{fragment}%"
		pattern_key = f"search_pattern_{index}"
		values[pattern_key] = ".*".join(re.escape(character) for character in term[:12])
		text_pattern = (
			f" OR search_identity.display_value REGEXP %({pattern_key})s"
			if not digits or len(digits) != len(term)
			else ""
		)
		link_pattern = (
			f" OR search_link.display_name REGEXP %({pattern_key})s"
			if not digits or len(digits) != len(term)
			else ""
		)
		team_pattern = (
			f" OR search_team.team_name REGEXP %({pattern_key})s"
			if not digits or len(digits) != len(term)
			else ""
		)
		term_conditions.append(
			f"""(
				conversation.conversation_key LIKE %({key})s
				{presented_match}
				OR EXISTS (
					SELECT 1
					FROM `tabWhatsApp Core Identity` AS search_identity
					WHERE search_identity.name = conversation.remote_identity
						AND (
							search_identity.display_value LIKE %({key})s
							OR search_identity.normalized_value LIKE %({key})s
							{text_pattern}
						)
				)
				OR EXISTS (
					SELECT 1
					FROM `tabWhatsApp Core Identity Link` AS search_link
					WHERE search_link.identity = conversation.remote_identity
						AND search_link.status = 'Active'
						AND (
							search_link.display_name LIKE %({key})s
							OR search_link.reference_name LIKE %({key})s
							{link_pattern}
						)
				)
				OR EXISTS (
					SELECT 1
					FROM `tabWhatsApp Core Team` AS search_team
					WHERE search_team.enabled = 1
						AND (
							search_team.name = conversation.assigned_team
							OR EXISTS (
								SELECT 1
								FROM `tabWhatsApp Core Team Contact` AS search_team_contact
								WHERE search_team_contact.parent = search_team.name
									AND search_team_contact.parenttype = 'WhatsApp Core Team'
									AND search_team_contact.parentfield = 'contacts'
									AND search_team_contact.enabled = 1
									AND search_team_contact.identity = conversation.remote_identity
							)
						)
						AND (
							search_team.team_name LIKE %({key})s
							{team_pattern}
						)
				)
			)"""
		)
	if term_conditions:
		conditions.extend(term_conditions)


@frappe.whitelist()
@require_core_access()
def conversation_summary(name: str) -> dict | None:
	"""Return one list-row projection without reloading the whole inbox."""
	assert_conversation_access(name)
	conditions, values = conversation_conditions("conversation")
	conditions.append("conversation.name = %(name)s")
	values["name"] = name
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
		LIMIT 1
		""",
		values,
		as_dict=True,
	)
	result = _enrich_conversation_rows(rows)
	return result[0] if result else None


def _enrich_conversation_rows(
	rows,
	*,
	user: str | None = None,
	include_unread: bool = True,
) -> list[dict]:
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
				"avatar",
				"status",
			],
			limit_page_length=len(identity_names),
		)
	}
	bindings = _primary_bindings(identity_names)
	identity_aliases = _identity_search_aliases(identity_names)
	teams = _team_presentations({row.assigned_team for row in rows if row.assigned_team})
	contact_teams = _identity_team_presentations(identity_names)
	from frappe_whatsapp_core.customer_workspace import folders_for_identities

	contact_folders = folders_for_identities(identity_names, user=user)
	presentations = present_identity_names(identity_names, context={"surface": "inbox_list"})
	latest_messages = _latest_messages(conversation_names)
	latest_calls = _latest_calls(conversation_names)
	unread_counts = _unread_counts(conversation_names, user=user) if include_unread else {}

	result = []
	for row in rows:
		identity = identity_map.get(row.remote_identity) or {}
		presentation = dict(presentations.get(row.remote_identity) or {})
		if identity.get("avatar"):
			presentation["avatar"] = contact_avatar_url(row.name)
		display_name = presentation.get("display_name") or row.name
		latest_message = latest_messages.get(row.name)
		latest_call = latest_calls.get(row.name)
		if latest_call and (
			not latest_message or latest_call.provider_timestamp > latest_message.provider_timestamp
		):
			latest_message = latest_call
			if not row.last_message_at or latest_call.provider_timestamp > row.last_message_at:
				row.last_message_at = latest_call.provider_timestamp
		search_aliases = [
			*identity_aliases.get(row.remote_identity, []),
			presentation.get("display_name"),
			presentation.get("secondary_text"),
			presentation.get("reference"),
			presentation.get("entity_type"),
			*(team.get("team_name") for team in contact_teams.get(row.remote_identity, [])),
			(teams.get(row.assigned_team) or {}).get("team_name"),
		]
		result.append(
			{
				**row,
				"assigned_team_details": teams.get(row.assigned_team),
				"contact_teams": contact_teams.get(row.remote_identity, []),
				"contact_folders": contact_folders.get(row.remote_identity, []),
				"display_name": display_name,
				"phone_number": presentation.get("secondary_text") or "",
				"identity_status": identity.get("status") or "",
				"contact_presentation": presentation,
				"search_aliases": list(dict.fromkeys(value for value in search_aliases if value)),
				"party_binding": bindings.get(row.remote_identity),
				"latest_message": latest_message,
				"unread_count": unread_counts.get(row.name, 0),
			}
		)
	return result


def conversation_rows_for_realtime(
	conversation_names: list[str],
	*,
	user: str | None = None,
	include_unread: bool = True,
) -> list[dict]:
	"""Build trusted list-row projections for already-authorized realtime rooms.

	The realtime dispatcher performs the canonical conversation access check before
	calling this helper. Keeping the projection query separate from the whitelisted
	``conversation_summary`` endpoint avoids impersonating each recipient or making
	the browser perform an API round trip for a conversation that just arrived.
	"""
	names = list(dict.fromkeys(str(name).strip() for name in conversation_names or [] if str(name).strip()))
	if not names:
		return []
	rows = frappe.db.sql(
		"""
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
		WHERE conversation.name IN %(conversation_names)s
		ORDER BY conversation.last_message_at DESC, conversation.name DESC
		""",
		{"conversation_names": tuple(names)},
		as_dict=True,
	)
	return _enrich_conversation_rows(
		rows,
		user=user,
		include_unread=include_unread,
	)


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
def conversation(name: str, message_limit: int = 30) -> dict:
	message_limit = max(1, min(int(message_limit or 30), 100))
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
	presentation = dict(presentation)
	if identity.get("avatar"):
		presentation["avatar"] = contact_avatar_url(doc.name)
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
	from frappe_whatsapp_core.calling import _call_rows

	calls = _call_rows(conversation=doc.name, limit=100)
	_enrich_message_senders(messages)
	_attach_template_snapshots(messages)
	attach_message_reactions(messages, doc.name)
	attach_message_readers(messages)
	from frappe_whatsapp_core.customer_workspace import attach_read_coverage, folders_for_identities
	from frappe_whatsapp_core.internal_comments import _comment_page

	expected_readers = attach_read_coverage(messages, doc.name)
	contact_folders = folders_for_identities([identity.name]).get(identity.name, [])
	internal_comment_page = _comment_page(doc.name)
	bookmarks = (
		set(
			frappe.get_all(
				"WhatsApp Core Message Bookmark",
				filters={"user": frappe.session.user, "message": ["in", [row.name for row in messages]]},
				pluck="message",
			)
		)
		if messages
		else set()
	)
	for row in messages:
		row.bookmarked = row.name in bookmarks
		add_media_url(row)
	attach_quoted_messages(messages, doc.name)
	attach_message_insights(messages)
	return {
		"conversation": doc.as_dict(),
		"assigned_team_details": assigned_team,
		"contact_teams": contact_teams,
		"contact_folders": contact_folders,
		"identity": identity.as_dict(),
		"display_name": presentation.get("display_name") or identity.normalized_value,
		"contact_presentation": presentation,
		"party_bindings": bindings,
		"messages": messages,
		"calls": calls,
		"message_page": message_page,
		"resume_message": resume_message,
		"current_user_read": current_read,
		"topics": list_topics(doc.name),
		"contact_summary": get_identity_summary(identity.name),
		"readers": readers,
		"expected_readers": expected_readers,
		"current_user": frappe.session.user,
		"internal_comments": internal_comment_page["rows"],
		"internal_comment_page": {
			key: value for key, value in internal_comment_page.items() if key != "rows"
		},
		"outbound": outbound_state(doc.name),
		"templates": frappe.get_all(
			"WhatsApp Core Template",
			filters={
				"enabled": 1,
				"approval_status": "APPROVED",
				"channel": doc.channel,
			},
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


def _attach_template_snapshots(messages) -> None:
	"""Enrich legacy template rows without mutating their historical database record."""
	for row in messages:
		if row.get("message_type") != "template":
			continue
		try:
			content = json.loads(row.get("content") or "{}")
		except (TypeError, ValueError):
			content = {}
		if not isinstance(content, dict) or content.get("template_snapshot"):
			continue
		record = content.get("template_record")
		if not record or not frappe.db.exists("WhatsApp Core Template", record):
			continue
		template_doc = frappe.get_cached_doc("WhatsApp Core Template", record)
		snapshot = template_message_snapshot(template_doc, content.get("components") or [])
		content["template_snapshot"] = snapshot
		row.content = json.dumps(content, separators=(",", ":"), ensure_ascii=False)
		if not row.get("body") or row.get("body") == content.get("template"):
			row.body = snapshot.get("body") or snapshot.get("header") or row.get("body")


def _conversation_message_rows(conversation: str, limit: int, current_read) -> tuple[list, dict, str | None]:
	"""Resume at the user's cursor, or at the first unread message for a new reader.

	The exact message-read ledger intentionally allows unread holes.  Those holes
	must continue to drive unread counts, but they must not drag a returning user
	backward after they deliberately jumped to and read a newer viewport.
	"""
	fields = """
		name, provider_message_id, direction, message_type, body, content,
		provider_timestamp, delivery_status, failure, owner, creation
	"""
	first_unread = frappe.db.sql(
		"""
		SELECT message.name, message.provider_timestamp, message.creation
		FROM `tabWhatsApp Core Message` message
		LEFT JOIN `tabWhatsApp Core Message Read` message_read
			ON message_read.message = message.name
			AND message_read.user = %(user)s
		WHERE message.conversation = %(conversation)s
			AND message.direction = 'Inbound'
			AND message.message_type != 'reaction'
			AND message_read.name IS NULL
		ORDER BY message.provider_timestamp ASC, message.creation ASC, message.name ASC
		LIMIT 1
		""",
		{"conversation": conversation, "user": frappe.session.user},
		as_dict=True,
	)
	anchor = []
	# A saved cursor is meaningful only while unread messages remain. Once the
	# exact ledger says the conversation is fully read, open the normal latest
	# page and place its final message at the bottom like a regular chat client.
	# If older unread holes remain, keep the monotonic cursor so an intentional
	# jump forward does not drag the operator back through already-seen context.
	resume_from_saved_cursor = bool(first_unread and current_read and current_read.get("last_read_message"))
	if resume_from_saved_cursor:
		anchor = frappe.db.sql(
			"""
			SELECT name, provider_timestamp, creation
			FROM `tabWhatsApp Core Message`
			WHERE name = %(message)s
				AND conversation = %(conversation)s
				AND message_type != 'reaction'
			LIMIT 1
			""",
			{
				"message": current_read.last_read_message,
				"conversation": conversation,
			},
			as_dict=True,
		)
	if not anchor and first_unread:
		anchor = first_unread
	anchor = anchor[0] if anchor else None
	if anchor:
		values = {
			"conversation": conversation,
			"at": anchor.provider_timestamp,
			"creation": anchor.creation,
			"anchor_name": anchor.name,
			"limit": limit + 1,
		}
		if resume_from_saved_cursor:
			messages = frappe.db.sql(
				f"""
				SELECT {fields}
				FROM `tabWhatsApp Core Message`
				WHERE conversation = %(conversation)s AND message_type != 'reaction'
					AND (
						provider_timestamp < %(at)s
						OR (
							provider_timestamp = %(at)s
							AND (
								creation < %(creation)s
								OR (creation = %(creation)s AND name <= %(anchor_name)s)
							)
						)
					)
				ORDER BY provider_timestamp DESC, creation DESC, name DESC
				LIMIT %(limit)s
				""",
				values,
				as_dict=True,
			)
			has_more_older = len(messages) > limit
			messages = messages[:limit]
			messages.reverse()
			has_more_newer = bool(
				frappe.db.sql(
					"""
				SELECT name
				FROM `tabWhatsApp Core Message`
				WHERE conversation = %(conversation)s AND message_type != 'reaction'
					AND (
						provider_timestamp > %(at)s
						OR (
							provider_timestamp = %(at)s
							AND (
								creation > %(creation)s
								OR (creation = %(creation)s AND name > %(anchor_name)s)
							)
						)
					)
				LIMIT 1
				""",
					values,
				)
			)
			oldest = messages[0] if messages else None
			newest = messages[-1] if messages else None
			return (
				messages,
				{
					"has_more": has_more_older,
					"has_more_newer": has_more_newer,
					"next_before": oldest.provider_timestamp if has_more_older and oldest else None,
					"next_before_creation": oldest.creation if has_more_older and oldest else None,
					"next_before_name": oldest.name if has_more_older and oldest else None,
					"next_after": newest.provider_timestamp if has_more_newer and newest else None,
					"next_after_creation": newest.creation if has_more_newer and newest else None,
					"next_after_name": newest.name if has_more_newer and newest else None,
				},
				anchor.name,
			)
		newer = frappe.db.sql(
			f"""
			SELECT {fields}
			FROM `tabWhatsApp Core Message`
			WHERE conversation = %(conversation)s AND message_type != 'reaction'
				AND (
					provider_timestamp > %(at)s
					OR (
						provider_timestamp = %(at)s
						AND (
							creation > %(creation)s
							OR (creation = %(creation)s AND name >= %(anchor_name)s)
						)
					)
				)
			ORDER BY provider_timestamp ASC, creation ASC, name ASC
			LIMIT %(limit)s
			""",
			values,
			as_dict=True,
		)
		has_more_newer = len(newer) > limit
		newer = newer[:limit]
		has_more_older = bool(
			frappe.db.sql(
				"""
			SELECT name
			FROM `tabWhatsApp Core Message`
			WHERE conversation = %(conversation)s AND message_type != 'reaction'
				AND (
					provider_timestamp < %(at)s
					OR (
						provider_timestamp = %(at)s
						AND (
							creation < %(creation)s
							OR (creation = %(creation)s AND name < %(anchor_name)s)
						)
					)
				)
			LIMIT 1
			""",
				values,
			)
		)
		messages = newer
		oldest = messages[0] if messages else None
		newest = newer[-1] if newer else None
		return (
			messages,
			{
				"has_more": has_more_older,
				"has_more_newer": has_more_newer,
				"next_before": oldest.provider_timestamp if has_more_older and oldest else None,
				"next_before_creation": oldest.creation if has_more_older and oldest else None,
				"next_before_name": oldest.name if has_more_older and oldest else None,
				"next_after": newest.provider_timestamp if has_more_newer and newest else None,
				"next_after_creation": newest.creation if has_more_newer and newest else None,
				"next_after_name": newest.name if has_more_newer and newest else None,
			},
			anchor.name,
		)

	messages = frappe.db.sql(
		f"""
		SELECT {fields}
		FROM `tabWhatsApp Core Message`
		WHERE conversation = %(conversation)s AND message_type != 'reaction'
		ORDER BY provider_timestamp DESC, creation DESC, name DESC
		LIMIT %(limit)s
		""",
		{"conversation": conversation, "limit": limit + 1},
		as_dict=True,
	)
	has_more = len(messages) > limit
	messages = messages[:limit]
	oldest = messages[-1] if messages else None
	messages.reverse()
	return (
		messages,
		{
			"has_more": has_more,
			"has_more_newer": False,
			"next_before": oldest.provider_timestamp if has_more and oldest else None,
			"next_before_creation": oldest.creation if has_more and oldest else None,
			"next_before_name": oldest.name if has_more and oldest else None,
			"next_after": None,
			"next_after_creation": None,
			"next_after_name": None,
		},
		None,
	)


def _team_presentations(team_names) -> dict[str, dict]:
	names = [name for name in set(team_names or []) if name]
	if not names:
		return {}
	rows = frappe.get_all(
		"WhatsApp Core Team",
		filters={"name": ["in", names]},
		fields=["name", "team_name", "icon", "avatar", "enabled"],
		limit_page_length=len(names),
	)
	for row in rows:
		row.avatar_url = team_avatar_url(row.name) if row.get("avatar") else ""
		row.avatar = ""
	return {row.name: row for row in rows}


def _identity_search_aliases(identity_names) -> dict[str, list[str]]:
	names = [name for name in set(identity_names or []) if name]
	result = {name: [] for name in names}
	if not names:
		return result
	rows = frappe.get_all(
		"WhatsApp Core Identity Link",
		filters={"identity": ["in", names], "status": "Active"},
		fields=["identity", "display_name", "reference_name"],
		order_by="is_primary desc, modified desc",
		limit_page_length=max(100, len(names) * 5),
	)
	for row in rows:
		for value in (row.display_name, row.reference_name):
			value = str(value or "").strip()
			if value and value not in result[row.identity]:
				result[row.identity].append(value)
	return result


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
			team.avatar,
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
		result.setdefault(row.identity, []).append(
			{
				"name": row.name,
				"team_name": row.team_name,
				"icon": row.icon,
				"avatar_url": team_avatar_url(row.name) if row.get("avatar") else "",
				"enabled": row.enabled,
			}
		)
	return result


def _enrich_message_senders(messages) -> None:
	owners = {row.get("owner") for row in messages if row.get("direction") == "Outbound" and row.get("owner")}
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
			names.get(row.get("owner"), row.get("owner")) if row.get("direction") == "Outbound" else ""
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
	record_name = frappe.db.get_value(
		"WhatsApp Core Message Bookmark",
		{"message": message, "user": frappe.session.user},
		"name",
	) or name_by_key("WhatsApp Core Message Bookmark", key)
	if record_name:
		frappe.delete_doc("WhatsApp Core Message Bookmark", record_name, ignore_permissions=True)
		return {"message": message, "bookmarked": False}
	frappe.get_doc(
		{
			"doctype": "WhatsApp Core Message Bookmark",
			"bookmark_key": key,
			"message": message,
			"conversation": conversation_name,
			"user": frappe.session.user,
		}
	).insert(ignore_permissions=True)
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


def _latest_calls(conversation_names: list[str]) -> dict:
	"""Project the newest call as a familiar conversation-list activity row."""
	rows = frappe.db.sql(
		"""
		SELECT
			ranked.name,
			ranked.call_id,
			ranked.conversation,
			ranked.direction,
			ranked.status,
			ranked.provider_timestamp
		FROM (
			SELECT
				call_log.name,
				call_log.call_id,
				call_log.conversation,
				call_log.direction,
				call_log.status,
				COALESCE(
					call_log.ended_at,
					call_log.started_at,
					call_log.creation
				) AS provider_timestamp,
				ROW_NUMBER() OVER (
					PARTITION BY call_log.conversation
					ORDER BY
						COALESCE(
							call_log.ended_at,
							call_log.started_at,
							call_log.creation
						) DESC,
						call_log.name DESC
				) AS row_rank
			FROM `tabWhatsApp Core Call` AS call_log
			WHERE call_log.conversation IN %(conversation_names)s
		) AS ranked
		WHERE ranked.row_rank = 1
		""",
		{"conversation_names": tuple(conversation_names)},
		as_dict=True,
	)
	for row in rows:
		row.message_type = "call"
		row.delivery_status = row.status
		row.body = _call_preview(row)
	return {row.conversation: row for row in rows}


def _call_preview(call) -> str:
	direction = "Incoming" if call.direction == "Inbound" else "Outgoing"
	status = str(call.status or "").lower()
	if status in {"missed", "reject", "rejected", "failed"}:
		return f"{direction} call · {status.title()}"
	if status in {"terminate", "terminated", "ended"}:
		return f"{direction} call · Completed"
	if status in {"accept", "accepted", "connected"}:
		return f"{direction} call · Answered"
	return f"{direction} call"


def _unread_counts(conversation_names: list[str], *, user: str | None = None) -> dict:
	rows = frappe.db.sql(
		"""
		SELECT
			message.conversation,
			COUNT(*) AS unread_count
		FROM `tabWhatsApp Core Message` AS message
		LEFT JOIN `tabWhatsApp Core Message Read` AS message_read
			ON message_read.message = message.name
			AND message_read.user = %(user)s
		WHERE message.conversation IN %(conversation_names)s
			AND message.direction = 'Inbound'
			AND message.message_type != 'reaction'
			AND message_read.name IS NULL
		GROUP BY message.conversation
		""",
		{
			"conversation_names": tuple(conversation_names),
			"user": user or frappe.session.user,
		},
		as_dict=True,
	)
	return {row.conversation: int(row.unread_count or 0) for row in rows}
