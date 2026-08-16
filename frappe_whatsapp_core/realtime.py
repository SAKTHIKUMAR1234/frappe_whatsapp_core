"""Permission-neutral realtime invalidations for the Core web application."""

import frappe


def publish_invalidation(event: str, *, after_commit: bool = True) -> None:
	"""Wake clients without placing protected row data on the site-wide room."""
	frappe.publish_realtime(
		str(event),
		{"changed": True},
		after_commit=after_commit,
	)
