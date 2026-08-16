"""Monotonic provider delivery-state transitions."""

from __future__ import annotations

import frappe

DELIVERY_RANK = {
	"Queued": 0,
	"Sent": 1,
	"Delivered": 2,
	"Read": 3,
}


def advance_delivery_status(current: str | None, incoming: str) -> str:
	"""Return a state that never regresses after a late provider callback."""
	current = current or "Queued"
	if incoming == "Deleted" or current == "Deleted":
		return "Deleted"
	if incoming == "Failed":
		return current if current in {"Delivered", "Read"} else "Failed"
	if current == "Failed":
		return current
	if incoming not in DELIVERY_RANK:
		return current
	if current not in DELIVERY_RANK:
		return incoming
	return (
		incoming
		if DELIVERY_RANK[incoming] > DELIVERY_RANK[current]
		else current
	)


def enqueue_delivery_status_handlers(updates) -> None:
	"""Project committed Core delivery changes into installed business apps."""
	paths = frappe.get_hooks("whatsapp_core_delivery_status_handlers") or []
	if isinstance(paths, str):
		paths = [paths]
	if not any(paths):
		return
	if isinstance(updates, dict):
		updates = [updates]
	normalized = []
	for row in updates or []:
		message_name = str(row.get("message_name") or row.get("message") or "").strip()
		delivery_status = str(row.get("delivery_status") or "").strip().title()
		if message_name and delivery_status:
			normalized.append({
				"message_name": message_name,
				"delivery_status": delivery_status,
			})
	if not normalized:
		return
	frappe.enqueue(
		"frappe_whatsapp_core.delivery.dispatch_delivery_status_handlers",
		queue="short",
		enqueue_after_commit=True,
		updates=normalized,
	)


def dispatch_delivery_status_handlers(updates) -> None:
	"""Run trusted local projections using the latest authoritative Core state."""
	paths = frappe.get_hooks("whatsapp_core_delivery_status_handlers") or []
	if isinstance(paths, str):
		paths = [paths]
	paths = list(dict.fromkeys(path for path in paths if path))
	for row in updates or []:
		message_name = str(row.get("message_name") or "").strip()
		current = (
			frappe.db.get_value(
				"WhatsApp Core Message", message_name, "delivery_status"
			)
			if message_name
			else None
		)
		if not current:
			continue
		for path in paths:
			frappe.get_attr(path)(
				message_name=message_name,
				delivery_status=current,
			)
