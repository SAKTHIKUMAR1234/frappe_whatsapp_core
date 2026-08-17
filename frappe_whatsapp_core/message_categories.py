"""Canonical, reusable categories for AI-understood WhatsApp messages."""

from __future__ import annotations

from collections import Counter
import hashlib

import frappe
from frappe.utils import now_datetime

from frappe_whatsapp_core.naming import name_by_key


DEFAULT_CATEGORIES = {
	"Uncategorized": "No reliable business category has been assigned yet.",
	"Payment proof": "A payment claim, reference, receipt, screenshot, or document awaiting verification.",
	"Complaint": "A product, delivery, billing, service, partner, or salesperson complaint.",
	"Order": "An order request or order-related response.",
	"Catalogue": "A catalogue, product information, price, stock, or scheme request.",
	"Callback": "An explicit request for a call or follow-up.",
	"Feedback": "Feedback, rating, survey response, or product opinion.",
	"Opt-out": "A request to stop or unsubscribe from messages.",
	"Other": "A understood message that does not fit another category.",
}


def ensure_default_categories() -> None:
	"""Create Core defaults and register categories already stored by older builds."""
	if not frappe.db.exists("DocType", "WhatsApp Core Message Category"):
		return
	for category, description in DEFAULT_CATEGORIES.items():
		ensure_message_category(category, source="System", description=description)
	if not frappe.db.exists("DocType", "WhatsApp Core Message Insight"):
		return
	for category in frappe.get_all(
		"WhatsApp Core Message Insight",
		filters={"category": ["is", "set"]},
		pluck="category",
		distinct=True,
		limit_page_length=1000,
	):
		ensure_message_category(category, source="AI")


def ensure_message_category(
	category: str | None,
	*,
	source: str = "AI",
	description: str = "",
) -> str:
	"""Return a valid category Link, creating a missing AI category safely."""
	name = " ".join(str(category or "").strip().split())[:140] or "Uncategorized"
	record_name = name_by_key("WhatsApp Core Message Category", name)
	if record_name:
		return record_name
	if source not in {"System", "AI", "Manager"}:
		source = "AI"
	try:
		doc = frappe.get_doc({
			"doctype": "WhatsApp Core Message Category",
			"category_name": name,
			"description": str(description or "")[:500],
			"source": source,
			"enabled": 1,
		}).insert(ignore_permissions=True)
		return doc.name
	except frappe.UniqueValidationError:
		# Two summary workers can discover the same new category concurrently.
		# The unique category name is authoritative; the losing worker reuses it.
		return name_by_key("WhatsApp Core Message Category", name)


def normalize_message_categories(*values) -> list[str]:
	"""Normalize model/operator category values without losing secondary intents."""
	result = []
	for value in values:
		items = value if isinstance(value, (list, tuple, set)) else [value]
		for item in items:
			name = " ".join(str(item or "").strip().split())[:140]
			if name and name not in result:
				result.append(name)
	return result or ["Uncategorized"]


def set_message_categories(
	message: str,
	conversation: str,
	identity: str,
	categories,
	*,
	source: str = "AI",
	confidence: float = 0,
) -> list[str]:
	"""Replace one message's indexed category set inside the caller transaction."""
	if source not in {"System", "AI", "Manager"}:
		source = "AI"
	names = [ensure_message_category(name, source=source) for name in normalize_message_categories(categories)]
	if not frappe.db.exists("DocType", "WhatsApp Core Message Category Assignment"):
		return names
	frappe.db.delete("WhatsApp Core Message Category Assignment", {"message": message})
	assigned_at = now_datetime()
	for category in names:
		key = hashlib.sha256(f"{message}:{category}".encode()).hexdigest()
		frappe.get_doc({
			"doctype": "WhatsApp Core Message Category Assignment",
			"assignment_key": key,
			"message": message,
			"conversation": conversation,
			"identity": identity,
			"category": category,
			"source": source,
			"confidence": confidence,
			"assigned_at": assigned_at,
		}).insert(ignore_permissions=True)
	return names


def categories_for_messages(message_names: list[str]) -> dict[str, list[str]]:
	names = list(dict.fromkeys(str(name) for name in message_names or [] if name))
	if not names or not frappe.db.exists("DocType", "WhatsApp Core Message Category Assignment"):
		return {}
	rows = frappe.db.sql(
		"""
		SELECT assignment.message, category.category_name AS category
		FROM `tabWhatsApp Core Message Category Assignment` AS assignment
		INNER JOIN `tabWhatsApp Core Message Category` AS category
			ON category.name = assignment.category
		WHERE assignment.message IN %(messages)s
		ORDER BY assignment.assigned_at ASC, category.category_name ASC
		""",
		{"messages": tuple(names)},
		as_dict=True,
	)
	result = {}
	for row in rows:
		result.setdefault(row.message, []).append(row.category)
	return result


def category_counts_for_teams(team_names: list[str]) -> dict[str, list[dict]]:
	"""Aggregate categorized messages for enabled contacts in each team."""
	names = list(dict.fromkeys(name for name in team_names or [] if name))
	if not names:
		return {}
	assignment_table = (
		"`tabWhatsApp Core Message Category Assignment`"
		if frappe.db.exists("DocType", "WhatsApp Core Message Category Assignment")
		else "`tabWhatsApp Core Message Insight`"
	)
	category_field = "assignment.category"
	identity_field = "assignment.identity"
	rows = frappe.db.sql(
		f"""
		SELECT team_contact.parent AS team,
			COALESCE(category.category_name, {category_field}) AS category,
			COUNT(*) AS message_count
		FROM `tabWhatsApp Core Team Contact` AS team_contact
		JOIN {assignment_table} AS assignment
			ON {identity_field} = team_contact.identity
		LEFT JOIN `tabWhatsApp Core Message Category` AS category
			ON category.name = {category_field}
		WHERE team_contact.parenttype = 'WhatsApp Core Team'
			AND team_contact.parentfield = 'contacts'
			AND team_contact.enabled = 1
			AND team_contact.parent IN %(teams)s
		GROUP BY team_contact.parent, COALESCE(category.category_name, {category_field})
		""",
		{"teams": tuple(names)},
		as_dict=True,
	)
	counts: dict[str, Counter] = {name: Counter() for name in names}
	for row in rows:
		counts.setdefault(row.team, Counter())[row.category or "Uncategorized"] += int(
			row.message_count or 0
		)
	return {
		team: [
			{"category": category, "count": count}
			for category, count in sorted(
				category_counts.items(),
				key=lambda item: (-item[1], item[0]),
			)
		]
		for team, category_counts in counts.items()
	}
