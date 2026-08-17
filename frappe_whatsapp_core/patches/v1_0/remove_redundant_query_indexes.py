"""Remove prefix indexes superseded by the inbox covering indexes."""

from frappe.database.utils import drop_index_if_exists


def execute():
	# Both indexes below are strict left-prefixes of indexes retained by Core.
	# Keeping them adds write amplification and index storage without making an
	# additional query shape searchable.
	drop_index_if_exists(
		"tabWhatsApp Core Message",
		"conversation_provider_timestamp_index",
	)
	drop_index_if_exists(
		"tabWhatsApp Core Conversation Read",
		"wa_core_conversation_read_user",
	)
