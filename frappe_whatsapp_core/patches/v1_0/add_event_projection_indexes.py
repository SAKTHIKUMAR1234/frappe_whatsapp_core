"""Index the relations used by webhook projection and identity history reads."""

import frappe


def execute():
	frappe.db.add_index(
		"WhatsApp Core Conversation",
		["remote_identity", "channel"],
		"wa_core_conversation_identity_channel",
	)
	frappe.db.add_index(
		"WhatsApp Core Message",
		["relay_event", "direction", "provider_timestamp"],
		"wa_core_message_event_direction",
	)
	frappe.db.add_index(
		"WhatsApp Core Handler Run",
		["relay_event", "handler", "status"],
		"wa_core_handler_event_handler_status",
	)
	frappe.db.add_index(
		"WhatsApp Core Call",
		["relay_event", "modified"],
		"wa_core_call_event_modified",
	)
	frappe.db.add_index(
		"WhatsApp Core Group",
		["relay_event"],
		"wa_core_group_event",
	)
	frappe.db.add_index(
		"WhatsApp Core Party Binding",
		["identity", "status"],
		"wa_core_party_binding_identity_status",
	)
