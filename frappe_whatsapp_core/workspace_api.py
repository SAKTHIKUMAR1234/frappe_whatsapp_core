"""Reusable conversation, message, team, and outbound APIs for `/whatsapp`."""

from __future__ import annotations

import json

import frappe
from frappe.utils import cint

from frappe_whatsapp_core.ai_summaries import attach_message_insights
from frappe_whatsapp_core.contact_presentation import present_identity_names
from frappe_whatsapp_core.conversation_reads import (
	attach_message_readers,
	mark_conversation_read,
)
from frappe_whatsapp_core.identity import contact_options
from frappe_whatsapp_core.message_media import add_media_url
from frappe_whatsapp_core.message_quotes import attach_quoted_messages
from frappe_whatsapp_core.message_reactions import attach_message_reactions
from frappe_whatsapp_core.naming import name_by_key
from frappe_whatsapp_core.permissions import (
	CORE_MANAGEMENT_ROLES,
	assert_conversation_access,
	conversation_conditions,
	require_core_access,
)
from frappe_whatsapp_core.profile_images import (
	attach_avatar,
	contact_avatar_url,
	prepare_avatar_file,
	team_avatar_url,
)
from frappe_whatsapp_core.realtime import publish_invalidation


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
			assigned_team.team_name AS assigned_team_name,
			assigned_team.icon AS assigned_team_icon,
			assigned_team.avatar AS assigned_team_avatar,
			conversation.assigned_user,
			conversation.last_inbound_at,
			conversation.last_message_at,
			identity.name AS identity,
			identity.display_value,
			identity.normalized_value,
			identity.avatar AS identity_avatar,
			identity.attributes,
			last_message.body AS last_message_body,
			last_message.message_type AS last_message_type,
			last_message.direction AS last_message_direction,
			COALESCE(SUM(
					CASE
						WHEN message.direction = 'Inbound'
							AND message.message_type != 'reaction'
							AND message_read.name IS NULL
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
						AND newest.message_type != 'reaction'
					ORDER BY newest.provider_timestamp DESC, newest.creation DESC, newest.name DESC
				LIMIT 1
			)
		LEFT JOIN `tabWhatsApp Core Message` message
			ON message.conversation = conversation.name
		LEFT JOIN `tabWhatsApp Core Message Read` message_read
			ON message_read.message = message.name
			AND message_read.user = %(user)s
		LEFT JOIN `tabWhatsApp Core Team` assigned_team
			ON assigned_team.name = conversation.assigned_team
		WHERE {where}
		GROUP BY conversation.name
		ORDER BY conversation.last_message_at DESC
		LIMIT %(limit)s OFFSET %(offset)s
		""",
		values,
		as_dict=True,
	)
	presentations = present_identity_names(
		[row.identity for row in rows], context={"surface": "workspace_inbox_list"}
	)
	for row in rows:
		row.unread_count = int(row.unread_count or 0)
		row.attributes = _json_dict(row.attributes)
		row.contact_presentation = dict(presentations.get(row.identity) or {})
		if row.identity_avatar:
			row.contact_presentation["avatar"] = contact_avatar_url(row.name)
		row.display_value = row.contact_presentation.get("display_name") or row.display_value
		row.phone_number = row.contact_presentation.get("secondary_text") or ""
		row.assigned_team_avatar_url = team_avatar_url(row.assigned_team) if row.assigned_team_avatar else ""
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
	presentation = present_identity_names(
		[identity.name], context={"surface": "workspace_conversation", "conversation": doc.name}
	).get(identity.name, {})
	presentation = dict(presentation)
	if identity.get("avatar"):
		presentation["avatar"] = contact_avatar_url(doc.name)
	return {
		**doc.as_dict(),
		"identity": {
			"name": identity.name,
			"display_value": presentation.get("display_name") or identity.display_value,
			"normalized_value": identity.normalized_value,
			"phone_number": presentation.get("secondary_text") or "",
			"attributes": _json_dict(identity.attributes),
			"presentation": presentation,
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
	before_creation: str | None = None,
	before_name: str | None = None,
	after: str | None = None,
	after_creation: str | None = None,
	after_name: str | None = None,
	limit: int = 50,
	search: str | None = None,
	category: str | None = None,
) -> dict:
	_assert_conversation_access(conversation)
	limit = min(max(int(limit or 50), 1), 100)
	if before and after:
		frappe.throw("Use either before or after, not both", frappe.ValidationError)
	filters = ["conversation = %(conversation)s", "message_type != 'reaction'"]
	values = {"conversation": conversation, "limit": limit + 1}
	ascending = bool(after)
	if before:
		values["before"] = before
		if before_creation and before_name:
			filters.append(
				"""(
					provider_timestamp < %(before)s
					OR (
						provider_timestamp = %(before)s
						AND (
							creation < %(before_creation)s
							OR (
								creation = %(before_creation)s
								AND name < %(before_name)s
							)
						)
					)
				)"""
			)
			values["before_creation"] = before_creation
			values["before_name"] = before_name
		elif before_creation:
			filters.append(
				"""(
					provider_timestamp < %(before)s
					OR (provider_timestamp = %(before)s AND creation < %(before_creation)s)
				)"""
			)
			values["before_creation"] = before_creation
		else:
			filters.append("provider_timestamp < %(before)s")
	if after:
		values["after"] = after
		if after_creation and after_name:
			filters.append(
				"""(
					provider_timestamp > %(after)s
					OR (
						provider_timestamp = %(after)s
						AND (
							creation > %(after_creation)s
							OR (
								creation = %(after_creation)s
								AND name > %(after_name)s
							)
						)
					)
				)"""
			)
			values["after_creation"] = after_creation
			values["after_name"] = after_name
		elif after_creation:
			filters.append(
				"""(
					provider_timestamp > %(after)s
					OR (provider_timestamp = %(after)s AND creation > %(after_creation)s)
				)"""
			)
			values["after_creation"] = after_creation
		else:
			filters.append("provider_timestamp > %(after)s")
	if search:
		filters.append("body LIKE %(search)s")
		values["search"] = f"%{search.strip()}%"
	category = str(category or "").strip()
	if category:
		filters.append(
			"""EXISTS (
				SELECT 1 FROM `tabWhatsApp Core Message Category Assignment` category_assignment
				WHERE category_assignment.message = `tabWhatsApp Core Message`.name
					AND category_assignment.category = %(category)s
			)"""
		)
		values["category"] = category
	rows = frappe.db.sql(
		f"""
		SELECT
			name, message_key, provider_message_id, direction, message_type,
			body, content, provider_timestamp, delivery_status, failure, owner, creation,
			EXISTS(
				SELECT 1 FROM `tabWhatsApp Core Message Bookmark` bookmark
				WHERE bookmark.message = `tabWhatsApp Core Message`.name
				AND bookmark.user = %(user)s
			) AS bookmarked
		FROM `tabWhatsApp Core Message`
		WHERE {" AND ".join(filters)}
		ORDER BY
			provider_timestamp {"ASC" if ascending else "DESC"},
			creation {"ASC" if ascending else "DESC"},
			name {"ASC" if ascending else "DESC"}
		LIMIT %(limit)s
		""",
		{**values, "user": frappe.session.user},
		as_dict=True,
	)
	has_more = len(rows) > limit
	rows = rows[:limit]
	_enrich_message_rows(rows, conversation)
	return {
		"rows": rows,
		"has_more": has_more,
		"next_before": rows[-1].provider_timestamp if not ascending and has_more and rows else None,
		"next_before_creation": rows[-1].creation if not ascending and has_more and rows else None,
		"next_before_name": rows[-1].name if not ascending and has_more and rows else None,
		"next_after": rows[-1].provider_timestamp if ascending and has_more and rows else None,
		"next_after_creation": rows[-1].creation if ascending and has_more and rows else None,
		"next_after_name": rows[-1].name if ascending and has_more and rows else None,
	}


@frappe.whitelist()
@require_core_access()
def refresh_messages(conversation: str, message_names) -> dict:
	"""Refresh the exact visible message window without resetting its read anchor.

	Realtime invalidations intentionally contain no protected row data.  The
	client therefore sends back only the message names it already holds and this
	permission-checked endpoint returns their current projections, including
	reactions and exact readers.  This keeps an older visible target bubble in
	place when a reaction arrives after the operator's navigation cursor.
	"""
	_assert_conversation_access(conversation)
	if isinstance(message_names, str):
		message_names = frappe.parse_json(message_names)
	if not isinstance(message_names, list):
		frappe.throw("message_names must be a list", frappe.ValidationError)
	names = list(dict.fromkeys(str(name).strip() for name in message_names if str(name).strip()))
	if len(names) > 500:
		frappe.throw("A visible message refresh cannot exceed 500 messages", frappe.ValidationError)
	if not names:
		return {"rows": []}
	rows = frappe.db.sql(
		"""
		SELECT
			name, message_key, provider_message_id, direction, message_type,
			body, content, provider_timestamp, delivery_status, failure, owner, creation,
			EXISTS(
				SELECT 1 FROM `tabWhatsApp Core Message Bookmark` bookmark
				WHERE bookmark.message = `tabWhatsApp Core Message`.name
					AND bookmark.user = %(user)s
			) AS bookmarked
		FROM `tabWhatsApp Core Message`
		WHERE conversation = %(conversation)s
			AND message_type != 'reaction'
			AND name IN %(names)s
		ORDER BY provider_timestamp ASC, creation ASC, name ASC
		""",
		{
			"conversation": conversation,
			"names": tuple(names),
			"user": frappe.session.user,
		},
		as_dict=True,
	)
	_enrich_message_rows(rows, conversation)
	return {"rows": rows}


def _enrich_message_rows(rows: list, conversation: str) -> None:
	"""Apply the same safe UI projection to paged and exact refresh rows."""
	owners = {row.owner for row in rows if row.direction == "Outbound" and row.owner}
	owner_names = (
		{
			row.name: row.full_name or row.name
			for row in frappe.get_all(
				"User",
				filters={"name": ["in", list(owners)]},
				fields=["name", "full_name"],
				limit_page_length=len(owners),
			)
		}
		if owners
		else {}
	)
	for row in rows:
		row.content = _json_dict(row.content)
		row.failure = _json_dict(row.failure)
		row.bookmarked = bool(row.bookmarked)
		row.sender_name = owner_names.get(row.owner, row.owner) if row.direction == "Outbound" else ""
		add_media_url(row)
	attach_quoted_messages(rows, conversation)
	attach_message_insights(rows)
	attach_message_reactions(rows, conversation)
	attach_message_readers(rows)


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
	local_file_url: str | None = None,
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
		local_file_url=local_file_url,
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
	if (team is not None or user is not None) and not (set(frappe.get_roles()) & CORE_MANAGEMENT_ROLES):
		frappe.throw(
			"WhatsApp Core management access is required for assignment",
			frappe.PermissionError,
		)
	if team and not frappe.db.exists("WhatsApp Core Team", {"name": team, "enabled": 1}):
		frappe.throw("Enabled team not found", frappe.ValidationError)
	if (
		user
		and team
		and not frappe.db.exists(
			"WhatsApp Core Team Member",
			{"parent": team, "user": user, "enabled": 1},
		)
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
	"""Return bounded team summaries without materializing child tables."""
	user = frappe.session.user
	manager = user == "Administrator" or bool(set(frappe.get_roles(user)) & CORE_MANAGEMENT_ROLES)
	values = {"user": user, "limit": 500}
	visibility = (
		"1 = 1"
		if manager
		else """EXISTS (
		SELECT 1 FROM `tabWhatsApp Core Team Member` scoped_member
		WHERE scoped_member.parent = team.name
			AND scoped_member.parenttype = 'WhatsApp Core Team'
			AND scoped_member.parentfield = 'members'
			AND scoped_member.enabled = 1
			AND scoped_member.user = %(user)s
	)"""
	)
	rows = frappe.db.sql(
		f"""
		SELECT
			team.name,
			team.team_name,
			team.icon,
			team.avatar,
			team.description,
			team.enabled,
			(
				SELECT COUNT(*) FROM `tabWhatsApp Core Team Member` member_count
				WHERE member_count.parent = team.name
					AND member_count.parenttype = 'WhatsApp Core Team'
					AND member_count.parentfield = 'members'
			) AS member_count,
			(
				SELECT COUNT(*) FROM `tabWhatsApp Core Team Contact` contact_count
				WHERE contact_count.parent = team.name
					AND contact_count.parenttype = 'WhatsApp Core Team'
					AND contact_count.parentfield = 'contacts'
			) AS contact_count
		FROM `tabWhatsApp Core Team` team
		WHERE team.enabled = 1
			AND {visibility}
		ORDER BY team.team_name ASC
		LIMIT %(limit)s
		""",
		values,
		as_dict=True,
	)
	for row in rows:
		row.avatar_url = team_avatar_url(row.name) if row.get("avatar") else ""
		row.avatar = ""
	return rows


@frappe.whitelist()
@require_core_access()
def search_team_options(search=None, limit=50) -> list[dict]:
	"""Return a permission-scoped, bounded LinkField page ordered newest first."""
	user = frappe.session.user
	manager = user == "Administrator" or bool(set(frappe.get_roles(user)) & CORE_MANAGEMENT_ROLES)
	values = {
		"user": user,
		"search": f"%{str(search or '').strip()}%",
		"limit": max(1, min(cint(limit or 50), 100)),
	}
	visibility = (
		"1 = 1"
		if manager
		else """EXISTS (
		SELECT 1 FROM `tabWhatsApp Core Team Member` scoped_member
		WHERE scoped_member.parent = team.name
			AND scoped_member.parenttype = 'WhatsApp Core Team'
			AND scoped_member.parentfield = 'members'
			AND scoped_member.enabled = 1
			AND scoped_member.user = %(user)s
	)"""
	)
	rows = frappe.db.sql(
		f"""
		SELECT team.name, team.team_name, team.description, team.icon, team.avatar
		FROM `tabWhatsApp Core Team` team
		WHERE team.enabled = 1
			AND {visibility}
			AND (
				team.name LIKE %(search)s
				OR team.team_name LIKE %(search)s
				OR team.description LIKE %(search)s
			)
		ORDER BY team.creation DESC, team.name DESC
		LIMIT %(limit)s
		""",
		values,
		as_dict=True,
	)
	for row in rows:
		row.avatar_url = team_avatar_url(row.name) if row.get("avatar") else ""
		row.avatar = ""
	return rows


def _user_options(search=None, limit=50, include=None) -> list[dict]:
	limit = max(1, min(cint(limit or 50), 100))
	filters = {"enabled": 1, "name": ["!=", "Guest"]}
	query = str(search or "").strip()
	users = frappe.get_all(
		"User",
		filters=filters,
		or_filters=(
			{
				"name": ["like", f"%{query}%"],
				"full_name": ["like", f"%{query}%"],
			}
			if query
			else None
		),
		fields=["name", "full_name", "user_image", "user_type"],
		order_by="full_name asc, name asc",
		limit_page_length=limit,
	)
	known = {user.name for user in users}
	missing = [name for name in dict.fromkeys(include or []) if name and name not in known]
	if missing:
		users.extend(
			frappe.get_all(
				"User",
				filters={"enabled": 1, "name": ["in", missing]},
				fields=["name", "full_name", "user_image", "user_type"],
				limit_page_length=len(missing),
			)
		)
	for user in users:
		user["label"] = (
			f"{user.full_name} ({user.name})" if user.full_name and user.full_name != user.name else user.name
		)
	return users


@frappe.whitelist()
@require_core_access(manage=True)
def search_team_users(search=None, limit=50) -> list[dict]:
	return _user_options(search=search, limit=limit)


@frappe.whitelist()
@require_core_access(manage=True)
def team_workspace() -> dict:
	"""Compatibility workspace containing summaries only.

	Assignments are loaded by their paginated endpoints when a manager opens one
	team. This avoids sending every site user and contact to the browser.
	"""
	return {"teams": list_teams(), "users": [], "contacts": []}


def _assignment_page(limit=50, offset=0) -> tuple[int, int]:
	return (
		max(1, min(cint(limit or 50), 100)),
		max(0, cint(offset or 0)),
	)


def _assert_team(team: str) -> str:
	name = str(team or "").strip()
	if not name or not frappe.db.exists("WhatsApp Core Team", name):
		frappe.throw("Team not found", frappe.DoesNotExistError)
	return name


def _publish_team(team: str, operation: str) -> None:
	frappe.db.set_value(
		"WhatsApp Core Team",
		team,
		"modified",
		frappe.utils.now_datetime(),
		update_modified=False,
	)
	publish_invalidation("whatsapp_core_team")


@frappe.whitelist()
@require_core_access(manage=True)
def team_member_page(team: str, search=None, limit=50, offset=0) -> dict:
	team = _assert_team(team)
	limit, offset = _assignment_page(limit, offset)
	values = {"team": team, "limit": limit + 1, "offset": offset}
	condition = ""
	query = str(search or "").strip()
	if query:
		condition = "AND (member.user LIKE %(search)s OR user.full_name LIKE %(search)s)"
		values["search"] = f"%{query}%"
	rows = frappe.db.sql(
		f"""
		SELECT member.name, member.user, member.team_role, member.enabled,
			user.full_name, user.user_image, user.user_type
		FROM `tabWhatsApp Core Team Member` member
		LEFT JOIN `tabUser` user ON user.name = member.user
		WHERE member.parent = %(team)s
			AND member.parenttype = 'WhatsApp Core Team'
			AND member.parentfield = 'members'
			{condition}
		ORDER BY member.idx ASC, member.creation ASC, member.name ASC
		LIMIT %(limit)s OFFSET %(offset)s
		""",
		values,
		as_dict=True,
	)
	return {"rows": rows[:limit], "has_more": len(rows) > limit, "offset": offset}


@frappe.whitelist()
@require_core_access(manage=True)
def team_contact_page(team: str, search=None, limit=50, offset=0) -> dict:
	team = _assert_team(team)
	limit, offset = _assignment_page(limit, offset)
	values = {"team": team, "limit": limit + 1, "offset": offset}
	condition = ""
	query = str(search or "").strip()
	if query:
		condition = """AND (
			contact.identity LIKE %(search)s
			OR identity.display_value LIKE %(search)s
			OR identity.normalized_value LIKE %(search)s
		)"""
		values["search"] = f"%{query}%"
	rows = frappe.db.sql(
		f"""
		SELECT contact.name, contact.identity, contact.enabled,
			identity.display_value, identity.normalized_value
		FROM `tabWhatsApp Core Team Contact` contact
		LEFT JOIN `tabWhatsApp Core Identity` identity ON identity.name = contact.identity
		WHERE contact.parent = %(team)s
			AND contact.parenttype = 'WhatsApp Core Team'
			AND contact.parentfield = 'contacts'
			{condition}
		ORDER BY contact.idx ASC, contact.creation ASC, contact.name ASC
		LIMIT %(limit)s OFFSET %(offset)s
		""",
		values,
		as_dict=True,
	)
	presentations = present_identity_names(
		[row.identity for row in rows], context={"surface": "team_contacts", "team": team}
	)
	for row in rows:
		presentation = presentations.get(row.identity) or {}
		row.contact_presentation = presentation
		row.display_value = presentation.get("display_name") or row.display_value
		row.phone_number = presentation.get("secondary_text") or ""
	return {"rows": rows[:limit], "has_more": len(rows) > limit, "offset": offset}


@frappe.whitelist()
@require_core_access(manage=True)
def add_team_member(team: str, user: str, team_role: str = "Agent") -> dict:
	team = _assert_team(team)
	user = str(user or "").strip()
	if not frappe.db.exists("User", {"name": user, "enabled": 1}):
		frappe.throw(f"Enabled user not found: {user}", frappe.ValidationError)
	existing = frappe.db.exists(
		"WhatsApp Core Team Member",
		{"parent": team, "parenttype": "WhatsApp Core Team", "user": user},
	)
	if existing:
		frappe.db.set_value(
			"WhatsApp Core Team Member",
			existing,
			{"team_role": team_role or "Agent", "enabled": 1},
		)
		name = existing
	else:
		name = (
			frappe.get_doc(
				{
					"doctype": "WhatsApp Core Team Member",
					"parent": team,
					"parenttype": "WhatsApp Core Team",
					"parentfield": "members",
					"user": user,
					"team_role": team_role or "Agent",
					"enabled": 1,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)
	_publish_team(team, "member_added")
	return frappe.get_doc("WhatsApp Core Team Member", name).as_dict()


@frappe.whitelist()
@require_core_access(manage=True)
def remove_team_member(team: str, user: str) -> dict:
	team = _assert_team(team)
	name = frappe.db.get_value(
		"WhatsApp Core Team Member",
		{"parent": team, "parenttype": "WhatsApp Core Team", "user": user},
		"name",
	)
	if name:
		frappe.delete_doc("WhatsApp Core Team Member", name, ignore_permissions=True)
		_publish_team(team, "member_removed")
	return {"team": team, "user": user, "removed": bool(name)}


@frappe.whitelist()
@require_core_access(manage=True)
def add_team_contact(team: str, identity: str) -> dict:
	team = _assert_team(team)
	identity = str(identity or "").strip()
	if not frappe.db.exists(
		"WhatsApp Core Identity",
		{"name": identity, "identity_type": "WhatsApp", "status": "Active"},
	):
		frappe.throw(f"Active WhatsApp contact not found: {identity}", frappe.ValidationError)
	existing = frappe.db.exists(
		"WhatsApp Core Team Contact",
		{"parent": team, "parenttype": "WhatsApp Core Team", "identity": identity},
	)
	if existing:
		frappe.db.set_value("WhatsApp Core Team Contact", existing, "enabled", 1)
		name = existing
	else:
		name = (
			frappe.get_doc(
				{
					"doctype": "WhatsApp Core Team Contact",
					"parent": team,
					"parenttype": "WhatsApp Core Team",
					"parentfield": "contacts",
					"identity": identity,
					"enabled": 1,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)
	_publish_team(team, "contact_added")
	return frappe.get_doc("WhatsApp Core Team Contact", name).as_dict()


@frappe.whitelist()
@require_core_access(manage=True)
def remove_team_contact(team: str, identity: str) -> dict:
	team = _assert_team(team)
	name = frappe.db.get_value(
		"WhatsApp Core Team Contact",
		{"parent": team, "parenttype": "WhatsApp Core Team", "identity": identity},
		"name",
	)
	if name:
		frappe.delete_doc("WhatsApp Core Team Contact", name, ignore_permissions=True)
		_publish_team(team, "contact_removed")
	return {"team": team, "identity": identity, "removed": bool(name)}


@frappe.whitelist()
@require_core_access(manage=True)
def upsert_team(
	team_name: str,
	icon: str = "users-round",
	avatar: str | None = None,
	description: str = "",
	enabled: int | bool = 1,
	members=None,
	contacts=None,
) -> dict:
	replace_members = members is not None
	replace_contacts = contacts is not None
	if isinstance(members, str):
		members = frappe.parse_json(members)
	if replace_members and not isinstance(members, list):
		frappe.throw("members must be a list", frappe.ValidationError)
	if isinstance(contacts, str):
		contacts = frappe.parse_json(contacts)
	if replace_contacts and not isinstance(contacts, list):
		frappe.throw("contacts must be a list", frappe.ValidationError)
	name = (team_name or "").strip()
	if not name:
		frappe.throw("Team name is required", frappe.ValidationError)
	record_name = name_by_key("WhatsApp Core Team", name)
	doc = (
		frappe.get_doc("WhatsApp Core Team", record_name)
		if record_name
		else frappe.new_doc("WhatsApp Core Team")
	)
	avatar_file = prepare_avatar_file(avatar) if avatar else None
	doc.team_name = name
	doc.icon = _team_icon(icon)
	if avatar is not None:
		doc.avatar = avatar_file.file_url if avatar_file else ""
	doc.description = description or ""
	doc.enabled = 1 if _as_bool(enabled) else 0
	if replace_members:
		doc.set("members", [])
		seen = set()
		for member in members:
			user = (member.get("user") or "").strip() if isinstance(member, dict) else ""
			if not user or user in seen:
				continue
			if not frappe.db.exists("User", user):
				frappe.throw(f"User not found: {user}", frappe.ValidationError)
			seen.add(user)
			doc.append(
				"members",
				{
					"user": user,
					"team_role": member.get("team_role") or "Agent",
					"enabled": 1 if member.get("enabled", True) else 0,
				},
			)
	if replace_contacts:
		doc.set("contacts", [])
		seen_contacts = set()
		for contact in contacts:
			identity = (contact.get("identity") or "").strip() if isinstance(contact, dict) else ""
			if not identity or identity in seen_contacts:
				continue
			if not frappe.db.exists(
				"WhatsApp Core Identity",
				{"name": identity, "identity_type": "WhatsApp", "status": "Active"},
			):
				frappe.throw(f"Active WhatsApp contact not found: {identity}", frappe.ValidationError)
			seen_contacts.add(identity)
			doc.append(
				"contacts",
				{
					"identity": identity,
					"enabled": 1 if contact.get("enabled", True) else 0,
				},
			)
	doc.save(ignore_permissions=True)
	if avatar_file:
		attach_avatar(avatar_file, "WhatsApp Core Team", doc.name)
	publish_invalidation("whatsapp_core_team")
	result = doc.as_dict()
	result.avatar_url = team_avatar_url(doc.name) if doc.avatar else ""
	result.avatar = ""
	return result


@frappe.whitelist()
@require_core_access(manage=True)
def update_contact_avatar(identity: str, avatar: str | None = None) -> dict:
	"""Set or clear one contact image without exposing its private File URL."""
	identity = str(identity or "").strip()
	if not frappe.db.exists(
		"WhatsApp Core Identity",
		{"name": identity, "identity_type": "WhatsApp", "status": "Active"},
	):
		frappe.throw("Active WhatsApp contact not found", frappe.DoesNotExistError)
	avatar_file = prepare_avatar_file(avatar) if avatar else None
	doc = frappe.get_doc("WhatsApp Core Identity", identity)
	doc.avatar = avatar_file.file_url if avatar_file else ""
	doc.save(ignore_permissions=True)
	if avatar_file:
		attach_avatar(avatar_file, "WhatsApp Core Identity", doc.name)
	publish_invalidation("whatsapp_core_contact")
	return {"identity": doc.name, "has_avatar": bool(doc.avatar)}


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
	assert_conversation_access(conversation)


def _conversation_conditions(alias: str) -> tuple[list[str], dict]:
	return conversation_conditions(alias)


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


def _team_icon(value) -> str:
	"""Keep the icon safe for both Desk's Icon field and the Core UI."""
	icon = str(value or "users-round").strip().lower()
	if not icon or len(icon) > 40 or any(not (character.isalnum() or character == "-") for character in icon):
		frappe.throw("Invalid team icon", frappe.ValidationError)
	return icon
