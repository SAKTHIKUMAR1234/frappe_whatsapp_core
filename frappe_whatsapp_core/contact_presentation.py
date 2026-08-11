"""Batch contact presentation with business-app overrides."""

from __future__ import annotations

from copy import deepcopy

import frappe

PRESENTATION_FIELDS = {
	"display_name",
	"secondary_text",
	"reference",
	"entity_type",
	"avatar",
	"badges",
	"metadata",
}


def present_identity_names(identity_names, *, context=None) -> dict[str, dict]:
	"""Load and present identities in one batch to avoid per-row hooks and queries."""
	names = list(dict.fromkeys(name for name in identity_names if name))
	if not names:
		return {}
	identities = frappe.get_all(
		"WhatsApp Core Identity",
		filters={"name": ["in", names]},
		fields=[
			"name",
			"normalized_value",
			"display_value",
			"primary_link",
			"attributes",
		],
		limit_page_length=len(names),
	)
	link_names = [row.primary_link for row in identities if row.primary_link]
	links = {
		row.name: row
		for row in frappe.get_all(
			"WhatsApp Core Identity Link",
			filters={"name": ["in", link_names], "status": "Active"},
			fields=[
				"name",
				"display_name",
				"entity_type",
				"reference_doctype",
				"reference_name",
			],
			limit_page_length=max(1, len(link_names)),
		)
	} if link_names else {}
	return present_contacts(identities, primary_links=links, context=context)


def present_contacts(identity_rows, *, primary_links=None, context=None) -> dict[str, dict]:
	"""Return Core defaults merged with presentation-only business overrides.

	Business applications register ``whatsapp_core_contact_presenters`` hooks.
	Each hook receives the entire presentation mapping and a context dictionary,
	then returns ``{identity_name: {field: value}}``. Batched invocation keeps
	large inboxes free of N+1 application calls.
	"""
	primary_links = primary_links or {}
	presentations = {}
	for row in identity_rows:
		name = row.get("name")
		if not name:
			continue
		link = primary_links.get(row.get("primary_link"))
		display_name = (
			(link.get("display_name") or link.get("reference_name"))
			if link
			else (row.get("display_value") or row.get("normalized_value"))
		)
		presentations[name] = {
			"display_name": display_name or name,
			"secondary_text": row.get("normalized_value") or "",
			"reference": (
				f"{link.get('reference_doctype')} · {link.get('reference_name')}"
				if link
				else "WhatsApp contact"
			),
			"entity_type": link.get("entity_type") if link else "",
			"avatar": "",
			"badges": [],
			"metadata": {},
		}

	for method in _presenter_hooks():
		overrides = frappe.get_attr(method)(
			contacts=deepcopy(presentations),
			context=dict(context or {}),
		)
		if overrides is None:
			continue
		if not isinstance(overrides, dict):
			frappe.throw(
				f"Contact presenter {method} must return an object",
				frappe.ValidationError,
			)
		for identity, values in overrides.items():
			if identity not in presentations or not isinstance(values, dict):
				continue
			presentations[identity].update(
				{key: value for key, value in values.items() if key in PRESENTATION_FIELDS}
			)
	return presentations


def _presenter_hooks() -> list[str]:
	hooks = frappe.get_hooks("whatsapp_core_contact_presenters") or []
	if isinstance(hooks, dict):
		hooks = list(hooks.values())
	result = []
	for hook in hooks:
		if isinstance(hook, (list, tuple)):
			result.extend(str(method) for method in hook if method)
		elif hook:
			result.append(str(hook))
	return result
