"""Site template projection and secure Integration-owned authoring requests."""

from __future__ import annotations

import hashlib
import json
import re

import frappe
from frappe.utils import now_datetime

from frappe_whatsapp_core.hub_client import call_management
from frappe_whatsapp_core.naming import name_by_key, resolve_name
from frappe_whatsapp_core.permissions import require_core_access, require_transport_access
from frappe_whatsapp_core.realtime import publish_invalidation


@frappe.whitelist()
@require_transport_access(capability="template")
def receive_push(template=None, enabled=True, **_kwargs) -> dict:
	"""Receive one assigned template from the Integration site.

	The authenticated Hub API user must hold the dedicated transport role. Template
	creation, Meta submission, editing and site assignment remain owned by the
	Integration application.
	"""
	payload = _template_payload(template)
	_assert_template_account_access(payload.get("account_name"))
	return sync_template_projection(payload, enabled=frappe.utils.sbool(enabled))


def sync_template_projection(template, *, enabled: bool = True) -> dict:
	payload = _template_payload(template)
	component_document = payload.get("components")
	if component_document is None and "components_json" in payload:
		component_document = _json_value(payload.get("components_json"), None)
	if component_document is not None:
		_validate_editable_components(component_document)
	account_name = str(payload.get("account_name") or "").strip()
	template_name = (payload.get("name") or payload.get("template_name") or "").strip()
	language_code = (payload.get("language") or payload.get("language_code") or "en").strip()
	if not account_name:
		frappe.throw("Hub account is required", frappe.ValidationError)
	if not template_name:
		frappe.throw("Template name is required", frappe.ValidationError)

	channel = _account_channel(account_name)
	template_key = scoped_template_key(account_name, template_name, language_code)
	values = {
		"account_name": account_name,
		"channel": channel,
		"template_name": template_name,
		"language_code": language_code,
		"category": payload.get("category") or "",
		"approval_status": (payload.get("status") or "UNKNOWN").upper(),
		"status_reason": (
			payload.get("rejected_reason")
			or payload.get("rejection_reason")
			or payload.get("status_reason")
			or ""
		),
		"correct_category": payload.get("correct_category") or "",
		"enabled": int(bool(enabled)),
		"template_id": payload.get("id") or payload.get("template_id") or "",
		"hub_template_name": payload.get("hub_template_name") or "",
		"message_send_ttl_seconds": _optional_positive_int(
			payload.get("message_send_ttl_seconds"),
			"message_send_ttl_seconds",
		),
		"parameter_format": payload.get("parameter_format") or "",
		"template_source": payload.get("source") or payload.get("template_source") or "",
		"header_type": payload.get("header_type") or "",
		"header_content": payload.get("header_content") or "",
		"body_text": payload.get("body_text") or "",
		"footer_text": payload.get("footer_text") or "",
		"components": json.dumps(
			component_document or [],
			separators=(",", ":"),
			ensure_ascii=False,
		),
		"last_synced_at": now_datetime(),
	}
	_extract_component_copy(values)

	record_name = name_by_key("WhatsApp Core Template", template_key)
	if record_name:
		doc = frappe.get_doc("WhatsApp Core Template", record_name)
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
		"account_name": doc.account_name,
		"channel": doc.channel,
	}


@frappe.whitelist()
@require_core_access(manage=True)
def request_template_upsert(template=None, template_key=None, submit=True) -> dict:
	"""Ask Integration to create/edit and submit a template to Meta.

	Core remains a projection: it never receives Meta credentials and never
	mutates an approved template locally. Integration validates tenant ownership,
	submits the request, and pushes every resulting status back to this site.
	"""
	payload = _editable_payload(template)
	submit = bool(frappe.utils.sbool(submit))
	existing = None
	if template_key:
		record_name = resolve_name("WhatsApp Core Template", template_key)
		if not record_name:
			frappe.throw("Template was not found", frappe.DoesNotExistError)
		existing = frappe.get_doc("WhatsApp Core Template", record_name)
		frappe.has_permission(
			"WhatsApp Core Template",
			"read",
			doc=existing,
			throw=True,
		)
		payload = _merge_existing_template(existing, payload)
	elif not payload.get("template_name"):
		frappe.throw("Template name is required", frappe.ValidationError)
	if not payload.get("account_name"):
		frappe.throw("Hub account is required", frappe.ValidationError)
	# Fail before the authenticated Hub call if a caller names an account that is
	# not mapped to exactly one channel on this Core site.
	_account_channel(payload["account_name"])

	result = call_management(
		"frappe_whatsapp_hub.frappe_whatsapp_hub.api.templates.upsert_template_for_site",
		{
			"site_name": frappe.local.site,
			"hub_template_name": existing.hub_template_name if existing else None,
			"template": payload,
			"submit": submit,
		},
	)
	remote_template = result.get("template")
	if isinstance(remote_template, dict):
		remote_template.setdefault("account_name", payload["account_name"])
		projection = sync_template_projection(
			remote_template,
			enabled=str(remote_template.get("status") or "").upper() == "APPROVED",
		)
	else:
		projection = None
	if not result.get("success") and not projection:
		frappe.throw(
			result.get("error") or "Meta did not accept the template request",
			frappe.ValidationError,
		)
	return {
		"success": bool(result.get("success")),
		"error": result.get("error") or "",
		"action": "submitted" if submit else "saved_draft",
		"template": projection,
		"synced_sites": result.get("synced_sites") or [],
		"approval_status": (remote_template or {}).get("status") or (
			"IN_REVIEW" if submit else "DRAFT"
		),
	}


@frappe.whitelist()
@require_core_access(manage=True)
def get_template(template_key: str) -> dict:
	"""Return one exact site-scoped template projection for API/UI/MCP readback."""
	record_name = resolve_name("WhatsApp Core Template", template_key)
	if not record_name:
		frappe.throw("Template was not found", frappe.DoesNotExistError)
	doc = frappe.get_doc("WhatsApp Core Template", record_name)
	frappe.has_permission("WhatsApp Core Template", "read", doc=doc, throw=True)
	return _template_readback(doc)


@frappe.whitelist()
@require_core_access(manage=True)
def submit_template(template_key: str) -> dict:
	"""Submit an existing Hub draft using its complete projected component document."""
	return request_template_upsert(template={}, template_key=template_key, submit=True)


@frappe.whitelist()
@require_transport_access(capability="template")
def set_template_enabled(template_key: str, enabled) -> dict:
	"""Apply an Integration-owned site assignment enable/disable event."""
	record_name = resolve_name("WhatsApp Core Template", template_key)
	if not record_name:
		frappe.throw("Assigned template was not found", frappe.DoesNotExistError)
	_assert_template_account_access(
		frappe.db.get_value("WhatsApp Core Template", record_name, "account_name")
	)
	frappe.db.set_value(
		"WhatsApp Core Template",
		record_name,
		{
			"enabled": int(frappe.utils.sbool(enabled)),
			"last_synced_at": now_datetime(),
		},
	)
	_publish_template(record_name)
	return {
		"name": record_name,
		"enabled": bool(frappe.utils.sbool(enabled)),
	}


def _publish_template(template) -> None:
	publish_invalidation("whatsapp_core_template")


def _template_payload(template) -> dict:
	if isinstance(template, str):
		template = _json_value(template, {})
	if not isinstance(template, dict):
		frappe.throw("Template payload must be an object", frappe.ValidationError)
	return dict(template)


def _editable_payload(template) -> dict:
	payload = _template_payload(template)
	allowed = {
		"account_name",
		"template_name",
		"language_code",
		"category",
		"header_type",
		"header_content",
		"body_text",
		"footer_text",
		"message_send_ttl_seconds",
		"parameter_format",
		"buttons",
		"sample_values",
		"components",
	}
	unknown = sorted(set(payload) - allowed)
	if unknown:
		frappe.throw(
			f"Unsupported template fields: {', '.join(unknown)}",
			frappe.ValidationError,
		)
	for fieldname, maximum in {
		"account_name": 140,
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
	for fieldname in ("buttons", "sample_values", "components"):
		if fieldname in payload and isinstance(payload[fieldname], str):
			payload[fieldname] = _json_value(payload[fieldname], None)
		if fieldname in payload and not isinstance(payload[fieldname], list):
			frappe.throw(f"{fieldname} must be a list", frappe.ValidationError)
	if "components" in payload:
		_validate_editable_components(payload["components"])
	if "template_name" in payload:
		name = str(payload.get("template_name") or "").strip()
		if not re.fullmatch(r"[a-z0-9_]{1,512}", name):
			frappe.throw(
				"template_name must use lowercase letters, numbers, and underscores",
				frappe.ValidationError,
			)
		payload["template_name"] = name
	if "language_code" in payload:
		language_code = str(payload.get("language_code") or "").strip()
		if not language_code or not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", language_code):
			frappe.throw("language_code is invalid", frappe.ValidationError)
		payload["language_code"] = language_code
	if "category" in payload:
		category = str(payload.get("category") or "").strip().upper()
		if category not in {"MARKETING", "UTILITY", "AUTHENTICATION"}:
			frappe.throw("category is invalid", frappe.ValidationError)
		payload["category"] = category
	if "parameter_format" in payload:
		parameter_format = str(payload.get("parameter_format") or "POSITIONAL").strip().upper()
		if parameter_format not in {"POSITIONAL", "NAMED"}:
			frappe.throw("parameter_format is invalid", frappe.ValidationError)
		payload["parameter_format"] = parameter_format
	if "message_send_ttl_seconds" in payload:
		payload["message_send_ttl_seconds"] = _optional_positive_int(
			payload.get("message_send_ttl_seconds"),
			"message_send_ttl_seconds",
		)
	return payload


def _validate_editable_components(components) -> None:
	if not components:
		frappe.throw("components must be a non-empty list", frappe.ValidationError)
	if len(components) > 100:
		frappe.throw("components exceeds the 100 component safety limit", frappe.ValidationError)
	try:
		encoded = json.dumps(components, separators=(",", ":"), ensure_ascii=False)
	except (TypeError, ValueError):
		frappe.throw("components must be JSON serializable", frappe.ValidationError)
	if len(encoded.encode("utf-8")) > 131072:
		frappe.throw("components exceeds the 128 KiB safety limit", frappe.ValidationError)
	nodes = 0

	def visit(item, depth=0):
		nonlocal nodes
		nodes += 1
		if nodes > 10000 or depth > 12:
			frappe.throw("components JSON is too deeply nested", frappe.ValidationError)
		if isinstance(item, dict):
			for key, child in item.items():
				if not isinstance(key, str) or len(key) > 128:
					frappe.throw("components contains an invalid object key", frappe.ValidationError)
				visit(child, depth + 1)
		elif isinstance(item, list):
			for child in item:
				visit(child, depth + 1)
		elif not isinstance(item, (str, int, float, bool, type(None))):
			frappe.throw("components contains a non-JSON value", frappe.ValidationError)

	for component in components:
		if not isinstance(component, dict):
			frappe.throw("Every template component must be an object", frappe.ValidationError)
		component_type = str(component.get("type") or "").strip().upper()
		if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", component_type):
			frappe.throw("Every template component requires a valid type", frappe.ValidationError)
		component["type"] = component_type
		visit(component)
	if not any(
		str(component.get("type") or "").strip().upper() == "BODY"
		for component in components
	):
		frappe.throw("A BODY template component is required", frappe.ValidationError)


def _merge_existing_template(existing, changes: dict) -> dict:
	components = _json_value(existing.components, [])
	for fieldname, current in {
		"account_name": existing.account_name,
		"template_name": existing.template_name,
		"language_code": existing.language_code,
	}.items():
		if fieldname in changes and str(changes.get(fieldname) or "").strip() != str(current or "").strip():
			frappe.throw(
				f"{fieldname} cannot be changed after template creation",
				frappe.ValidationError,
			)
	advanced_components = _components_require_raw_editor(components)
	content_fields = {
		"header_type",
		"header_content",
		"body_text",
		"footer_text",
		"buttons",
		"sample_values",
	}
	if advanced_components and "components" not in changes:
		flattened_changes = content_fields.intersection(changes)
		if flattened_changes:
			frappe.throw(
				"Advanced template content must be edited through components JSON",
				frappe.ValidationError,
			)
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
		"account_name": existing.account_name,
		"template_name": existing.template_name,
		"language_code": existing.language_code,
		"category": existing.category or "UTILITY",
		"header_type": existing.header_type or "",
		"header_content": existing.header_content or "",
		"body_text": existing.body_text or "",
		"footer_text": existing.footer_text or "",
		"buttons": buttons,
		"message_send_ttl_seconds": getattr(
			existing, "message_send_ttl_seconds", None
		),
		"parameter_format": getattr(existing, "parameter_format", None) or "POSITIONAL",
	}
	if components and not content_fields.intersection(changes):
		# Category/TTL-only edits must not silently flatten authentication, Flow,
		# catalog, examples, or future Meta component fields.
		base["components"] = components
	base.update(changes)
	base["account_name"] = existing.account_name
	return base


def _template_readback(doc) -> dict:
	components = _json_value(doc.components, None)
	if components is None:
		frappe.throw(
			"Stored template components contain invalid JSON; resync before editing",
			frappe.ValidationError,
		)
	_validate_editable_components(components)
	return {
		"name": doc.name,
		"account_name": doc.account_name,
		"channel": doc.channel,
		"template_name": doc.template_name,
		"language_code": doc.language_code,
		"category": doc.category,
		"approval_status": doc.approval_status,
		"status_reason": doc.status_reason or "",
		"correct_category": doc.correct_category or "",
		"enabled": bool(doc.enabled),
		"hub_template_name": doc.hub_template_name or "",
		"template_id": doc.template_id or "",
		"message_send_ttl_seconds": doc.message_send_ttl_seconds or None,
		"parameter_format": doc.parameter_format or "",
		"template_source": doc.template_source or "",
		"components": components,
		"last_synced_at": doc.last_synced_at,
	}


def _optional_positive_int(value, fieldname: str):
	if value in (None, "", 0, "0"):
		return None
	try:
		value = int(value)
	except (TypeError, ValueError):
		frappe.throw(f"{fieldname} must be a positive integer", frappe.ValidationError)
	if value <= 0:
		frappe.throw(f"{fieldname} must be a positive integer", frappe.ValidationError)
	return value


def _components_require_raw_editor(components) -> bool:
	"""Return whether the stored Meta shape is lossy in the basic editor."""
	for component in components:
		if not isinstance(component, dict):
			return True
		component_type = str(component.get("type") or "").upper()
		allowed_component_keys = {
			"HEADER": {"type", "format", "text", "example"},
			"BODY": {"type", "text", "example"},
			"FOOTER": {"type", "text"},
			"BUTTONS": {"type", "buttons"},
		}.get(component_type)
		if not allowed_component_keys or set(component) - allowed_component_keys:
			return True
		if component_type == "BUTTONS":
			for button in component.get("buttons") or []:
				if not isinstance(button, dict):
					return True
				if set(button) - {"type", "text", "url", "phone_number", "ttl_minutes"}:
					return True
	return False


def scoped_template_key(account_name: str, template_name: str, language_code: str) -> str:
	"""Return a bounded, stable identity for one account's Meta template."""
	account_name = str(account_name or "").strip()
	template_name = str(template_name or "").strip()
	language_code = str(language_code or "en").strip()
	digest = hashlib.sha256(
		f"{account_name}\0{template_name}\0{language_code}".encode()
	).hexdigest()[:20]
	return f"{template_name[:80]}-{language_code[:20]}-{digest}"


def _account_channel(account_name: str) -> str:
	settings = frappe.get_single("WhatsApp Core Settings")
	channels = [
		str(row.channel).strip()
		for row in settings.accounts
		if str(row.account_name or "").strip() == account_name and row.channel
	]
	channels = list(dict.fromkeys(channels))
	if len(channels) != 1:
		frappe.throw(
			f"Hub account {account_name} must map to exactly one Core channel",
			frappe.ValidationError,
		)
	return channels[0]


def _assert_template_account_access(account_name: str) -> None:
	"""Bind every Integration template callback to one configured Hub account."""
	account_name = str(account_name or "").strip()
	if not account_name:
		frappe.throw("Hub account is required", frappe.ValidationError)
	# Administrator is the local recovery principal. WhatsApp Manager is the
	# documented unified transport identity and may project templates for every
	# account mapped on this Core site. Dedicated template-service identities stay
	# account-bound below so one machine credential cannot cross tenants.
	if (
		frappe.session.user == "Administrator"
		or "WhatsApp Manager" in set(frappe.get_roles(frappe.session.user))
	):
		_account_channel(account_name)
		return
	bound = frappe.db.exists(
		"WhatsApp Core Hub Account",
		{
			"parent": "WhatsApp Core Settings",
			"parenttype": "WhatsApp Core Settings",
			"parentfield": "accounts",
			"account_name": account_name,
			"template_service_user": frappe.session.user,
		},
	)
	if not bound:
		frappe.throw(
			"This Core Template Service identity is not bound to the requested Hub account",
			frappe.PermissionError,
		)


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
