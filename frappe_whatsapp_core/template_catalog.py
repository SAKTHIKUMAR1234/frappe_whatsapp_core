"""Site template projection and secure Integration-owned authoring requests."""

from __future__ import annotations

import json

import frappe
from frappe.utils import now_datetime

from frappe_whatsapp_core.hub_client import call_management
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
		"hub_template_name": payload.get("hub_template_name") or "",
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
	_publish_template(doc)

	return {
		"name": doc.name,
		"status": status,
		"approval_status": doc.approval_status,
		"enabled": bool(doc.enabled),
	}


@frappe.whitelist()
@require_core_access(manage=True)
def request_template_upsert(template=None, template_key=None) -> dict:
	"""Ask Integration to create/edit and submit a template to Meta.

	Core remains a projection: it never receives Meta credentials and never
	mutates an approved template locally. Integration validates tenant ownership,
	submits the request, and pushes every resulting status back to this site.
	"""
	payload = _editable_payload(template)
	existing = None
	if template_key:
		existing = frappe.get_doc("WhatsApp Core Template", str(template_key).strip())
		frappe.has_permission(
			"WhatsApp Core Template",
			"read",
			doc=existing,
			throw=True,
		)
		payload = _merge_existing_template(existing, payload)
	elif not payload.get("template_name"):
		frappe.throw("Template name is required", frappe.ValidationError)

	result = call_management(
		"frappe_whatsapp_integration.frappe_whatsapp_hub.api.templates.upsert_template_for_site",
		{
			"site_name": frappe.local.site,
			"hub_template_name": existing.hub_template_name if existing else None,
			"template": payload,
		},
	)
	remote_template = result.get("template")
	if isinstance(remote_template, dict):
		projection = sync_template_projection(
			remote_template,
			enabled=str(remote_template.get("status") or "").upper() == "APPROVED",
		)
	else:
		projection = None
	if not result.get("success"):
		frappe.throw(
			result.get("error") or "Meta did not accept the template request",
			frappe.ValidationError,
		)
	return {
		"success": True,
		"template": projection,
		"approval_status": (remote_template or {}).get("status") or "IN_REVIEW",
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
	_publish_template(template_key)
	return {
		"name": template_key,
		"enabled": bool(frappe.utils.sbool(enabled)),
	}


def _publish_template(template) -> None:
	name = template if isinstance(template, str) else template.name
	frappe.publish_realtime(
		"whatsapp_core_template",
		{"template": name},
		after_commit=True,
	)


def _template_payload(template) -> dict:
	if isinstance(template, str):
		template = _json_value(template, {})
	if not isinstance(template, dict):
		frappe.throw("Template payload must be an object", frappe.ValidationError)
	return dict(template)


def _editable_payload(template) -> dict:
	payload = _template_payload(template)
	allowed = {
		"template_name",
		"language_code",
		"category",
		"header_type",
		"header_content",
		"body_text",
		"footer_text",
		"message_send_ttl_seconds",
		"buttons",
		"sample_values",
	}
	unknown = sorted(set(payload) - allowed)
	if unknown:
		frappe.throw(
			f"Unsupported template fields: {', '.join(unknown)}",
			frappe.ValidationError,
		)
	for fieldname, maximum in {
		"template_name": 512,
		"language_code": 32,
		"category": 32,
		"header_type": 32,
		"header_content": 1024,
		"body_text": 4096,
		"footer_text": 1024,
	}.items():
		if fieldname in payload and len(str(payload.get(fieldname) or "")) > maximum:
			frappe.throw(f"{fieldname} is too long", frappe.ValidationError)
	for fieldname in ("buttons", "sample_values"):
		if fieldname in payload and isinstance(payload[fieldname], str):
			payload[fieldname] = _json_value(payload[fieldname], None)
		if fieldname in payload and not isinstance(payload[fieldname], list):
			frappe.throw(f"{fieldname} must be a list", frappe.ValidationError)
	return payload


def _merge_existing_template(existing, changes: dict) -> dict:
	components = _json_value(existing.components, [])
	buttons = []
	for component in components:
		if not isinstance(component, dict) or str(component.get("type") or "").upper() != "BUTTONS":
			continue
		for button in component.get("buttons") or []:
			if isinstance(button, dict):
				buttons.append({
					"button_type": button.get("type") or "",
					"button_text": button.get("text") or "",
					"button_url": button.get("url") or "",
					"phone_number": button.get("phone_number") or "",
					"ttl_minutes": button.get("ttl_minutes"),
				})
	base = {
		"template_name": existing.template_name,
		"language_code": existing.language_code,
		"category": existing.category or "UTILITY",
		"header_type": existing.header_type or "",
		"header_content": existing.header_content or "",
		"body_text": existing.body_text or "",
		"footer_text": existing.footer_text or "",
		"buttons": buttons,
	}
	base.update(changes)
	return base


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
