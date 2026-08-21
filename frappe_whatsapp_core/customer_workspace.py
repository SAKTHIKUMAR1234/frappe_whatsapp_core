"""Customer-management projections layered on top of the shared inbox.

Folders are private operator preferences. Team metrics and read coverage always
reuse Core's canonical conversation scope; they never widen message access.
"""

from __future__ import annotations

import hashlib
import re

import frappe
from frappe.utils import cint

from frappe_whatsapp_core.permissions import (
	CORE_MANAGEMENT_ROLES,
	assert_identity_team_access,
	conversation_conditions,
	require_core_access,
)
from frappe_whatsapp_core.profile_images import team_avatar_url

IMPORTANT_FOLDER = "important"
MAX_CUSTOM_FOLDERS = 30
DEFAULT_FOLDER_COLOR = "#22c55e"


def _key(*parts: str) -> str:
	return hashlib.sha256(":".join(str(part) for part in parts).encode()).hexdigest()


def _folder_color(value: str | None) -> str:
	color = str(value or DEFAULT_FOLDER_COLOR).strip()
	return color if re.fullmatch(r"#[0-9a-fA-F]{6}", color) else DEFAULT_FOLDER_COLOR


def _folder_row(folder: str, *, user: str | None = None):
	user = user or frappe.session.user
	row = frappe.db.get_value(
		"WhatsApp Core Contact Folder",
		folder,
		["name", "user", "folder_name", "folder_type", "color", "position"],
		as_dict=True,
	)
	if not row or row.user != user:
		frappe.throw("Folder not found", frappe.DoesNotExistError)
	return row


def _important_folder(*, create: bool = False):
	user = frappe.session.user
	name = frappe.db.get_value(
		"WhatsApp Core Contact Folder",
		{"folder_key": _key(user, IMPORTANT_FOLDER)},
		"name",
	)
	if name or not create:
		return name
	return frappe.get_doc({
		"doctype": "WhatsApp Core Contact Folder",
		"folder_key": _key(user, IMPORTANT_FOLDER),
		"user": user,
		"folder_name": "Important",
		"folder_type": "Important",
		"color": "#f59e0b",
		"position": -1000,
	}).insert(ignore_permissions=True).name


@frappe.whitelist()
@require_core_access()
def contact_folders() -> list[dict]:
	"""Return the current user's private folders and contact counts."""
	user = frappe.session.user
	rows = frappe.db.sql(
		"""
		SELECT
			folder.name,
			folder.folder_name,
			folder.folder_type,
			folder.color,
			folder.position,
			COUNT(item.name) AS contact_count
		FROM `tabWhatsApp Core Contact Folder` AS folder
		LEFT JOIN `tabWhatsApp Core Contact Folder Item` AS item
			ON item.folder = folder.name AND item.user = %(user)s
		WHERE folder.user = %(user)s
		GROUP BY folder.name, folder.folder_name, folder.folder_type, folder.color, folder.position
		ORDER BY folder.position ASC, folder.creation ASC
		""",
		{"user": user},
		as_dict=True,
	)
	important = next((row for row in rows if row.folder_type == "Important"), None)
	custom = [row for row in rows if row.folder_type == "Custom"]
	result = [{
		"name": important.name if important else IMPORTANT_FOLDER,
		"folder_name": "Important",
		"folder_type": "Important",
		"color": "#f59e0b",
		"position": -1000,
		"contact_count": cint(important.contact_count) if important else 0,
	}]
	result.extend(custom)
	for row in result:
		row["contact_count"] = cint(row.get("contact_count"))
	return result


@frappe.whitelist(methods=["POST"])
@require_core_access()
def create_contact_folder(folder_name: str, color: str = "#22c55e") -> dict:
	user = frappe.session.user
	name = " ".join(str(folder_name or "").split())[:80]
	if not name:
		frappe.throw("Folder name is required", frappe.ValidationError)
	if name.casefold() == "important":
		frappe.throw("Important is a built-in folder", frappe.ValidationError)
	if frappe.db.count("WhatsApp Core Contact Folder", {"user": user, "folder_type": "Custom"}) >= MAX_CUSTOM_FOLDERS:
		frappe.throw(f"A user can create up to {MAX_CUSTOM_FOLDERS} folders", frappe.ValidationError)
	existing = frappe.db.sql(
		"""SELECT name FROM `tabWhatsApp Core Contact Folder`
		WHERE user = %(user)s AND LOWER(folder_name) = LOWER(%(folder_name)s) LIMIT 1""",
		{"user": user, "folder_name": name},
		pluck=True,
	)
	if existing:
		frappe.throw("A folder with this name already exists", frappe.DuplicateEntryError)
	position = cint(frappe.db.sql(
		"SELECT COALESCE(MAX(position), 0) FROM `tabWhatsApp Core Contact Folder` WHERE user = %s",
		(user,),
		pluck=True,
	)[0]) + 1
	doc = frappe.get_doc({
		"doctype": "WhatsApp Core Contact Folder",
		"folder_key": _key(user, name.casefold()),
		"user": user,
		"folder_name": name,
		"folder_type": "Custom",
		"color": _folder_color(color),
		"position": position,
	}).insert(ignore_permissions=True)
	_publish_folder_change()
	return {**doc.as_dict(), "contact_count": 0}


@frappe.whitelist(methods=["POST"])
@require_core_access()
def rename_contact_folder(folder: str, folder_name: str, color: str | None = None) -> dict:
	row = _folder_row(folder)
	if row.folder_type != "Custom":
		frappe.throw("The Important folder cannot be renamed", frappe.ValidationError)
	name = " ".join(str(folder_name or "").split())[:80]
	if not name or name.casefold() == "important":
		frappe.throw("Choose a different folder name", frappe.ValidationError)
	doc = frappe.get_doc("WhatsApp Core Contact Folder", row.name)
	doc.folder_name = name
	doc.folder_key = _key(frappe.session.user, name.casefold())
	if color is not None:
		doc.color = _folder_color(color)
	doc.save(ignore_permissions=True)
	_publish_folder_change()
	return doc.as_dict()


@frappe.whitelist(methods=["POST"])
@require_core_access()
def delete_contact_folder(folder: str) -> dict:
	row = _folder_row(folder)
	if row.folder_type != "Custom":
		frappe.throw("The Important folder cannot be deleted", frappe.ValidationError)
	frappe.db.delete("WhatsApp Core Contact Folder Item", {"folder": row.name, "user": row.user})
	frappe.delete_doc("WhatsApp Core Contact Folder", row.name, ignore_permissions=True)
	_publish_folder_change()
	return {"folder": row.name, "deleted": True}


@frappe.whitelist(methods=["POST"])
@require_core_access()
def set_contact_folder(identity: str, folder: str, enabled=1) -> dict:
	identity = str(identity or "").strip()
	if not frappe.db.exists("WhatsApp Core Identity", identity):
		frappe.throw("Contact not found", frappe.DoesNotExistError)
	assert_identity_team_access(identity)
	if str(folder or "").strip() == IMPORTANT_FOLDER:
		folder = _important_folder(create=bool(cint(enabled)))
		if not folder:
			return {"identity": identity, "folder": IMPORTANT_FOLDER, "enabled": False}
	row = _folder_row(folder)
	item_key = _key(frappe.session.user, row.name, identity)
	item_name = frappe.db.get_value(
		"WhatsApp Core Contact Folder Item", {"item_key": item_key}, "name"
	)
	if cint(enabled) and not item_name:
		frappe.get_doc({
			"doctype": "WhatsApp Core Contact Folder Item",
			"item_key": item_key,
			"folder": row.name,
			"user": frappe.session.user,
			"identity": identity,
		}).insert(ignore_permissions=True)
	elif not cint(enabled) and item_name:
		frappe.delete_doc("WhatsApp Core Contact Folder Item", item_name, ignore_permissions=True)
	folder_details = {
		"name": row.name,
		"folder_name": row.folder_name,
		"folder_type": row.folder_type,
		"color": row.color,
		"contact_count": frappe.db.count(
			"WhatsApp Core Contact Folder Item",
			{"folder": row.name, "user": frappe.session.user},
		),
	}
	conversation_names = frappe.get_list(
		"WhatsApp Core Conversation",
		filters={"remote_identity": identity},
		pluck="name",
		limit_page_length=100,
	)
	_publish_folder_change(
		identity=identity,
		folder_details=folder_details,
		enabled=bool(cint(enabled)),
		conversations=conversation_names,
	)
	return {
		"identity": identity,
		"folder": row.name,
		"folder_details": folder_details,
		"enabled": bool(cint(enabled)),
	}


def folders_for_identities(identity_names: list[str], *, user: str | None = None) -> dict[str, list[dict]]:
	user = user or frappe.session.user
	names = list(dict.fromkeys(str(value) for value in identity_names or [] if value))
	if not names:
		return {}
	rows = frappe.db.sql(
		"""
		SELECT item.identity, folder.name, folder.folder_name, folder.folder_type, folder.color
		FROM `tabWhatsApp Core Contact Folder Item` AS item
		JOIN `tabWhatsApp Core Contact Folder` AS folder ON folder.name = item.folder
		WHERE item.user = %(user)s AND folder.user = %(user)s
			AND item.identity IN %(identities)s
		ORDER BY folder.position ASC, folder.folder_name ASC
		""",
		{"user": user, "identities": tuple(names)},
		as_dict=True,
	)
	result: dict[str, list[dict]] = {}
	for row in rows:
		result.setdefault(row.identity, []).append({
			"name": row.name,
			"folder_name": row.folder_name,
			"folder_type": row.folder_type,
			"color": row.color,
		})
	return result


def folder_filter_condition(folder: str | None, *, identity_expression: str) -> tuple[str | None, dict]:
	folder = str(folder or "").strip()
	if not folder:
		return None, {}
	if folder == IMPORTANT_FOLDER:
		folder = _important_folder(create=False)
		if not folder:
			return "1 = 0", {}
	row = _folder_row(folder)
	return (
		f"""EXISTS (
			SELECT 1 FROM `tabWhatsApp Core Contact Folder Item` AS personal_folder_item
			WHERE personal_folder_item.folder = %(personal_folder)s
				AND personal_folder_item.user = %(personal_folder_user)s
				AND personal_folder_item.identity = {identity_expression}
		)""",
		{"personal_folder": row.name, "personal_folder_user": frappe.session.user},
	)


def eligible_readers(conversation: str) -> list[dict]:
	"""Return enabled operators responsible for reading one conversation."""
	row = frappe.db.get_value(
		"WhatsApp Core Conversation",
		conversation,
		["remote_identity", "assigned_team", "assigned_user"],
		as_dict=True,
	)
	if not row:
		return []
	teams = set(frappe.get_all(
		"WhatsApp Core Team Contact",
		filters={
			"parenttype": "WhatsApp Core Team",
			"parentfield": "contacts",
			"identity": row.remote_identity,
			"enabled": 1,
		},
		pluck="parent",
	))
	if row.assigned_team:
		teams.add(row.assigned_team)
	users = set()
	if teams:
		users.update(frappe.get_all(
			"WhatsApp Core Team Member",
			filters={
				"parent": ["in", list(teams)],
				"parenttype": "WhatsApp Core Team",
				"parentfield": "members",
				"enabled": 1,
			},
			pluck="user",
		))
	elif row.assigned_user:
		users.add(row.assigned_user)
	else:
		users.update(frappe.db.sql(
			"""
			SELECT DISTINCT role.parent
			FROM `tabHas Role` AS role
			JOIN `tabUser` AS user ON user.name = role.parent AND user.enabled = 1
			WHERE role.parenttype = 'User' AND role.parentfield = 'roles'
				AND role.role = 'WhatsApp User'
				AND NOT EXISTS (
					SELECT 1 FROM `tabWhatsApp Core Team Member` AS member
					JOIN `tabWhatsApp Core Team` AS team ON team.name = member.parent AND team.enabled = 1
					WHERE member.user = role.parent AND member.enabled = 1
				)
			""",
			pluck=True,
		))
	profiles = frappe.get_all(
		"User",
		filters={"name": ["in", list(users)], "enabled": 1},
		fields=["name", "full_name", "first_name", "last_name", "username", "user_image"],
		limit_page_length=len(users),
	) if users else []
	from frappe_whatsapp_core.conversation_reads import _reader_display_name
	return [{
		"user": profile.name,
		"display_name": _reader_display_name(profile, profile.name),
		"user_image": profile.user_image or "",
	} for profile in profiles]


def attach_read_coverage(messages: list, conversation: str) -> list[dict]:
	expected = eligible_readers(conversation)
	expected_users = {row["user"] for row in expected}
	profiles = {row["user"]: row for row in expected}
	for message in messages or []:
		read_users = {row.get("user") for row in message.get("read_by") or []}
		read_expected = expected_users & read_users
		message["read_coverage"] = {
			"read": len(read_expected),
			"expected": len(expected_users),
			"complete": bool(expected_users) and read_expected == expected_users,
			"unread_by": [profiles[user] for user in sorted(expected_users - read_expected)],
		}
	return expected


@frappe.whitelist()
@require_core_access()
def operations_dashboard() -> dict:
	"""Return permission-scoped customer operations and team workload metrics."""
	conditions, values = conversation_conditions("conversation")
	where = " AND ".join(conditions)
	values["user"] = frappe.session.user
	global_rows = frappe.db.sql(
		f"""
		SELECT
			COUNT(*) AS conversations,
			SUM(conversation.status = 'Open') AS open_conversations,
			SUM(COALESCE(conversation.assigned_team, '') = '' AND COALESCE(conversation.assigned_user, '') = '') AS unassigned_conversations,
			SUM(DATE(conversation.last_message_at) = CURRENT_DATE()) AS active_today,
			SUM(EXISTS (
				SELECT 1 FROM `tabWhatsApp Core Message` AS unread_message
				LEFT JOIN `tabWhatsApp Core Message Read` AS own_read
					ON own_read.message = unread_message.name AND own_read.user = %(user)s
				WHERE unread_message.conversation = conversation.name
					AND unread_message.direction = 'Inbound'
					AND unread_message.message_type != 'reaction'
					AND own_read.name IS NULL
			)) AS unread_conversations
		FROM `tabWhatsApp Core Conversation` AS conversation
		WHERE {where}
		""",
		values,
		as_dict=True,
	)[0]
	team_visibility, team_values = _team_visibility_sql()
	team_values.update(values)
	team_rows = frappe.db.sql(
		f"""
		SELECT
			team.name,
			team.team_name,
			team.icon,
			team.avatar,
			COUNT(DISTINCT member.name) AS member_count,
			COUNT(DISTINCT contact.identity) AS contact_count,
			COUNT(DISTINCT conversation.name) AS conversation_count,
			COUNT(DISTINCT CASE WHEN conversation.status = 'Open' THEN conversation.name END) AS open_conversations,
			COUNT(DISTINCT CASE WHEN unread_message.name IS NOT NULL AND own_read.name IS NULL THEN conversation.name END) AS unread_conversations,
			MAX(conversation.last_message_at) AS last_activity_at
		FROM `tabWhatsApp Core Team` AS team
		LEFT JOIN `tabWhatsApp Core Team Member` AS member
			ON member.parent = team.name
			AND member.parenttype = 'WhatsApp Core Team'
			AND member.parentfield = 'members'
			AND member.enabled = 1
		LEFT JOIN `tabWhatsApp Core Team Contact` AS contact
			ON contact.parent = team.name
			AND contact.parenttype = 'WhatsApp Core Team'
			AND contact.parentfield = 'contacts'
			AND contact.enabled = 1
		LEFT JOIN `tabWhatsApp Core Conversation` AS conversation
			ON conversation.remote_identity = contact.identity AND {where}
		LEFT JOIN `tabWhatsApp Core Message` AS unread_message
			ON unread_message.conversation = conversation.name
			AND unread_message.direction = 'Inbound' AND unread_message.message_type != 'reaction'
		LEFT JOIN `tabWhatsApp Core Message Read` AS own_read
			ON own_read.message = unread_message.name AND own_read.user = %(user)s
		WHERE team.enabled = 1 AND {team_visibility}
		GROUP BY team.name, team.team_name, team.icon, team.avatar
		ORDER BY unread_conversations DESC, open_conversations DESC, team.team_name ASC
		LIMIT 100
		""",
		team_values,
		as_dict=True,
	)
	for row in team_rows:
		for field in ("member_count", "contact_count", "conversation_count", "open_conversations", "unread_conversations"):
			row[field] = cint(row.get(field))
		row["avatar_url"] = team_avatar_url(row.name) if row.avatar else ""
		row["avatar"] = ""
	metrics = {key: cint(value) for key, value in global_rows.items()}
	return {"metrics": metrics, "teams": team_rows}


def _team_visibility_sql() -> tuple[str, dict]:
	user = frappe.session.user
	if user == "Administrator" or set(frappe.get_roles(user)) & CORE_MANAGEMENT_ROLES:
		return "1 = 1", {}
	return (
		"""EXISTS (
			SELECT 1 FROM `tabWhatsApp Core Team Member` AS visible_member
			WHERE visible_member.parent = team.name
				AND visible_member.parenttype = 'WhatsApp Core Team'
				AND visible_member.parentfield = 'members'
				AND visible_member.enabled = 1
				AND visible_member.user = %(team_user)s
		)""",
		{"team_user": user},
	)


def _publish_folder_change(
	*,
	identity: str | None = None,
	folder_details: dict | None = None,
	enabled: bool | None = None,
	conversations: list[str] | None = None,
) -> None:
	frappe.publish_realtime(
		"whatsapp_core_contact_folder",
		{
			"changed": True,
			"identity": identity or "",
			"folder_details": folder_details,
			"enabled": enabled,
			"conversations": conversations or [],
		},
		user=frappe.session.user,
		after_commit=True,
	)
