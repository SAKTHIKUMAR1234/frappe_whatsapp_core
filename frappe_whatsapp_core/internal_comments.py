"""Team-only notes attached to a permission-scoped WhatsApp conversation."""

from __future__ import annotations

import frappe
from frappe.utils import cint

from frappe_whatsapp_core.permissions import (
	CORE_MANAGEMENT_ROLES,
	assert_conversation_access,
	require_core_access,
)

COMMENT_PAGE_SIZE = 30
COMMENT_MAX_PAGE_SIZE = 100


def _comment_projection(name: str) -> dict | None:
	rows = frappe.db.sql(
		"""
		SELECT
			comment.name, comment.conversation, comment.user, comment.content,
			comment.creation, comment.modified,
			COALESCE(NULLIF(profile.full_name, ''), NULLIF(profile.first_name, ''), comment.user)
				AS user_display_name,
			COALESCE(profile.user_image, '') AS user_image
		FROM `tabWhatsApp Core Internal Comment` AS comment
		LEFT JOIN `tabUser` AS profile ON profile.name = comment.user
		WHERE comment.name = %(name)s
		LIMIT 1
		""",
		{"name": name},
		as_dict=True,
	)
	return dict(rows[0]) if rows else None


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
			comment.creation, comment.modified,
			COALESCE(NULLIF(profile.full_name, ''), NULLIF(profile.first_name, ''), comment.user)
				AS user_display_name,
			COALESCE(profile.user_image, '') AS user_image
		FROM `tabWhatsApp Core Internal Comment` AS comment
		LEFT JOIN `tabUser` AS profile ON profile.name = comment.user
		WHERE {' AND '.join(conditions)}
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
		"rows": [dict(row) for row in reversed(page)],
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
def add_comment(conversation: str, content: str) -> dict:
	assert_conversation_access(conversation)
	doc = frappe.get_doc({
		"doctype": "WhatsApp Core Internal Comment",
		"conversation": conversation,
		"user": frappe.session.user,
		"content": content,
	}).insert(ignore_permissions=True)
	row = _comment_projection(doc.name)
	from frappe_whatsapp_core.realtime import publish_internal_comment_change

	publish_internal_comment_change(conversation, comment=row, status="created")
	return row


def _editable_comment(name: str):
	doc = frappe.get_doc("WhatsApp Core Internal Comment", str(name or "").strip())
	assert_conversation_access(doc.conversation)
	if doc.user != frappe.session.user and not set(frappe.get_roles()) & CORE_MANAGEMENT_ROLES:
		frappe.throw("Only the author or a WhatsApp Manager can change this comment", frappe.PermissionError)
	return doc


@frappe.whitelist()
@require_core_access()
def update_comment(comment: str, content: str) -> dict:
	doc = _editable_comment(comment)
	doc.content = content
	doc.save(ignore_permissions=True)
	row = _comment_projection(doc.name)
	from frappe_whatsapp_core.realtime import publish_internal_comment_change

	publish_internal_comment_change(doc.conversation, comment=row, status="updated")
	return row


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
