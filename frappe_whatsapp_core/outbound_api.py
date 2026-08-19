"""Stable authenticated API for business apps sending through WhatsApp Core."""

from __future__ import annotations

import frappe

from frappe_whatsapp_core.legacy_compat import (
	queue_template_by_phone,
	queue_text_by_phone,
)
from frappe_whatsapp_core.permissions import require_core_access


@frappe.whitelist(methods=["POST"])
@require_core_access(manage=True)
def send_text(
	phone_number: str,
	body: str,
	channel: str | None = None,
	phone_number_id: str | None = None,
	client_message_id: str | None = None,
) -> dict:
	"""Queue a text message using an international or locally configured number."""
	message = queue_text_by_phone(
		phone_number,
		body,
		channel=channel,
		phone_number_id=phone_number_id,
		source="Core outbound API",
		client_message_id=client_message_id,
	)
	return _queued_response(message)


@frappe.whitelist(methods=["POST"])
@require_core_access(manage=True)
def send_template(
	phone_number: str,
	template: str,
	parameters: list | str | None = None,
	language_code: str = "",
	header_parameters: list | str | None = None,
	channel: str | None = None,
	phone_number_id: str | None = None,
	client_message_id: str | None = None,
) -> dict:
	"""Queue a template by number using simple positional parameter arrays.

	``parameters=["Sakthi", "19/08/2026"]`` supplies ``{{1}}`` and ``{{2}}``
	in the body. ``template`` accepts a Core record, Meta template name, or Meta
	template id. Header values are optional and use the same positional format.
	"""
	body_values = _parameter_list(parameters, "parameters")
	header_values = _parameter_list(header_parameters, "header_parameters")
	variables = {"body": body_values}
	if header_values:
		variables["header"] = header_values
	message = queue_template_by_phone(
		phone_number,
		template,
		language_code=language_code,
		variables=variables,
		channel=channel,
		phone_number_id=phone_number_id,
		source="Core outbound API",
		client_message_id=client_message_id,
	)
	return _queued_response(message)


def _parameter_list(value, fieldname: str) -> list:
	if value in (None, ""):
		return []
	if isinstance(value, str):
		try:
			value = frappe.parse_json(value)
		except (TypeError, ValueError):
			frappe.throw(f"{fieldname} must be a JSON array", frappe.ValidationError)
	if not isinstance(value, list):
		frappe.throw(f"{fieldname} must be an array", frappe.ValidationError)
	return value


def _queued_response(message) -> dict:
	return {
		"status": "queued",
		"message": message.name,
		"conversation": message.conversation,
		"delivery_status": message.delivery_status,
		"provider_message_id": message.provider_message_id,
	}
