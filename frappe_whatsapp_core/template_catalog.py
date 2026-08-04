"""Read-only Core template catalog fed by the Integration application."""

from __future__ import annotations

import json

import frappe
from frappe.utils import now_datetime

from frappe_whatsapp_core.permissions import require_core_access


@frappe.whitelist()
@require_core_access(manage=True)
def receive_push(template=None, enabled=True, **_kwargs) -> dict:
	"""Receive one assigned template from the Integration site.

	The authenticated Hub API user must hold a Core management role. Template
	creation, Meta submission, editing and site assignment remain owned by the
	Integration application.
	"""
	return sync_template_projection(template, enabled=frappe.utils.sbool(enabled))


def sync_template_projection(template, *, enabled: bool = True) -> dict:
	payload = _template_payload(template)
	template_name = (payload.get("name") or payload.get("template_name") or "").strip()
	language_code = (payload.get("language") or payload.get("language_code") or "en").strip()
	if not template_name:
		frappe.throw("Template name is required", frappe.ValidationError)

	template_key = f"{template_name}-{language_code}"
	values = {
		"template_name": template_name,
		"language_code": language_code,
		"category": payload.get("category") or "",
		"approval_status": (payload.get("status") or "UNKNOWN").upper(),
		"enabled": int(bool(enabled)),
		"template_id": payload.get("id") or payload.get("template_id") or "",
		"header_type": payload.get("header_type") or "",
		"header_content": payload.get("header_content") or "",
		"body_text": payload.get("body_text") or "",
		"footer_text": payload.get("footer_text") or "",
		"components": json.dumps(
			payload.get("components") or _json_value(payload.get("components_json"), []),
			separators=(",", ":"),
			ensure_ascii=False,
		),
		"last_synced_at": now_datetime(),
	}
	_extract_component_copy(values)

	if frappe.db.exists("WhatsApp Core Template", template_key):
		doc = frappe.get_doc("WhatsApp Core Template", template_key)
		doc.update(values)
		doc.save(ignore_permissions=True)
		status = "updated"
	else:
		doc = frappe.get_doc({
			"doctype": "WhatsApp Core Template",
			"template_key": template_key,
			**values,
		}).insert(ignore_permissions=True)
		status = "created"

	return {
		"name": doc.name,
		"status": status,
		"approval_status": doc.approval_status,
		"enabled": bool(doc.enabled),
	}


@frappe.whitelist()
@require_core_access(manage=True)
def set_template_enabled(template_key: str, enabled) -> dict:
	"""Apply an Integration-owned site assignment enable/disable event."""
	if not frappe.db.exists("WhatsApp Core Template", template_key):
		frappe.throw("Assigned template was not found", frappe.DoesNotExistError)
	frappe.db.set_value(
		"WhatsApp Core Template",
		template_key,
		{
			"enabled": int(frappe.utils.sbool(enabled)),
			"last_synced_at": now_datetime(),
		},
	)
	return {
		"name": template_key,
		"enabled": bool(frappe.utils.sbool(enabled)),
	}


def _template_payload(template) -> dict:
	if isinstance(template, str):
		template = _json_value(template, {})
	if not isinstance(template, dict):
		frappe.throw("Template payload must be an object", frappe.ValidationError)
	return dict(template)


def _json_value(value, fallback):
	if value in (None, ""):
		return fallback
	if isinstance(value, (dict, list)):
		return value
	try:
		return json.loads(value)
	except (TypeError, ValueError):
		return fallback


def _extract_component_copy(values: dict) -> None:
	components = _json_value(values.get("components"), [])
	for component in components:
		component_type = (component.get("type") or "").upper()
		if component_type == "HEADER":
			values["header_type"] = component.get("format") or values["header_type"]
			values["header_content"] = component.get("text") or values["header_content"]
		elif component_type == "BODY":
			values["body_text"] = component.get("text") or values["body_text"]
		elif component_type == "FOOTER":
			values["footer_text"] = component.get("text") or values["footer_text"]

