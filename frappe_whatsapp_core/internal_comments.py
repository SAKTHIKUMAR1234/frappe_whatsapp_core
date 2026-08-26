"""Team-only notes attached to a permission-scoped WhatsApp conversation."""

from __future__ import annotations

from urllib.parse import quote, urlencode

import frappe
from frappe.utils import cint

from frappe_whatsapp_core.permissions import (
	CORE_MANAGEMENT_ROLES,
	assert_conversation_access,
	require_core_access,
)

COMMENT_PAGE_SIZE = 30
COMMENT_MAX_PAGE_SIZE = 100
COMMENT_MAX_MESSAGE_REFERENCES = 50
COMMENT_MAX_MENTIONS = 20
COMMENT_REFERENCE_DOCTYPES = {
	"WhatsApp Core Conversation Topic",
	"WhatsApp Core Contact Summary",
	"WhatsApp Core Summary Period",
}


def _notification_link(comment: dict) -> str:
	conversation = str(comment.get("conversation") or "").strip()
	query = {"comment": str(comment.get("name") or "").strip()}
	references = _decoded_references(comment.get("message_references"))
	if references:
		query["message"] = references[0]
	return f"/whatsapp#/inbox/{quote(conversation, safe='')}?{urlencode(query)}"


def _message_references(value, conversation: str) -> list[str]:
	if isinstance(value, str):
		try:
			value = frappe.parse_json(value)
		except (TypeError, ValueError):
			frappe.throw("Message references must be a JSON list", frappe.ValidationError)
	references = list(
		dict.fromkeys(str(name or "").strip() for name in (value or []) if str(name or "").strip())
	)
	if len(references) > COMMENT_MAX_MESSAGE_REFERENCES:
		frappe.throw(
			f"An internal task can reference at most {COMMENT_MAX_MESSAGE_REFERENCES} messages",
			frappe.ValidationError,
		)
	if references:
		owned = set(
			frappe.get_all(
				"WhatsApp Core Message",
				filters={"name": ["in", references], "conversation": conversation},
				pluck="name",
				limit_page_length=len(references),
			)
		)
		if owned != set(references):
			frappe.throw(
				"One or more referenced messages do not belong to this conversation",
				frappe.ValidationError,
			)
	return references


def _eligible_assignees(conversation: str) -> set[str]:
	from frappe_whatsapp_core.realtime import conversation_recipients

	return set(conversation_recipients([conversation]).get(conversation, set()))


def _validate_assignee(conversation: str, assigned_to) -> str:
	assigned_to = str(assigned_to or "").strip()
	if assigned_to and assigned_to not in _eligible_assignees(conversation):
		frappe.throw(
			"The assignee is outside this conversation's team scope",
			frappe.PermissionError,
		)
	return assigned_to


def _mentioned_users(value, conversation: str) -> list[str]:
	if isinstance(value, str):
		try:
			value = frappe.parse_json(value)
		except (TypeError, ValueError):
			frappe.throw("Mentions must be a JSON list", frappe.ValidationError)
	users = list(dict.fromkeys(str(user or "").strip() for user in (value or []) if str(user or "").strip()))
	if len(users) > COMMENT_MAX_MENTIONS:
		frappe.throw(
			f"An internal note can mention at most {COMMENT_MAX_MENTIONS} team members",
			frappe.ValidationError,
		)
	outside_scope = set(users) - _eligible_assignees(conversation)
	if outside_scope:
		frappe.throw(
			"One or more mentioned users are outside this conversation's team scope", frappe.PermissionError
		)
	return users


def _parent_comment(value, conversation: str) -> str:
	name = str(value or "").strip()
	if not name:
		return ""
	parent_conversation = frappe.db.get_value("WhatsApp Core Internal Comment", name, "conversation")
	if not parent_conversation or parent_conversation != conversation:
		frappe.throw("The replied note does not belong to this conversation", frappe.ValidationError)
	return name


def _summary_reference(conversation: str, reference_doctype=None, reference_name=None) -> tuple[str, str]:
	reference_doctype = str(reference_doctype or "").strip()
	reference_name = str(reference_name or "").strip()
	if not reference_doctype and not reference_name:
		return "", ""
	if reference_doctype not in COMMENT_REFERENCE_DOCTYPES or not reference_name:
		frappe.throw("Select a valid conversation summary", frappe.ValidationError)
	conversation_identity = frappe.db.get_value("WhatsApp Core Conversation", conversation, "remote_identity")
	if reference_doctype == "WhatsApp Core Conversation Topic":
		owned = frappe.db.get_value(reference_doctype, reference_name, "conversation") == conversation
	else:
		owned = frappe.db.get_value(reference_doctype, reference_name, "identity") == conversation_identity
	if not owned:
		frappe.throw("The referenced summary does not belong to this conversation", frappe.ValidationError)
	return reference_doctype, reference_name


def _decoded_references(value) -> list[str]:
	if isinstance(value, list):
		return [str(name) for name in value if name]
	try:
		rows = frappe.parse_json(value or "[]")
	except (TypeError, ValueError):
		return []
	return [str(name) for name in rows if name] if isinstance(rows, list) else []


def _user_presentations(users: list[str]) -> list[dict]:
	users = list(dict.fromkeys(user for user in users if user))
	if not users:
		return []
	rows = frappe.get_all(
		"User",
		filters={"name": ["in", users]},
		fields=["name", "full_name", "first_name", "user_image"],
		limit_page_length=len(users),
	)
	by_name = {row.name: row for row in rows}
	return [
		{
			"name": user,
			"label": (
				(by_name[user].full_name or by_name[user].first_name or user) if user in by_name else user
			),
			"user_image": (by_name[user].user_image or "") if user in by_name else "",
		}
		for user in users
	]


def _enrich_comment_rows(rows) -> list[dict]:
	results = [dict(row) for row in rows]
	all_mentions = []
	all_messages = []
	for row in results:
		row["message_references"] = _decoded_references(row.get("message_references"))
		row["mentioned_users"] = _decoded_references(row.get("mentioned_users"))
		all_messages.extend(row["message_references"])
		all_mentions.extend(row["mentioned_users"])

	user_details = {row["name"]: row for row in _user_presentations(all_mentions)}
	message_rows = (
		frappe.get_all(
			"WhatsApp Core Message",
			filters={
				"name": ["in", list(dict.fromkeys(all_messages))],
				"conversation": [
					"in",
					list({row.get("conversation") for row in results if row.get("conversation")}),
				],
			},
			fields=["name", "conversation", "body", "message_type", "provider_timestamp"],
			limit_page_length=max(1, len(set(all_messages))),
		)
		if all_messages
		else []
	)
	messages = {(row.name, row.conversation): dict(row) for row in message_rows}
	topic_names = [
		row.get("reference_name")
		for row in results
		if row.get("reference_doctype") == "WhatsApp Core Conversation Topic" and row.get("reference_name")
	]
	period_names = [
		row.get("reference_name")
		for row in results
		if row.get("reference_doctype") == "WhatsApp Core Summary Period" and row.get("reference_name")
	]
	topic_rows = (
		frappe.get_all(
			"WhatsApp Core Conversation Topic",
			filters={"name": ["in", topic_names]},
			fields=["name", "conversation", "title"],
			limit_page_length=max(1, len(topic_names)),
		)
		if topic_names
		else []
	)
	topic_labels = {(row.name, row.conversation): row.title for row in topic_rows}
	period_labels = (
		{
			row.name: f"{row.period_type or 'Conversation'} summary"
			for row in frappe.get_all(
				"WhatsApp Core Summary Period",
				filters={"name": ["in", period_names]},
				fields=["name", "period_type"],
				limit_page_length=max(1, len(period_names)),
			)
		}
		if period_names
		else {}
	)
	for row in results:
		row["mentioned_user_details"] = [
			user_details[user] for user in row["mentioned_users"] if user in user_details
		]
		row["message_reference_details"] = [
			messages[(name, row.get("conversation"))]
			for name in row["message_references"]
			if (name, row.get("conversation")) in messages
		]
		doctype = row.get("reference_doctype")
		name = row.get("reference_name")
		if doctype == "WhatsApp Core Conversation Topic":
			row["reference_label"] = (
				topic_labels.get((name, row.get("conversation"))) or "Conversation summary"
			)
		elif doctype == "WhatsApp Core Summary Period":
			row["reference_label"] = period_labels.get(name) or "Conversation summary"
		elif doctype == "WhatsApp Core Contact Summary" and name:
			row["reference_label"] = "Contact summary"
		else:
			row["reference_label"] = ""
	return results


def _enrich_comment_row(row) -> dict:
	return _enrich_comment_rows([row])[0]


def _comment_projections(names: list[str]) -> list[dict]:
	names = list(dict.fromkeys(str(name or "").strip() for name in names if str(name or "").strip()))
	if not names:
		return []
	rows = frappe.db.sql(
		"""
		SELECT
			comment.name, comment.conversation, comment.user, comment.content,
			comment.message_references, comment.reference_doctype, comment.reference_name,
			comment.parent_comment, comment.mentioned_users, comment.assigned_to, comment.status,
			comment.resolved_by, comment.resolved_at, comment.creation, comment.modified,
			COALESCE(NULLIF(profile.full_name, ''), NULLIF(profile.first_name, ''), comment.user)
				AS user_display_name,
			COALESCE(profile.user_image, '') AS user_image,
			COALESCE(NULLIF(assignee.full_name, ''), NULLIF(assignee.first_name, ''), comment.assigned_to)
				AS assigned_to_display_name,
			COALESCE(assignee.user_image, '') AS assigned_to_image,
			COALESCE(NULLIF(parent_profile.full_name, ''), NULLIF(parent_profile.first_name, ''), parent.user)
				AS parent_user_display_name,
			COALESCE(parent.content, '') AS parent_content
		FROM `tabWhatsApp Core Internal Comment` AS comment
		LEFT JOIN `tabUser` AS profile ON profile.name = comment.user
		LEFT JOIN `tabUser` AS assignee ON assignee.name = comment.assigned_to
		LEFT JOIN `tabWhatsApp Core Internal Comment` AS parent ON parent.name = comment.parent_comment
		LEFT JOIN `tabUser` AS parent_profile ON parent_profile.name = parent.user
		WHERE comment.name IN %(names)s
		""",
		{"names": names},
		as_dict=True,
	)
	return _enrich_comment_rows(rows)


def _comment_projection(name: str) -> dict | None:
	rows = _comment_projections([name])
	return rows[0] if rows else None


def _comment_page(conversation: str, *, before=None, before_name=None, limit=COMMENT_PAGE_SIZE) -> dict:
	limit = min(COMMENT_MAX_PAGE_SIZE, max(1, cint(limit) or COMMENT_PAGE_SIZE))
	conditions = ["comment.conversation = %(conversation)s"]
	values = {"conversation": conversation, "limit": limit + 1}
	if before:
		conditions.append(
			"(comment.creation < %(before)s OR "
			"(comment.creation = %(before)s AND comment.name < %(before_name)s))"
		)
		values.update(before=before, before_name=str(before_name or ""))
	rows = frappe.db.sql(
		f"""
		SELECT
			comment.name, comment.conversation, comment.user, comment.content,
			comment.message_references, comment.reference_doctype, comment.reference_name,
			comment.parent_comment, comment.mentioned_users, comment.assigned_to, comment.status,
			comment.resolved_by, comment.resolved_at, comment.creation, comment.modified,
			COALESCE(NULLIF(profile.full_name, ''), NULLIF(profile.first_name, ''), comment.user)
				AS user_display_name,
			COALESCE(profile.user_image, '') AS user_image,
			COALESCE(NULLIF(assignee.full_name, ''), NULLIF(assignee.first_name, ''), comment.assigned_to)
				AS assigned_to_display_name,
			COALESCE(assignee.user_image, '') AS assigned_to_image,
			COALESCE(NULLIF(parent_profile.full_name, ''), NULLIF(parent_profile.first_name, ''), parent.user)
				AS parent_user_display_name,
			COALESCE(parent.content, '') AS parent_content
		FROM `tabWhatsApp Core Internal Comment` AS comment
		LEFT JOIN `tabUser` AS profile ON profile.name = comment.user
		LEFT JOIN `tabUser` AS assignee ON assignee.name = comment.assigned_to
		LEFT JOIN `tabWhatsApp Core Internal Comment` AS parent ON parent.name = comment.parent_comment
		LEFT JOIN `tabUser` AS parent_profile ON parent_profile.name = parent.user
		WHERE {" AND ".join(conditions)}
		ORDER BY comment.creation DESC, comment.name DESC
		LIMIT %(limit)s
		""",
		values,
		as_dict=True,
	)
	has_more = len(rows) > limit
	page = rows[:limit]
	oldest = page[-1] if page else None
	return {
		"rows": _enrich_comment_rows(reversed(page)),
		"has_more": has_more,
		"next_before": oldest.creation if has_more and oldest else None,
		"next_before_name": oldest.name if has_more and oldest else None,
	}


@frappe.whitelist()
@require_core_access()
def comment_page(conversation: str, before=None, before_name=None, limit=COMMENT_PAGE_SIZE) -> dict:
	assert_conversation_access(conversation)
	return _comment_page(conversation, before=before, before_name=before_name, limit=limit)


@frappe.whitelist()
@require_core_access()
def work_item_assignees(conversation: str) -> list[dict]:
	assert_conversation_access(conversation)
	users = sorted(_eligible_assignees(conversation))
	if not users:
		return []
	rows = frappe.get_all(
		"User",
		filters={"name": ["in", users], "enabled": 1},
		fields=["name", "full_name", "first_name", "user_image"],
		limit_page_length=len(users),
	)
	return [
		{
			"name": row.name,
			"label": row.full_name or row.first_name or row.name,
			"user_image": row.user_image or "",
		}
		for row in rows
	]


@frappe.whitelist()
@require_core_access()
def add_comment(
	conversation: str,
	content: str,
	message_references=None,
	assigned_to=None,
	mentioned_users=None,
	parent_comment=None,
	reference_doctype=None,
	reference_name=None,
) -> dict:
	assert_conversation_access(conversation)
	references = _message_references(message_references, conversation)
	assigned_to = _validate_assignee(conversation, assigned_to)
	mentions = _mentioned_users(mentioned_users, conversation)
	parent_comment = _parent_comment(parent_comment, conversation)
	reference_doctype, reference_name = _summary_reference(conversation, reference_doctype, reference_name)
	doc = frappe.get_doc(
		{
			"doctype": "WhatsApp Core Internal Comment",
			"conversation": conversation,
			"user": frappe.session.user,
			"content": content,
			"message_references": frappe.as_json(references),
			"reference_doctype": reference_doctype,
			"reference_name": reference_name,
			"parent_comment": parent_comment,
			"mentioned_users": frappe.as_json(mentions),
			"assigned_to": assigned_to,
			"status": "Open",
		}
	).insert(ignore_permissions=True)
	row = _comment_projection(doc.name)
	from frappe_whatsapp_core.realtime import publish_internal_comment_change

	publish_internal_comment_change(conversation, comment=row, status="created")
	_notify_collaborators(row)
	return row


def _editable_comment(name: str):
	doc = frappe.get_doc("WhatsApp Core Internal Comment", str(name or "").strip())
	assert_conversation_access(doc.conversation)
	if (
		doc.user != frappe.session.user
		and doc.assigned_to != frappe.session.user
		and not set(frappe.get_roles()) & CORE_MANAGEMENT_ROLES
	):
		frappe.throw(
			"Only the author, assignee or a WhatsApp Manager can change this task",
			frappe.PermissionError,
		)
	return doc


@frappe.whitelist()
@require_core_access()
def update_comment(
	comment: str,
	content: str | None = None,
	assigned_to=None,
	status: str | None = None,
	message_references=None,
	mentioned_users=None,
	reference_doctype=None,
	reference_name=None,
) -> dict:
	doc = _editable_comment(comment)
	previous_recipients = _comment_recipients(_comment_projection(doc.name))
	if content is not None:
		doc.content = content
	if assigned_to is not None:
		doc.assigned_to = _validate_assignee(doc.conversation, assigned_to)
	if status is not None:
		status = str(status or "").strip().title()
		if status not in {"Open", "Resolved"}:
			frappe.throw("Status must be Open or Resolved", frappe.ValidationError)
		doc.status = status
	if message_references is not None:
		doc.message_references = frappe.as_json(_message_references(message_references, doc.conversation))
	if mentioned_users is not None:
		doc.mentioned_users = frappe.as_json(_mentioned_users(mentioned_users, doc.conversation))
	if reference_doctype is not None or reference_name is not None:
		doc.reference_doctype, doc.reference_name = _summary_reference(
			doc.conversation, reference_doctype, reference_name
		)
	doc.save(ignore_permissions=True)
	row = _comment_projection(doc.name)
	from frappe_whatsapp_core.realtime import publish_internal_comment_change

	publish_internal_comment_change(doc.conversation, comment=row, status="updated")
	_notify_collaborators(row, previous_recipients=previous_recipients)
	return row


def _comment_recipients(comment: dict | None) -> set[str]:
	if not comment:
		return set()
	recipients = set(_decoded_references(comment.get("mentioned_users")))
	if comment.get("assigned_to"):
		recipients.add(comment["assigned_to"])
	if comment.get("parent_comment"):
		parent_user = frappe.db.get_value("WhatsApp Core Internal Comment", comment["parent_comment"], "user")
		if parent_user:
			recipients.add(parent_user)
	return {user for user in recipients if user and user != frappe.session.user}


def _notify_collaborators(comment: dict, *, previous_recipients=None) -> None:
	recipients = _comment_recipients(comment) - set(previous_recipients or set())
	if not recipients:
		return
	from frappe.desk.doctype.notification_log.notification_log import enqueue_create_notification

	enqueue_create_notification(
		list(recipients),
		{
			"type": "Mention",
			"subject": f"{comment.get('user_display_name') or 'A team member'} needs your attention in WhatsApp",
			"email_content": str(comment.get("content") or ""),
			"document_type": "WhatsApp Core Internal Comment",
			"document_name": comment.get("name"),
			"from_user": frappe.session.user,
			"link": _notification_link(comment),
		},
	)


@frappe.whitelist()
@require_core_access()
def collaboration_notifications(limit=20) -> dict:
	limit = min(100, max(1, cint(limit) or 20))
	rows = frappe.get_all(
		"Notification Log",
		filters={
			"for_user": frappe.session.user,
			"document_type": "WhatsApp Core Internal Comment",
		},
		fields=["name", "subject", "email_content", "document_name", "from_user", "read", "creation"],
		order_by="creation desc",
		limit_page_length=limit,
	)
	comments = {
		row["name"]: row
		for row in _comment_projections([notification.document_name for notification in rows])
	}
	result = []
	for notification in rows:
		comment = comments.get(notification.document_name)
		if not comment:
			continue
		try:
			assert_conversation_access(comment["conversation"])
		except frappe.PermissionError:
			continue
		result.append({**dict(notification), "conversation": comment["conversation"], "comment": comment})
	return {
		"rows": result,
		"unread": sum(1 for row in result if not row.get("read")),
	}


@frappe.whitelist()
@require_core_access()
def mark_collaboration_notification_read(notification: str) -> dict:
	name = str(notification or "").strip()
	if not frappe.db.exists(
		"Notification Log",
		{"name": name, "for_user": frappe.session.user, "document_type": "WhatsApp Core Internal Comment"},
	):
		frappe.throw("Notification not found", frappe.DoesNotExistError)
	frappe.db.set_value("Notification Log", name, "read", 1, update_modified=False)
	return {"success": True, "name": name}


@frappe.whitelist()
@require_core_access()
def delete_comment(comment: str) -> dict:
	doc = _editable_comment(comment)
	conversation = doc.conversation
	name = doc.name
	frappe.delete_doc(doc.doctype, name, ignore_permissions=True)
	from frappe_whatsapp_core.realtime import publish_internal_comment_change

	publish_internal_comment_change(conversation, comment={"name": name}, status="deleted")
	return {"success": True, "name": name, "conversation": conversation}
