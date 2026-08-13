"""Bench-only proof helper for legacy API to Core throughput."""

from time import perf_counter
from unittest.mock import patch

import frappe


ADAPTERS = {
	"essdee": {
		"sender": "essdee_partners_api.whatsapp_integration.api.send.send_text",
		"resolver": "essdee_partners_api.whatsapp_core_adapter.outbound._phone_number_id",
		"legacy_doctype": "WhatsApp Message",
		"phone_argument": "to_number",
	},
	"sihma": {
		"sender": "sihma.sihma_whatsapp_integration.api.send.send_text",
		"resolver": "sihma.whatsapp_core_adapter.outbound._phone_number_id",
		"legacy_doctype": "Sihma WhatsApp Message",
		"phone_argument": "to_number",
	},
	"pasarai": {
		"sender": "pasarai_rotary.pasarai_whatsapp_integration.api.send.send_text",
		"resolver": "pasarai_rotary.whatsapp_core_adapter.outbound._phone_number_id",
		"legacy_doctype": "WhatsApp Message",
		"phone_argument": "to",
	},
}


def run(adapter: str, count: int = 1000) -> dict:
	"""Queue messages through a legacy dotted path, verify, then roll back."""
	config = ADAPTERS.get(str(adapter or "").strip().lower())
	if not config:
		frappe.throw("Unknown cutover benchmark adapter", frappe.ValidationError)
	count = max(1, min(int(count), 5000))
	frappe.set_user("Administrator")
	suffix = frappe.generate_hash(length=8).lower()
	phone_number_id = f"cutover-benchmark-{adapter}-{suffix}"
	channel = frappe.get_doc({
		"doctype": "WhatsApp Core Channel",
		"channel_key": f"meta:{phone_number_id}",
		"display_name": f"{adapter.title()} cutover benchmark",
		"provider": "meta",
		"phone_number_id": phone_number_id,
		"enabled": 1,
	}).insert(ignore_permissions=True)
	phone = f"91{int(suffix, 36) % 10_000_000_000:010d}"
	legacy_before = frappe.db.count(config["legacy_doctype"])
	core_before = frappe.db.count("WhatsApp Core Message")
	sender = frappe.get_attr(config["sender"])
	started = perf_counter()
	try:
		with (
			patch(config["resolver"], return_value=phone_number_id),
			patch("frappe_whatsapp_core.outbound.outbound_ready", return_value=True),
			patch("frappe_whatsapp_core.outbound._within_service_window", return_value=True),
			patch("frappe_whatsapp_core.outbound._enqueue_message_delivery"),
			patch("frappe_whatsapp_core.outbound.frappe.publish_realtime"),
		):
			for index in range(count):
				sender(
					**{
						config["phone_argument"]: phone,
						"message": f"Cutover performance proof {index}",
					}
				)
		elapsed = perf_counter() - started
		core_inserted = frappe.db.count("WhatsApp Core Message") - core_before
		legacy_inserted = frappe.db.count(config["legacy_doctype"]) - legacy_before
		return {
			"adapter": adapter,
			"requested": count,
			"core_inserted": core_inserted,
			"legacy_inserted": legacy_inserted,
			"elapsed_seconds": round(elapsed, 3),
			"messages_per_second": round(count / elapsed, 2),
			"channel": channel.name,
			"rolled_back": True,
			"passed": core_inserted == count and legacy_inserted == 0,
		}
	finally:
		frappe.db.rollback()
