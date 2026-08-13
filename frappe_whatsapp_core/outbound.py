"""Core-owned optimistic outbound messages and crash-safe Hub submission."""

from __future__ import annotations

import hashlib
import json
import mimetypes
import re
import uuid
from base64 import b64encode
from copy import deepcopy

import frappe
from frappe.utils import add_to_date, now_datetime

from frappe_whatsapp_core.hub_client import (
	call_management,
	connection_status,
	get_settings,
	send_raw,
)
from frappe_whatsapp_core.hub_client import (
	send_batch as send_hub_batch,
)
from frappe_whatsapp_core.identity import phone_candidates
from frappe_whatsapp_core.materializer import (
	get_or_create_conversation,
	get_or_create_identity,
	normalize_phone,
)
from frappe_whatsapp_core.permissions import assert_conversation_access, require_core_access


def outbound_ready() -> bool:
	status = connection_status()
	return bool(
		status["enabled"]
		and status["outbound_enabled"]
		and status["credentials_configured"]
		and status["account_count"]
	)


def resolve_recipient_phone(identity, context: dict | None = None) -> str:
	"""Resolve the delivery number, falling back to the Core Identity value."""
	if isinstance(identity, str):
		identity = frappe.get_cached_doc("WhatsApp Core Identity", identity)
	if getattr(identity, "status", "Active") != "Active":
		frappe.throw(
			"This WhatsApp contact is blocked from outbound messaging",
			frappe.ValidationError,
		)
	paths = frappe.get_hooks("whatsapp_core_recipient_phone_resolver") or []
	if isinstance(paths, str):
		paths = [paths]
	paths = list(dict.fromkeys(paths))
	if len(paths) > 1:
		frappe.throw(
			"At most one WhatsApp recipient phone resolver may be configured",
			frappe.ValidationError,
		)

	value = identity.normalized_value
	if paths:
		resolved = frappe.get_attr(paths[0])(
			identity=identity,
			context=context or {},
		)
		if isinstance(resolved, dict):
			resolved = resolved.get("phone_number")
		if resolved:
			value = resolved
	else:
		value = _linked_recipient_phone(identity, context or {}) or value

	default_country_code = str(
		(context or {}).get("default_country_calling_code")
		or frappe.conf.get("whatsapp_default_country_calling_code")
		or "91"
	)
	phone = normalize_phone(
		value,
		assume_local=True,
		country_code=default_country_code,
	)
	if not 7 <= len(phone) <= 15:
		frappe.throw(
			"The resolved WhatsApp recipient phone number is invalid",
			frappe.ValidationError,
		)
	return phone


def _linked_recipient_phone(identity, context: dict) -> str | None:
	"""Resolve a linked business document through an adapter or its configured field."""
	link_name = getattr(identity, "primary_link", None)
	if not link_name:
		return None
	link = frappe.get_cached_doc("WhatsApp Core Identity Link", link_name)
	if link.status != "Active":
		return None
	if not frappe.db.exists(link.reference_doctype, link.reference_name):
		frappe.throw(
			f"Linked WhatsApp contact {link.reference_doctype} {link.reference_name} no longer exists",
			frappe.ValidationError,
		)
	source = frappe.get_cached_doc("WhatsApp Core Identity Source", link.identity_source)
	document = frappe.get_cached_doc(link.reference_doctype, link.reference_name)
	resolver = _contact_phone_resolver(source.source_key)
	if resolver:
		resolved = frappe.get_attr(resolver)(
			identity=identity,
			link=link,
			source=source,
			document=document,
			context=context,
		)
		if isinstance(resolved, dict):
			resolved = resolved.get("phone_number")
		if resolved:
			return str(resolved)

	for method_name in ("get_whatsapp_contact_number", "get_contact_number"):
		method = getattr(document, method_name, None)
		if callable(method):
			resolved = method(context=context)
			if isinstance(resolved, dict):
				resolved = resolved.get("phone_number")
			if resolved:
				return str(resolved)

	value = _mapped_phone_value(document, source.phone_field, identity.normalized_value)
	if value:
		return str(value)
	frappe.throw(
		f"{link.reference_doctype} is not usable as a WhatsApp contact because "
		f"{source.phone_field or 'a phone field'} has no value. Configure the contact source "
		"or register a whatsapp_core_contact_phone_resolvers hook.",
		frappe.ValidationError,
	)


def _contact_phone_resolver(source_key: str) -> str | None:
	hooks = frappe.get_hooks("whatsapp_core_contact_phone_resolvers") or {}
	if not isinstance(hooks, dict):
		return None
	paths = hooks.get(source_key) or []
	if isinstance(paths, str):
		paths = [paths]
	paths = list(dict.fromkeys(paths))
	if len(paths) > 1:
		frappe.throw(
			f"Multiple contact phone resolvers are registered for {source_key}",
			frappe.ValidationError,
		)
	return paths[0] if paths else None


def _mapped_phone_value(document, phone_field: str, identity_value: str) -> str | None:
	path = str(phone_field or "").strip()
	if not path:
		return None
	if "." not in path:
		return document.get(path)
	table_field, child_field = path.split(".", 1)
	values = [row.get(child_field) for row in (document.get(table_field) or []) if row.get(child_field)]
	if not values:
		return None
	candidates = set(phone_candidates(identity_value))
	for value in values:
		if candidates.intersection(phone_candidates(value)):
			return value
	return values[0]


def outbound_state(conversation: str | None = None) -> dict:
	status = connection_status()
	reasons = []
	if not status["enabled"]:
		reasons.append("WhatsApp Core is disabled")
	if not status["outbound_enabled"]:
		reasons.append("Outbound messaging is disabled")
	if not status["credentials_configured"]:
		reasons.append("Hub credentials are not configured")
	if not status["account_count"]:
		reasons.append("No Hub account is mapped")
	context = {
		"conversation": conversation,
		"message_type": "text",
		"content": {},
	}
	for path in frappe.get_hooks("whatsapp_core_outbound_preflight"):
		result = frappe.get_attr(path)(context)
		if result is False:
			reasons.append("Business outbound preflight failed")
		elif isinstance(result, dict) and not result.get("ready", False):
			reasons.extend(
				result.get("reasons")
				or ["Business outbound preflight failed"]
			)
	text_allowed = (
		_within_service_window(conversation)
		if conversation
		else False
	)
	return {
		**status,
		"ready": not reasons,
		"text_allowed": text_allowed,
		"text_ready": not reasons and text_allowed,
		"reasons": reasons,
	}


@frappe.whitelist()
@require_core_access(manage=True)
def start_conversation(
	channel: str,
	phone_number: str | None = None,
	display_name: str = "",
	identity: str | None = None,
) -> dict:
	channel_doc = frappe.get_doc("WhatsApp Core Channel", channel)
	if not channel_doc.enabled:
		frappe.throw("The selected WhatsApp channel is disabled")
	if identity:
		identity_doc = frappe.get_doc("WhatsApp Core Identity", identity)
		if identity_doc.identity_type != "WhatsApp" or identity_doc.status != "Active":
			frappe.throw("Select an active WhatsApp Core contact", frappe.ValidationError)
		resolved_phone = resolve_recipient_phone(
			identity_doc,
			context={"operation": "start_conversation"},
		)
	else:
		default_country_code = (
			frappe.db.get_single_value(
				"WhatsApp Core Settings",
				"default_country_calling_code",
			)
			or "91"
		)
		normalized = normalize_phone(
			phone_number,
			assume_local=True,
			country_code=default_country_code,
		)
		if not 7 <= len(normalized) <= 15:
			frappe.throw("Enter a valid international phone number")
		identity_doc = get_or_create_identity(normalized)
		resolved_phone = identity_doc.normalized_value
		if display_name and identity_doc.display_value in {"", identity_doc.normalized_value}:
			identity_doc.display_value = display_name.strip()[:140]
			identity_doc.save(ignore_permissions=True)
	conversation = get_or_create_conversation(channel_doc, identity_doc)
	return {
		"conversation": conversation.name,
		"identity": identity_doc.name,
		"phone_number": resolved_phone,
	}


@frappe.whitelist()
@require_core_access()
def queue_text(
	conversation_name: str,
	body: str,
	source: str = "Core UI",
	context_message_id: str | None = None,
	client_message_id: str | None = None,
) -> dict:
	return queue_text_internal(
		conversation_name,
		body,
		source,
		context_message_id=context_message_id,
		client_message_id=client_message_id,
	)


def queue_text_internal(
	conversation_name: str,
	body: str,
	source: str = "Core",
	*,
	context_message_id: str | None = None,
	client_message_id: str | None = None,
	enqueue_delivery: bool = True,
	_batch_context: dict | None = None,
) -> dict:
	body = str(body or "").strip()
	if not body:
		frappe.throw("Message cannot be empty")
	if len(body) > 4096:
		frappe.throw("Message cannot exceed 4096 characters")
	return _queue_message(
		conversation_name,
		"text",
		body,
		{
			"body": body,
			"source": source,
			"context_message_id": _provider_context_id(context_message_id),
		},
		client_message_id=client_message_id,
		enqueue_delivery=enqueue_delivery,
		_batch_context=_batch_context,
	)


@frappe.whitelist()
@require_core_access()
def queue_rich(
	conversation_name: str,
	message_type: str,
	payload: dict | str,
	body: str = "",
	source: str = "Core UI",
	client_message_id: str | None = None,
	local_file_url: str | None = None,
) -> dict:
	return queue_rich_internal(
		conversation_name,
		message_type,
		payload,
		body,
		source,
		client_message_id=client_message_id,
		local_file_url=local_file_url,
	)


def queue_rich_internal(
	conversation_name: str,
	message_type: str,
	payload: dict | str,
	body: str = "",
	source: str = "Core",
	*,
	client_message_id: str | None = None,
	local_file_url: str | None = None,
	enqueue_delivery: bool = True,
) -> dict:
	"""Queue a supported native Cloud API message without exposing its recipient.

	The caller supplies only the type-specific object (for example ``image`` or
	``location``). Core resolves the mapped account and destination at delivery
	time and rejects transport-level fields such as ``to``.
	"""
	message_type = str(message_type or "").strip().lower()
	if isinstance(payload, str):
		payload = frappe.parse_json(payload)
	if not isinstance(payload, dict):
		frappe.throw("Rich message payload must be an object", frappe.ValidationError)
	normalized = _validate_rich_payload(message_type, payload)
	local_file = _local_media_file(local_file_url, message_type) if local_file_url else None
	if local_file:
		normalized["local_file_url"] = local_file.file_url
	preview = str(body or _rich_message_body(message_type, normalized)).strip()[:4096]
	message = _queue_message(
		conversation_name,
		message_type,
		preview,
		{"payload": normalized, "source": source},
		client_message_id=client_message_id,
		enqueue_delivery=enqueue_delivery,
	)
	if local_file:
		local_file.attached_to_doctype = "WhatsApp Core Message"
		local_file.attached_to_name = message.name
		local_file.attached_to_field = None
		local_file.save(ignore_permissions=True)
	return message


@frappe.whitelist()
@require_core_access()
def upload_media(conversation_name: str, file_url: str, media_type: str | None = None) -> dict:
	return upload_media_internal(conversation_name, file_url, media_type)


def upload_media_internal(
	conversation_name: str,
	file_url: str,
	media_type: str | None = None,
) -> dict:
	"""Upload a private Core file to the mapped Meta account and return its ID."""
	assert_conversation_access(conversation_name)
	conversation = frappe.get_doc("WhatsApp Core Conversation", conversation_name)
	frappe.has_permission(
		"WhatsApp Core Conversation",
		"read",
		doc=conversation,
		throw=True,
	)
	file_name = frappe.db.get_value("File", {"file_url": file_url}, "name")
	if not file_name:
		frappe.throw("Uploaded file not found", frappe.DoesNotExistError)
	file_doc = frappe.get_doc("File", file_name)
	frappe.has_permission("File", "read", doc=file_doc, throw=True)
	content = file_doc.get_content()
	if isinstance(content, str):
		content = content.encode()
	media_type = str(media_type or "document").strip().lower()
	max_bytes = {
		"image": 5 * 1024 * 1024,
		"video": 16 * 1024 * 1024,
		"audio": 16 * 1024 * 1024,
		"document": 100 * 1024 * 1024,
		"sticker": 500 * 1024,
	}.get(media_type)
	if not max_bytes:
		frappe.throw("Unsupported media type", frappe.ValidationError)
	if len(content) > max_bytes:
		frappe.throw(
			f"{media_type.title()} exceeds WhatsApp's upload limit",
			frappe.ValidationError,
		)
	settings = get_settings(outbound=True)
	result = call_management(
		"frappe_whatsapp_integration.frappe_whatsapp_hub.api.media.upload_media",
		{
			"account_name": settings.get_account_name(conversation.channel),
			"file_content_b64": b64encode(content).decode(),
			"content_type": (
				mimetypes.guess_type(file_doc.file_name or "")[0]
				or "application/octet-stream"
			),
			"filename": file_doc.file_name or "file",
		},
	)
	if not result.get("success") or not result.get("media_id"):
		frappe.throw(result.get("error") or "Meta media upload failed")
	return {
		"media_id": result["media_id"],
		"file_url": file_doc.file_url,
		"filename": file_doc.file_name,
		"content_type": mimetypes.guess_type(file_doc.file_name or "")[0],
	}


@frappe.whitelist()
@require_core_access()
def queue_template(
	conversation_name: str,
	template: str,
	language_code: str = "",
	components: list | str | None = None,
	source: str = "Core UI",
) -> dict:
	return queue_template_internal(
		conversation_name,
		template,
		language_code,
		components,
		source,
	)


def queue_template_internal(
	conversation_name: str,
	template: str,
	language_code: str = "",
	components: list | str | None = None,
	source: str = "Core",
	*,
	enqueue_delivery: bool = True,
	_batch_context: dict | None = None,
	_template_doc=None,
) -> dict:
	template_doc = _template_doc or _approved_template(template)
	if components is None:
		components = []
	elif isinstance(components, str):
		components = frappe.parse_json(components)
	if not isinstance(components, list):
		frappe.throw("Template components must be a list")
	language_code = (
		str(language_code or "").strip()
		or template_doc.language_code
		or "en"
	)
	snapshot = template_message_snapshot(template_doc, components)
	return _queue_message(
		conversation_name,
		"template",
		snapshot.get("body") or snapshot.get("header") or template_doc.template_name,
		{
			"template": template_doc.template_name,
			"template_record": template_doc.name,
			"language": language_code,
			"components": components,
			"template_snapshot": snapshot,
			"source": source,
		},
		enqueue_delivery=enqueue_delivery,
		_batch_context=_batch_context,
	)


def template_message_snapshot(template_doc, supplied_components: list | None = None) -> dict:
	"""Freeze the human-visible template content at send time.

	Meta transport still receives the canonical template name and component values, while
	the inbox renders this immutable snapshot.  Editing or re-syncing a template later must
	not change what operators believe was sent.
	"""
	definitions = _json_list(getattr(template_doc, "components", None))
	supplied = supplied_components if isinstance(supplied_components, list) else []
	header_definition = _template_component(definitions, "HEADER")
	body_definition = _template_component(definitions, "BODY")
	footer_definition = _template_component(definitions, "FOOTER")
	buttons_definition = _template_component(definitions, "BUTTONS")

	header_type = str(
		getattr(template_doc, "header_type", "")
		or header_definition.get("format")
		or "TEXT"
	).upper()
	header = str(
		getattr(template_doc, "header_content", "")
		or header_definition.get("text")
		or ""
	).strip()
	body = str(
		getattr(template_doc, "body_text", "")
		or body_definition.get("text")
		or ""
	).strip()
	footer = str(
		getattr(template_doc, "footer_text", "")
		or footer_definition.get("text")
		or ""
	).strip()

	header_parameters = _template_supplied_parameters(supplied, "header")
	body_parameters = _template_supplied_parameters(supplied, "body")
	if header_type == "TEXT":
		header = _render_template_text(header, header_parameters)
	body = _render_template_text(body, body_parameters)

	buttons = []
	for index, button in enumerate(buttons_definition.get("buttons") or []):
		if not isinstance(button, dict):
			continue
		label = str(button.get("text") or "").strip()
		if not label:
			continue
		button_type = str(button.get("type") or "").upper()
		button_parameters = _template_supplied_parameters(
			supplied,
			"button",
			index=index,
		)
		url = str(button.get("url") or "").strip()
		if url:
			url = _render_template_text(url, button_parameters)
		buttons.append({
			"label": label,
			"type": button_type,
			"url": url,
		})

	media = None
	if header_type in {"IMAGE", "VIDEO", "DOCUMENT"} and header_parameters:
		parameter = header_parameters[0]
		value = parameter.get(header_type.lower()) if isinstance(parameter, dict) else None
		if isinstance(value, dict):
			media = value.get("link") or value.get("id")

	return {
		"header": header if header_type == "TEXT" else "",
		"header_type": header_type,
		"header_media": media,
		"body": body,
		"footer": footer,
		"buttons": buttons,
	}


def _template_component(components: list, component_type: str) -> dict:
	return next(
		(
			component
			for component in components
			if isinstance(component, dict)
			and str(component.get("type") or "").upper() == component_type
		),
		{},
	)


def _template_supplied_parameters(
	components: list,
	component_type: str,
	*,
	index: int | None = None,
) -> list[dict]:
	for component in components:
		if not isinstance(component, dict):
			continue
		if str(component.get("type") or "").lower() != component_type:
			continue
		if index is not None and str(component.get("index")) != str(index):
			continue
		parameters = component.get("parameters") or []
		return parameters if isinstance(parameters, list) else []
	return []


def _render_template_text(text: str, parameters: list[dict]) -> str:
	values = [_template_parameter_text(parameter) for parameter in parameters]

	def replace(match):
		position = int(match.group(1)) - 1
		return values[position] if 0 <= position < len(values) else match.group(0)

	return re.sub(r"\{\{\s*(\d+)\s*\}\}", replace, str(text or ""))


def _template_parameter_text(parameter) -> str:
	if not isinstance(parameter, dict):
		return str(parameter or "")
	if parameter.get("text") is not None:
		return str(parameter.get("text"))
	if isinstance(parameter.get("currency"), dict):
		currency = parameter["currency"]
		return str(
			currency.get("fallback_value")
			or currency.get("amount_1000")
			or currency.get("code")
			or ""
		)
	if isinstance(parameter.get("date_time"), dict):
		return str(parameter["date_time"].get("fallback_value") or "")
	return ""


def queue_choice(
	conversation_name: str,
	body: str,
	options: list | str,
	button_label: str = "Choose",
	source: str = "Core Flow",
) -> dict:
	body = str(body or "").strip()
	if not body:
		frappe.throw("Question cannot be empty")
	if len(body) > 1024:
		frappe.throw("Interactive question cannot exceed 1024 characters")
	options = (
		frappe.parse_json(options)
		if isinstance(options, str)
		else options
	)
	normalized_options = _normalize_choice_options(options)
	button_label = str(button_label or "Choose").strip()
	if len(button_label) > 20:
		frappe.throw("Choice button label cannot exceed 20 characters")
	return _queue_message(
		conversation_name,
		"interactive",
		body,
		{
			"body": body,
			"options": normalized_options,
			"button_label": button_label,
			"source": source,
		},
	)


def queue_campaign_recipient(campaign, recipient) -> dict:
	channel = frappe.get_doc("WhatsApp Core Channel", campaign.channel)
	identity = frappe.get_doc("WhatsApp Core Identity", recipient.identity)
	conversation = get_or_create_conversation(channel, identity)
	personalization = _json_dict(recipient.personalization)
	if (getattr(campaign, "content_type", None) or "Template") == "Text":
		message = queue_text_internal(
			conversation.name,
			personalization.get("text") or campaign.message_text,
			source=f"Campaign:{campaign.name}",
		)
	else:
		template = campaign_template_document(campaign)
		message = queue_template_internal(
			conversation.name,
			template.name,
			template.language_code,
			components=personalization.get("components") or [],
			source=f"Campaign:{campaign.name}",
			_template_doc=template,
		)
	return {
		"message": message.name,
		"conversation": conversation.name,
	}


def queue_campaign_batch(campaign, recipients) -> dict:
	"""Create optimistic messages and enqueue Hub submission after commit.

	The campaign transaction owns the optimistic Core messages and recipient rows.  Sending
	to the Hub before that transaction commits lets a fast provider callback overtake the
	message insert, which produces orphaned provider sends and ``message not found`` results.
	"""
	if not recipients:
		return {}
	if len(recipients) > 40:
		frappe.throw(
			"A WhatsApp campaign transport batch cannot exceed 40 recipients",
			frappe.ValidationError,
		)
	channel = frappe.get_cached_doc("WhatsApp Core Channel", campaign.channel)
	content_type = getattr(campaign, "content_type", None) or "Template"
	template = campaign_template_document(campaign) if content_type == "Template" else None
	results = {}
	message_names = []
	message_payloads = []
	conversation_names = []
	# Transport readiness is invariant for this bounded batch. Rechecking and
	# decrypting the same Single DocType for every recipient is avoidable work.
	if not outbound_ready():
		frappe.throw(
			"WhatsApp outbound is not fully configured and enabled",
			frappe.ValidationError,
		)
	for recipient in recipients:
		try:
			identity = frappe.get_cached_doc(
				"WhatsApp Core Identity",
				recipient.identity,
			)
			conversation = get_or_create_conversation(channel, identity)
			recipient_phone = resolve_recipient_phone(
				identity,
				{
					"source": "campaign",
					"campaign": campaign.name,
					"recipient": recipient.name,
					"conversation": conversation.name,
				},
			)
			personalization = _json_dict(recipient.personalization)
			if content_type == "Text":
				message = queue_text_internal(
					conversation.name,
					personalization.get("text") or campaign.message_text,
					source=f"Campaign:{campaign.name}",
					enqueue_delivery=False,
					_batch_context={
						"conversation": conversation,
						"identity": identity,
					},
				)
			else:
				message = queue_template_internal(
					conversation.name,
					template.name,
					template.language_code,
					personalization.get("components") or [],
					source=f"Campaign:{campaign.name}",
					enqueue_delivery=False,
					_batch_context={
						"conversation": conversation,
						"identity": identity,
					},
					_template_doc=template,
				)
			# Resolve and validate while the recipient is still available to the campaign
			# worker. The durable transport call itself happens only after commit.
			_message_payload(message, recipient_phone)
			message_names.append(message.name)
			message_payloads.append(dict(message))
			conversation_names.append(conversation.name)
			results[recipient.name] = {
				"success": True,
				"message": message.name,
				"conversation": message.conversation,
			}
		except frappe.QueryDeadlockError:
			# A database deadlock invalidates the complete transaction, including
			# messages accumulated for earlier recipients. Never return stale Python
			# objects as successful rows; the campaign wrapper retries the full batch.
			raise
		except Exception as exception:
			results[recipient.name] = {
				"success": False,
				"error": str(exception),
			}

	if conversation_names:
		frappe.db.sql(
			"""
			UPDATE `tabWhatsApp Core Conversation`
			SET last_message_at = GREATEST(
				COALESCE(last_message_at, '1900-01-01 00:00:00'),
				NOW(6)
			)
			WHERE name IN %(conversation_names)s
			""",
			{"conversation_names": list(dict.fromkeys(conversation_names))},
		)
		frappe.publish_realtime(
			"whatsapp_core_batch_committed",
			{
				"event_count": 0,
				"completed": 0,
				"failed": 0,
				"kinds": ["message"],
				"conversations": list(dict.fromkeys(conversation_names)),
				"message_changes": [
					{"kind": "message", "status": "created", "message": row}
					for row in message_payloads
				],
			},
			after_commit=True,
		)

	if message_names:
		frappe.enqueue(
			"frappe_whatsapp_core.outbound.deliver_queued_message_batch",
			queue="short",
			enqueue_after_commit=True,
			message_names=message_names,
		)
	return results


def freeze_campaign_template(template_name: str) -> dict:
	"""Return the approved catalog data a campaign must retain for its full run."""
	template = _approved_template(template_name)
	return {
		"name": template.name,
		"template_name": template.template_name,
		"language_code": template.language_code or "en",
		"category": template.category or "",
		"approval_status": template.approval_status,
		"enabled": bool(template.enabled),
		"header_type": template.header_type or "",
		"header_content": template.header_content or "",
		"body_text": template.body_text or "",
		"footer_text": template.footer_text or "",
		"components": _json_list(template.components),
	}


def campaign_template_document(campaign):
	"""Return the immutable launch snapshot, with a legacy-campaign fallback.

	New campaigns always persist ``template_snapshot`` before they are queued. Older
	campaigns created before that field existed still need to drain safely, so they
	use the catalog document that their existing workers used historically.
	"""
	snapshot = _json_dict(getattr(campaign, "template_snapshot", None))
	if snapshot:
		return frappe._dict(snapshot)
	return frappe.get_cached_doc("WhatsApp Core Template", campaign.template)


def deliver_queued_message_batch(message_names: list[str]) -> None:
	"""Submit committed optimistic messages to the Hub in one bounded batch."""
	message_names = list(dict.fromkeys(message_names or []))
	if not message_names:
		return
	if len(message_names) > 40:
		frappe.throw(
			"A WhatsApp campaign transport batch cannot exceed 40 messages",
			frappe.ValidationError,
		)

	submissions = []
	preparation_failures = []
	missing_messages = []
	for message_name in message_names:
		try:
			message = frappe.get_doc("WhatsApp Core Message", message_name)
		except frappe.DoesNotExistError:
			# A stale after-commit job must not prevent the other 39 independent
			# messages in this transport batch from reaching the Hub.
			missing_messages.append(message_name)
			continue
		if message.delivery_status != "Queued":
			continue
		try:
			conversation = frappe.get_doc(
				"WhatsApp Core Conversation",
				message.conversation,
			)
			identity = frappe.get_doc(
				"WhatsApp Core Identity",
				conversation.remote_identity,
			)
			context = {
				"source": "message",
				"message": message.name,
				"conversation": conversation.name,
				"channel": message.channel,
			}
			group_id = _group_id(identity)
			recipient = group_id or resolve_recipient_phone(identity, context)
			submissions.append({
				"message": message,
				"channel": message.channel,
				"payload": _message_payload(
					message,
					recipient,
					recipient_type="group" if group_id else "individual",
				),
				"idempotency_key": message.idempotency_key,
			})
		except Exception as exception:
			preparation_failures.append(
				(message.name, {"error": str(exception), "retryable": False})
			)

	# Everything above is read-only. End that database snapshot before the external
	# request: Meta can deliver its callback while this HTTP request is still in
	# flight, and retaining the old snapshot makes MariaDB reject the later status
	# update with error 1020 (record changed since last read). No business write is
	# discarded here.
	frappe.db.rollback()
	if missing_messages:
		frappe.logger("frappe_whatsapp_core").warning(
			"Skipped %s missing messages from a committed campaign transport batch",
			len(missing_messages),
		)
	if not submissions:
		for message_name, failure in preparation_failures:
			_mark_failed(frappe._dict(name=message_name), failure)
		return

	hub_result = send_hub_batch([
		{
			"channel": item["channel"],
			"payload": item["payload"],
			"idempotency_key": item["idempotency_key"],
		}
		for item in submissions
	])
	# Hub settings are resolved from Frappe immediately before the HTTP request,
	# which starts another read transaction. End it after the request for the same
	# callback-before-response race handled by the single-message path.
	frappe.db.rollback()
	for message_name, failure in preparation_failures:
		_mark_failed(frappe._dict(name=message_name), failure)
	items_by_key = {
		item.get("idempotency_key"): item
		for item in hub_result.get("items") or []
		if isinstance(item, dict) and item.get("idempotency_key")
	}
	for submission in submissions:
		message = submission["message"]
		item = items_by_key.get(submission["idempotency_key"]) or {}
		relay_result = item.get("result") or {}
		item_status = str(item.get("status") or "").lower()
		relay_status = str(relay_result.get("status") or "").lower()
		if (
			hub_result.get("accepted")
			and relay_result.get("success")
			and (
				item_status in {"completed", "sent"}
				or relay_status == "sent"
			)
		):
			_mark_sent(message, relay_result.get("meta_message_id"))
		elif (
			hub_result.get("accepted")
			and relay_result.get("success")
			and (
				item_status in {"queued", "duplicate"}
				or relay_status == "queued"
			)
		):
			# The relay accepted this independent JetStream work item.
			# Its durable result callback will finalize the local message.
			pass
		elif (
			hub_result.get("accepted")
			and (
				item_status == "failed"
				or relay_status == "failed"
			)
		):
			_mark_failed(message, relay_result)
		else:
			_record_retryable_submission(
				message,
				{
					"error": (
						relay_result.get("error")
						or hub_result.get("error")
						or "Batch submission was not confirmed"
					),
				},
			)
			_enqueue_message_delivery(message.name)


def deliver_queued_message(message_name: str) -> None:
	lock_name = f"whatsapp_core_outbound:{message_name}"
	with frappe.cache.lock(lock_name, timeout=90, blocking_timeout=1):
		message = frappe.get_doc("WhatsApp Core Message", message_name)
		if message.delivery_status != "Queued":
			return
		conversation = frappe.get_doc(
			"WhatsApp Core Conversation",
			message.conversation,
		)
		identity = frappe.get_doc(
			"WhatsApp Core Identity",
			conversation.remote_identity,
		)
		context = {
			"source": "message",
			"message": message.name,
			"conversation": conversation.name,
			"channel": message.channel,
		}
		group_id = _group_id(identity)
		recipient = group_id or resolve_recipient_phone(identity, context)
		payload = _message_payload(
			message,
			recipient,
			recipient_type="group" if group_id else "individual",
		)
		result = send_raw(
			message.channel,
			payload,
			message.idempotency_key,
		)
		# The provider may have committed a status callback during send_raw().
		# Refresh the transaction boundary so the monotonic UPDATE below operates
		# against the current row rather than the pre-request read snapshot.
		frappe.db.rollback()
		if result.get("accepted"):
			if result.get("status") not in {"queued", "retrying"}:
				_mark_sent(message, result.get("meta_message_id"))
			return
		if result.get("retryable"):
			_record_retryable_submission(message, result)
			return
		_mark_failed(message, result)


def retry_queued_messages(limit: int = 500) -> None:
	cutoff = add_to_date(now_datetime(), seconds=-30)
	message_names = frappe.db.sql(
		"""
		SELECT message.name
		FROM `tabWhatsApp Core Message` message
		LEFT JOIN `tabWhatsApp Core Campaign Recipient` recipient
			ON recipient.core_message = message.name
		LEFT JOIN `tabWhatsApp Core Campaign` campaign
			ON campaign.name = recipient.campaign
		WHERE message.direction = 'Outbound'
			AND message.delivery_status = 'Queued'
			AND message.modified <= %s
			AND (campaign.name IS NULL OR campaign.status != 'Cancelled')
		ORDER BY message.modified ASC
		LIMIT %s
		""",
		(cutoff, max(1, min(int(limit), 2000))),
		pluck=True,
	)
	for message_name in message_names:
		frappe.enqueue(
			"frappe_whatsapp_core.outbound.deliver_queued_message",
			queue="short",
			enqueue_after_commit=True,
			message_name=message_name,
		)


def _queue_message(
	conversation_name: str,
	message_type: str,
	body: str,
	content: dict,
	*,
	enqueue_delivery: bool = True,
	client_message_id: str | None = None,
	_batch_context: dict | None = None,
) -> dict:
	batch_context = _batch_context or {}
	if not batch_context:
		assert_conversation_access(conversation_name)
	if not batch_context and not outbound_ready():
		frappe.throw(
			"WhatsApp outbound is not fully configured and enabled",
			frappe.ValidationError,
		)
	conversation = batch_context.get("conversation") or frappe.get_doc(
		"WhatsApp Core Conversation", conversation_name
	)
	identity = batch_context.get("identity") or frappe.get_cached_doc(
		"WhatsApp Core Identity", conversation.remote_identity
	)
	group_id = _group_id(identity)
	if not batch_context:
		frappe.has_permission(
			"WhatsApp Core Conversation",
			"read",
			doc=conversation,
			throw=True,
		)
	if (
		not group_id
		and message_type != "template"
		and not _within_service_window(conversation.name)
	):
		frappe.throw(
			"An approved template is required outside the 24-hour customer service window",
			frappe.ValidationError,
		)
	if group_id and message_type not in {
		"text", "image", "video", "audio", "document", "template"
	}:
		frappe.throw(
			f"{message_type.title()} messages are not supported by Meta Groups",
			frappe.ValidationError,
		)
	_run_preflight_hooks(
		conversation=conversation,
		message_type=message_type,
		content=content,
	)
	local_id = f"local:{_client_uuid(client_message_id)}"
	message_key = hashlib.sha256(
		f"{conversation.channel}:{local_id}".encode()
	).hexdigest()
	message = frappe.get_doc({
		"doctype": "WhatsApp Core Message",
		"message_key": message_key,
		"idempotency_key": message_key,
		"conversation": conversation.name,
		"channel": conversation.channel,
		"provider_message_id": local_id,
		"direction": "Outbound",
		"message_type": message_type,
		"body": body,
		"content": json.dumps(
			{"client_message_id": local_id, **content},
			separators=(",", ":"),
			ensure_ascii=False,
		),
		"provider_timestamp": now_datetime(),
		"delivery_status": "Queued",
	}).insert(ignore_permissions=True)
	if not batch_context:
		conversation.last_message_at = message.provider_timestamp
		conversation.save(ignore_permissions=True)
	if enqueue_delivery:
		_enqueue_message_delivery(message.name)
	message_payload = message.as_dict()
	message_payload["sender_name"] = (
		frappe.db.get_value("User", message.owner, "full_name") or message.owner
	)
	if not batch_context:
		frappe.publish_realtime(
			"whatsapp_core_message",
			{"conversation": conversation.name, "message": message_payload},
			after_commit=True,
		)
	return message_payload


def _client_uuid(client_message_id: str | None = None) -> uuid.UUID:
	"""Return a validated client UUID or create one for non-UI callers.

	Accepting the UI-generated UUID lets the browser render immediately and
	reconcile the optimistic row with both the API response and realtime event.
	"""
	if not client_message_id:
		return uuid.uuid4()
	try:
		return uuid.UUID(str(client_message_id))
	except (TypeError, ValueError, AttributeError):
		frappe.throw("Invalid client message ID", frappe.ValidationError)


def _enqueue_message_delivery(message_name: str) -> None:
	frappe.enqueue(
		"frappe_whatsapp_core.outbound.deliver_queued_message",
		queue="short",
		enqueue_after_commit=True,
		message_name=message_name,
	)


def _run_preflight_hooks(**context) -> None:
	for path in frappe.get_hooks("whatsapp_core_outbound_preflight"):
		result = frappe.get_attr(path)(context)
		if result is False:
			frappe.throw("Outbound business preflight failed")
		if isinstance(result, dict) and not result.get("ready", False):
			frappe.throw(
				"; ".join(
					result.get("reasons")
					or ["Outbound business preflight failed"]
				)
			)


def _approved_template(template: str):
	template_name = str(template or "").strip()
	if not template_name:
		frappe.throw("Template is required")
	record_name = (
		template_name
		if frappe.db.exists("WhatsApp Core Template", template_name)
		else frappe.db.get_value(
			"WhatsApp Core Template",
			{"template_name": template_name, "enabled": 1},
			"name",
		)
	)
	if not record_name:
		frappe.throw("Template is not assigned to this site")
	doc = frappe.get_doc("WhatsApp Core Template", record_name)
	if not doc.enabled:
		frappe.throw("Template is disabled for this site")
	if doc.approval_status != "APPROVED":
		frappe.throw("Template is not approved by Meta")
	return doc


def _message_payload(
	message,
	recipient: str,
	*,
	recipient_type: str = "individual",
) -> dict:
	content = _json_dict(message.content)
	payload = {
		"messaging_product": "whatsapp",
		"recipient_type": recipient_type,
		"to": recipient,
		"type": message.message_type,
	}
	if message.message_type == "text":
		payload["text"] = {"body": message.body}
		if content.get("context_message_id"):
			payload["context"] = {"message_id": content["context_message_id"]}
	elif message.message_type == "template":
		payload["template"] = {
			"name": content["template"],
			"language": {"code": content.get("language") or "en"},
		}
		if content.get("components"):
			payload["template"]["components"] = content["components"]
	elif message.message_type == "interactive":
		if content.get("payload"):
			rich_payload = deepcopy(content["payload"])
			context_message_id = rich_payload.pop("context_message_id", None)
			payload["interactive"] = rich_payload
			if context_message_id:
				payload["context"] = {"message_id": context_message_id}
		else:
			payload["interactive"] = _interactive_payload(
				content.get("body") or message.body,
				_normalize_choice_options(content.get("options")),
				content.get("button_label") or "Choose",
			)
	elif message.message_type in _RICH_MESSAGE_TYPES:
		rich_payload = deepcopy(content.get("payload") or {})
		context_message_id = rich_payload.pop("context_message_id", None)
		rich_payload.pop("local_file_url", None)
		payload[message.message_type] = (
			rich_payload.get("contacts")
			if message.message_type == "contacts"
			else rich_payload
		)
		if context_message_id:
			payload["context"] = {"message_id": context_message_id}
	else:
		frappe.throw(f"Unsupported outbound message type: {message.message_type}")
	return payload


def _local_media_file(file_url: str, message_type: str):
	if message_type not in {"audio", "document", "image", "sticker", "video"}:
		frappe.throw("A local File is valid only for media messages", frappe.ValidationError)
	file_name = frappe.db.get_value("File", {"file_url": str(file_url or "").strip()}, "name")
	if not file_name:
		frappe.throw("Uploaded local media was not found", frappe.DoesNotExistError)
	file_doc = frappe.get_doc("File", file_name)
	frappe.has_permission("File", "read", doc=file_doc, throw=True)
	return file_doc


def _group_id(identity) -> str:
	attributes = _json_dict(identity.attributes)
	group_id = str(attributes.get("group_id") or "").strip()
	if group_id:
		return group_id
	normalized = str(identity.normalized_value or "")
	return normalized.removeprefix("group:").strip() if normalized.startswith("group:") else ""


_RICH_MESSAGE_TYPES = {
	"audio",
	"contacts",
	"document",
	"image",
	"location",
	"reaction",
	"sticker",
	"video",
}


def _validate_rich_payload(message_type: str, payload: dict) -> dict:
	if message_type not in _RICH_MESSAGE_TYPES | {"interactive"}:
		frappe.throw(f"Unsupported rich message type: {message_type}", frappe.ValidationError)
	for forbidden in {"to", "messaging_product", "recipient_type"}:
		if forbidden in payload:
			frappe.throw(f"Rich message payload cannot set {forbidden}", frappe.ValidationError)
	if message_type != "interactive" and "type" in payload:
		frappe.throw("Rich message payload cannot set type", frappe.ValidationError)
	result = deepcopy(payload)
	context = _provider_context_id(result.get("context_message_id"))
	if context:
		result["context_message_id"] = context
	else:
		result.pop("context_message_id", None)

	if message_type in {"image", "video", "audio", "document", "sticker"}:
		media_sources = [key for key in ("id", "link") if str(result.get(key) or "").strip()]
		if len(media_sources) != 1:
			frappe.throw(
				f"{message_type.title()} requires exactly one media id or link",
				frappe.ValidationError,
			)
		result[media_sources[0]] = str(result[media_sources[0]]).strip()
		if message_type == "sticker" and any(key in result for key in ("caption", "filename")):
			frappe.throw("Stickers do not support captions or filenames", frappe.ValidationError)
		if len(str(result.get("caption") or "")) > 1024:
			frappe.throw("Media caption cannot exceed 1024 characters", frappe.ValidationError)
	elif message_type == "reaction":
		result["message_id"] = _provider_context_id(result.get("message_id"), required=True)
		if len(str(result.get("emoji") or "")) > 16:
			frappe.throw("Reaction emoji is invalid", frappe.ValidationError)
	elif message_type == "location":
		try:
			latitude = float(result.get("latitude"))
			longitude = float(result.get("longitude"))
		except (TypeError, ValueError):
			frappe.throw("Location requires numeric latitude and longitude", frappe.ValidationError)
		if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
			frappe.throw("Location coordinates are out of range", frappe.ValidationError)
		result["latitude"], result["longitude"] = latitude, longitude
	elif message_type == "contacts":
		contacts = result.get("contacts")
		if not isinstance(contacts, list) or not 1 <= len(contacts) <= 10:
			frappe.throw("Contacts requires between 1 and 10 contact objects", frappe.ValidationError)
		result = {"contacts": contacts, **({"context_message_id": context} if context else {})}
	elif message_type == "interactive":
		interactive_type = str(result.get("type") or "").strip()
		if interactive_type not in {
			"button", "list", "product", "product_list", "catalog_message",
			"flow", "location_request_message", "address_message", "order_details",
			"order_status",
		}:
			frappe.throw("Unsupported interactive message type", frappe.ValidationError)
		if not isinstance(result.get("action"), dict):
			frappe.throw("Interactive message requires an action object", frappe.ValidationError)
	return result


def _provider_context_id(value, *, required: bool = False) -> str:
	value = str(value or "").strip()
	if not value:
		if required:
			frappe.throw("Provider message id is required", frappe.ValidationError)
		return ""
	if value.startswith("local:"):
		frappe.throw("A queued local message cannot be used as reply context", frappe.ValidationError)
	if len(value) > 512:
		frappe.throw("Provider message id is invalid", frappe.ValidationError)
	return value


def _rich_message_body(message_type: str, payload: dict) -> str:
	if message_type in {"image", "video", "audio", "document"}:
		return str(payload.get("caption") or f"[{message_type.title()}]")
	if message_type == "sticker":
		return "[Sticker]"
	if message_type == "reaction":
		return str(payload.get("emoji") or "[Reaction removed]")
	if message_type == "location":
		return str(payload.get("name") or payload.get("address") or "[Location]")
	if message_type == "contacts":
		return "[Contact]" if len(payload.get("contacts") or []) == 1 else "[Contacts]"
	if message_type == "interactive":
		body = payload.get("body") or {}
		return str(body.get("text") or f"[{payload.get('type', 'Interactive').title()}]")
	return f"[{message_type.title()}]"


def _mark_sent(message, provider_message_id: str | None) -> None:
	# A provider status webhook can arrive before the HTTP send call returns.
	# Updating the Document loaded before that network call would then either
	# raise MariaDB 1020 (stale row) or regress Delivered/Read back to Sent.
	# Keep this as one atomic, monotonic update against the current database row.
	frappe.db.sql(
		"""
		UPDATE `tabWhatsApp Core Message`
		SET provider_message_id = CASE
				WHEN %(provider_message_id)s != '' THEN %(provider_message_id)s
				ELSE provider_message_id
			END,
			delivery_status = CASE
				WHEN delivery_status = 'Queued' THEN 'Sent'
				ELSE delivery_status
			END,
			failure = CASE
				WHEN delivery_status IN ('Queued', 'Sent') THEN NULL
				ELSE failure
			END
		WHERE name = %(name)s
		""",
		{
			"name": message.name,
			"provider_message_id": str(provider_message_id or "").strip(),
		},
	)
	frappe.clear_document_cache("WhatsApp Core Message", message.name)
	current = frappe.db.get_value(
		"WhatsApp Core Message",
		message.name,
		["name", "conversation", "delivery_status", "provider_message_id"],
		as_dict=True,
	)
	if not current:
		return
	if provider_message_id:
		# Direct sends and durable relay-result callbacks share the same provider
		# race. Wake receipts that arrived before this id was persisted.
		from frappe_whatsapp_core.dispatcher import enqueue_waiting_status_events

		enqueue_waiting_status_events(
			[provider_message_id],
			enqueue_after_commit=True,
		)
	_reconcile_campaign_message(message.name)
	_publish_status(current)


def _record_retryable_submission(message, result: dict) -> None:
	content = _json_dict(message.content)
	submission = content.setdefault("submission", {})
	submission["attempts"] = int(submission.get("attempts") or 0) + 1
	submission["last_attempt_at"] = str(now_datetime())
	submission["last_error"] = str(result.get("error") or "")[:500]
	content_json = json.dumps(
		content,
		separators=(",", ":"),
		ensure_ascii=False,
	)
	# Do not overwrite a callback that already advanced this message while the
	# provider request was in flight.
	frappe.db.sql(
		"""
		UPDATE `tabWhatsApp Core Message`
		SET content = %(content)s
		WHERE name = %(name)s AND delivery_status = 'Queued'
		""",
		{"name": message.name, "content": content_json},
	)
	frappe.clear_document_cache("WhatsApp Core Message", message.name)


def _mark_failed(message, failure: dict) -> None:
	failure_json = json.dumps(
		failure,
		separators=(",", ":"),
		ensure_ascii=False,
	)
	# A late send failure cannot undo an already delivered/read receipt.
	frappe.db.sql(
		"""
		UPDATE `tabWhatsApp Core Message`
		SET delivery_status = CASE
				WHEN delivery_status IN ('Delivered', 'Read', 'Deleted')
					THEN delivery_status
				ELSE 'Failed'
			END,
			failure = CASE
				WHEN delivery_status IN ('Delivered', 'Read', 'Deleted')
					THEN failure
				ELSE %(failure)s
			END
		WHERE name = %(name)s
		""",
		{"name": message.name, "failure": failure_json},
	)
	frappe.clear_document_cache("WhatsApp Core Message", message.name)
	current = frappe.db.get_value(
		"WhatsApp Core Message",
		message.name,
		["name", "conversation", "delivery_status", "provider_message_id"],
		as_dict=True,
	)
	if not current:
		return
	_reconcile_campaign_message(message.name)
	_publish_status(current)


def _reconcile_campaign_message(message_name: str) -> None:
	# Keep campaign aggregation outside the provider-send transaction. A single
	# campaign row is shared by thousands of independent message workers; locking
	# it here can roll back an already accepted provider send and cause a retry.
	# The after-commit projection is idempotent and the periodic dirty repair is
	# the final source of truth for counters.
	from frappe_whatsapp_core.campaigns import enqueue_campaign_refresh_for_messages

	enqueue_campaign_refresh_for_messages([message_name])


def _publish_status(message) -> None:
	frappe.publish_realtime(
		"whatsapp_core_message_status",
		{
			"conversation": message.conversation,
			"message": message.name,
			"delivery_status": message.delivery_status,
			"provider_message_id": message.provider_message_id,
		},
		after_commit=True,
	)


def _json_dict(value) -> dict:
	if not value:
		return {}
	result = frappe.parse_json(value) if isinstance(value, str) else value
	return result if isinstance(result, dict) else {}


def _json_list(value) -> list:
	if not value:
		return []
	result = frappe.parse_json(value) if isinstance(value, str) else value
	return result if isinstance(result, list) else []


def _normalize_choice_options(options) -> list[dict]:
	if not isinstance(options, list) or not 2 <= len(options) <= 10:
		frappe.throw("A choice question requires between 2 and 10 options")
	normalized = []
	values = set()
	for index, option in enumerate(options, start=1):
		if isinstance(option, str):
			label = value = option.strip()
		elif isinstance(option, dict):
			label = str(option.get("label") or "").strip()
			value = str(option.get("value") or label).strip()
		else:
			frappe.throw(f"Choice option {index} must be text or an object")
		if not label or not value:
			frappe.throw(f"Choice option {index} requires a label and value")
		if len(label) > 24:
			frappe.throw(
				f"Choice option {index} label cannot exceed 24 characters"
			)
		if len(value) > 200:
			frappe.throw(
				f"Choice option {index} value cannot exceed 200 characters"
			)
		if value in values:
			frappe.throw(f"Choice option value is duplicated: {value}")
		values.add(value)
		normalized.append({"label": label, "value": value})
	return normalized


def _interactive_payload(
	body: str,
	options: list[dict],
	button_label: str,
) -> dict:
	if len(options) <= 3:
		return {
			"type": "button",
			"body": {"text": body},
			"action": {
				"buttons": [
					{
						"type": "reply",
						"reply": {
							"id": option["value"],
							"title": option["label"][:20],
						},
					}
					for option in options
				],
			},
		}
	return {
		"type": "list",
		"body": {"text": body},
		"action": {
			"button": button_label,
			"sections": [{
				"title": "Options",
				"rows": [
					{"id": option["value"], "title": option["label"]}
					for option in options
				],
			}],
		},
	}


def _within_service_window(conversation: str) -> bool:
	last_inbound_at = frappe.db.get_value(
		"WhatsApp Core Conversation",
		conversation,
		"last_inbound_at",
	)
	if not last_inbound_at:
		return False
	return last_inbound_at >= add_to_date(now_datetime(), hours=-24)
