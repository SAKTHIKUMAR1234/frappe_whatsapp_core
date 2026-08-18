"""Attach legacy call rows to the same scoped conversations used by the inbox."""

import frappe

from frappe_whatsapp_core.identity import get_or_create_identity
from frappe_whatsapp_core.materializer import get_or_create_conversation


def execute():
	for row in frappe.get_all(
		"WhatsApp Core Call",
		filters={"conversation": ["is", "not set"]},
		fields=[
			"name",
			"channel",
			"remote_user_id",
			"remote_parent_user_id",
			"remote_number",
		],
		limit_page_length=0,
	):
		target = row.remote_user_id or row.remote_parent_user_id or row.remote_number
		if not target or not row.channel or not frappe.db.exists("WhatsApp Core Channel", row.channel):
			continue
		is_scoped = bool(row.remote_user_id or row.remote_parent_user_id)
		identity = get_or_create_identity(
			target,
			resolve=False,
			scope=row.channel if is_scoped else None,
			aliases={
				"phone": row.remote_number,
				"user_id": row.remote_user_id,
				"parent_user_id": row.remote_parent_user_id,
			},
		)
		conversation = get_or_create_conversation(
			frappe.get_cached_doc("WhatsApp Core Channel", row.channel), identity
		)
		frappe.db.set_value(
			"WhatsApp Core Call",
			row.name,
			{"remote_identity": identity.name, "conversation": conversation.name},
			update_modified=False,
		)
