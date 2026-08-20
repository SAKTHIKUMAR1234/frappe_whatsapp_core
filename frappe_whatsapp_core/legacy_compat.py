"""Compatibility boundary for apps retiring their private WhatsApp transports.

Business apps may keep their established API method names while this module
normalizes those calls into Core conversations and durable Core messages.  It
never writes a legacy contact, message, campaign, or webhook table.
"""

from __future__ import annotations

import json
from copy import deepcopy
from urllib.parse import urlsplit

import frappe

from frappe_whatsapp_core.identity import normalize_phone
from frappe_whatsapp_core.materializer import (
	get_or_create_conversation,
	get_or_create_identity,
)
from frappe_whatsapp_core.outbound import (
	queue_rich_internal,
	queue_template_internal,
	queue_text_internal,
	upload_media_internal,
)


def resolve_channel(
	*,
	channel: str | None = None,
	phone_number_id: str | None = None,
):
	"""Resolve one enabled Core channel without consulting legacy credentials."""
	if channel:
		channel_doc = frappe.get_doc("WhatsApp Core Channel", channel)
	elif phone_number_id:
		channel_name = frappe.db.get_value(
			"WhatsApp Core Channel",
			{"phone_number_id": str(phone_number_id).strip(), "enabled": 1},
			"name",
		)
		if not channel_name:
			frappe.throw(
				"The legacy WhatsApp account is not mapped to an enabled Core channel",
				frappe.ValidationError,
			)
		channel_doc = frappe.get_doc("WhatsApp Core Channel", channel_name)
	else:
		channels = frappe.get_all(
			"WhatsApp Core Channel",
			filters={"enabled": 1},
			pluck="name",
			limit_page_length=2,
		)
		if not channels:
			frappe.throw("No enabled WhatsApp Core channel is configured", frappe.ValidationError)
		if len(channels) != 1:
			frappe.throw(
				"Multiple Core channels are enabled; map the legacy account explicitly",
				frappe.ValidationError,
			)
		channel_doc = frappe.get_doc("WhatsApp Core Channel", channels[0])
	if not channel_doc.enabled:
		frappe.throw("The selected WhatsApp Core channel is disabled", frappe.ValidationError)
	return channel_doc


def conversation_for_phone(
	phone_number: str,
	*,
	channel: str | None = None,
	phone_number_id: str | None = None,
):
	channel_doc = resolve_channel(channel=channel, phone_number_id=phone_number_id)
	country_code = (
		frappe.db.get_single_value(
			"WhatsApp Core Settings",
			"default_country_calling_code",
		)
		or "91"
	)
	phone = normalize_phone(
		phone_number,
		assume_local=True,
		country_code=country_code,
	)
	if not 7 <= len(phone) <= 15:
		frappe.throw("Enter a valid WhatsApp phone number", frappe.ValidationError)
	# The exact number supplied by the business API is authoritative. Reuse a
	# provider-confirmed phone alias within this channel instead of creating a
	# second global identity or selecting another number linked to the same party.
	identity = get_or_create_identity(
		phone,
		scope=channel_doc.name,
		aliases={"phone": phone},
	)
	conversation = get_or_create_conversation(channel_doc, identity)
	return conversation


def queue_text_by_phone(
	phone_number: str,
	body: str,
	*,
	channel: str | None = None,
	phone_number_id: str | None = None,
	source: str = "Legacy compatibility",
	enqueue_delivery: bool = True,
	client_message_id: str | None = None,
) -> dict:
	conversation = conversation_for_phone(
		phone_number,
		channel=channel,
		phone_number_id=phone_number_id,
	)
	return queue_text_internal(
		conversation.name,
		body,
		source,
		client_message_id=client_message_id,
		enqueue_delivery=enqueue_delivery,
		recipient_override=phone_number,
	)


def queue_template_by_phone(
	phone_number: str,
	template: str,
	*,
	language_code: str = "",
	variables=None,
	document_id: str | None = None,
	document_link: str | None = None,
	document_filename: str | None = None,
	channel: str | None = None,
	phone_number_id: str | None = None,
	source: str = "Legacy compatibility",
	enqueue_delivery: bool = True,
	client_message_id: str | None = None,
) -> dict:
	conversation = conversation_for_phone(
		phone_number,
		channel=channel,
		phone_number_id=phone_number_id,
	)
	components = legacy_template_components(variables)
	local_file_url = _local_file_url(document_link)
	if not document_id and local_file_url:
		uploaded = upload_media_internal(conversation.name, local_file_url, "document")
		document_id = uploaded["media_id"]
	if document_id or document_link:
		document = {"id": str(document_id)} if document_id else {"link": str(document_link)}
		if document_filename:
			document["filename"] = str(document_filename)
		_replace_component(
			components,
			"header",
			{"type": "document", "document": document},
		)
	message = queue_template_internal(
		conversation.name,
		template,
		language_code,
		components,
		source,
		client_message_id=client_message_id,
		local_file_url=local_file_url,
		enqueue_delivery=enqueue_delivery,
		recipient_override=phone_number,
	)
	return message


def queue_media_by_phone(
	phone_number: str,
	media_type: str,
	*,
	media_id: str | None = None,
	media_url: str | None = None,
	caption: str | None = None,
	filename: str | None = None,
	channel: str | None = None,
	phone_number_id: str | None = None,
	source: str = "Legacy compatibility",
	enqueue_delivery: bool = True,
) -> dict:
	conversation = conversation_for_phone(
		phone_number,
		channel=channel,
		phone_number_id=phone_number_id,
	)
	local_file_url = _local_file_url(media_url)
	if not media_id and local_file_url:
		uploaded = upload_media_internal(conversation.name, local_file_url, media_type)
		media_id = uploaded["media_id"]
	if media_id:
		payload = {"id": str(media_id)}
	elif media_url:
		payload = {"link": str(media_url)}
	else:
		frappe.throw("Media requires an uploaded media id or URL", frappe.ValidationError)
	if caption and str(media_type).lower() != "audio":
		payload["caption"] = str(caption)
	if filename and str(media_type).lower() == "document":
		payload["filename"] = str(filename)
	return queue_rich_internal(
		conversation.name,
		media_type,
		payload,
		caption or "",
		source,
		local_file_url=local_file_url,
		enqueue_delivery=enqueue_delivery,
		recipient_override=phone_number,
	)


def queue_interactive_by_phone(
	phone_number: str,
	interactive_type: str,
	body_text: str,
	*,
	buttons=None,
	list_sections=None,
	list_button_text: str = "View Options",
	header_text: str | None = None,
	footer_text: str | None = None,
	channel: str | None = None,
	phone_number_id: str | None = None,
	source: str = "Legacy compatibility",
	enqueue_delivery: bool = True,
) -> dict:
	conversation = conversation_for_phone(
		phone_number,
		channel=channel,
		phone_number_id=phone_number_id,
	)
	interactive_type = str(interactive_type or "").strip().lower()
	payload = {"type": interactive_type, "body": {"text": str(body_text or "")}}
	if header_text:
		payload["header"] = {"type": "text", "text": str(header_text)}
	if footer_text:
		payload["footer"] = {"text": str(footer_text)}
	if interactive_type == "button":
		items = _json_value(buttons, [])
		payload["action"] = {
			"buttons": [
				{
					"type": "reply",
					"reply": {
						"id": str(item.get("id") or item.get("title") or "")[:256],
						"title": str(item.get("title") or "")[:20],
					},
				}
				for item in items
				if isinstance(item, dict) and item.get("title")
			],
		}
	elif interactive_type == "list":
		payload["action"] = {
			"button": str(list_button_text or "View Options")[:20],
			"sections": _json_value(list_sections, []),
		}
	else:
		frappe.throw("Legacy interactive type must be button or list", frappe.ValidationError)
	return queue_rich_internal(
		conversation.name,
		"interactive",
		payload,
		body_text,
		source,
		enqueue_delivery=enqueue_delivery,
		recipient_override=phone_number,
	)


def legacy_template_components(variables) -> list[dict]:
	variables = _json_value(variables, {})
	if isinstance(variables, list):
		if all(isinstance(row, dict) and row.get("type") for row in variables):
			return deepcopy(variables)
		variables = {"body": variables}
	if not isinstance(variables, dict):
		frappe.throw("Template variables must be an object or list", frappe.ValidationError)
	if isinstance(variables.get("components"), list):
		return deepcopy(variables["components"])
	components = []
	for component_type in ("header", "body"):
		values = variables.get(component_type) or []
		if not isinstance(values, list):
			values = [values]
		if values:
			components.append(
				{
					"type": component_type,
					"parameters": [_template_parameter(value) for value in values],
				}
			)
	return components


def _template_parameter(value) -> dict:
	if isinstance(value, dict) and value.get("type"):
		return deepcopy(value)
	return {"type": "text", "text": str(value if value is not None else "")}


def _replace_component(components: list[dict], component_type: str, parameter: dict) -> None:
	components[:] = [
		component for component in components if str(component.get("type") or "").lower() != component_type
	]
	components.insert(0, {"type": component_type, "parameters": [parameter]})


def _json_value(value, default):
	if isinstance(value, str):
		try:
			return json.loads(value) if value else default
		except (TypeError, ValueError):
			frappe.throw("Invalid JSON payload", frappe.ValidationError)
	return value if value is not None else default


def _local_file_url(value: str | None) -> str | None:
	if not value:
		return None
	path = urlsplit(str(value)).path or str(value)
	if path.startswith(("/private/files/", "/files/")) and frappe.db.exists("File", {"file_url": path}):
		return path
	return None
