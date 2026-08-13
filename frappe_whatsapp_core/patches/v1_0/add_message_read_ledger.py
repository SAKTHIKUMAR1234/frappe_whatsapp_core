"""Add indexed exact message reads and backfill existing aggregate cursors."""

import frappe


def execute():
	frappe.db.add_index(
		"WhatsApp Core Message Read",
		["message", "user"],
		"wa_core_message_reader",
	)
	frappe.db.add_index(
		"WhatsApp Core Message Read",
		["conversation", "user", "read_at"],
		"wa_core_conversation_user_read",
	)
	frappe.db.add_index(
		"WhatsApp Core Message Read",
		["contact", "read_at"],
		"wa_core_contact_read",
	)
	frappe.db.sql(
		"""
		INSERT IGNORE INTO `tabWhatsApp Core Message Read` (
			name, creation, modified, modified_by, owner, docstatus, idx,
			read_key, message, conversation, contact, user, read_at
		)
		SELECT
			SHA2(CONCAT(message.name, ':', read_cursor.user), 256),
			read_cursor.modified,
			read_cursor.modified,
			read_cursor.modified_by,
			read_cursor.owner,
			0,
			0,
			SHA2(CONCAT(message.name, ':', read_cursor.user), 256),
			message.name,
			message.conversation,
			conversation.remote_identity,
			read_cursor.user,
			COALESCE(read_cursor.last_read_at, read_cursor.modified)
		FROM `tabWhatsApp Core Conversation Read` read_cursor
		INNER JOIN `tabWhatsApp Core Conversation` conversation
			ON conversation.name = read_cursor.conversation
		INNER JOIN `tabWhatsApp Core Message` message
			ON message.name = read_cursor.last_read_message
			AND message.conversation = read_cursor.conversation
		"""
	)
