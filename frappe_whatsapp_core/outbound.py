"""Core-owned optimistic outbound messages and crash-safe Hub submission."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import mimetypes
import re
import uuid
from copy import deepcopy
from urllib.parse import urlsplit

import frappe
from frappe.utils import add_to_date, cint, now_datetime

from frappe_whatsapp_core.delivery import enqueue_delivery_status_handlers
from frappe_whatsapp_core.hub_client import (
	connection_status,
	get_settings,
	send_raw,
)
from frappe_whatsapp_core.hub_client import (
	send_batch as send_hub_batch,
)
from frappe_whatsapp_core.hub_client import (
	upload_media as upload_meta_media,
)
from frappe_whatsapp_core.identity import (
	is_business_scoped_user_id,
	is_parent_business_scoped_user_id,
	normalize_business_scoped_user_id,
	phone_candidates,
)
from frappe_whatsapp_core.materializer import (
	get_or_create_conversation,
	get_or_create_identity,
	normalize_phone,
)
from frappe_whatsapp_core.permissions import assert_conversation_access, require_core_access
from frappe_whatsapp_core.realtime import publish_message_changes


def outbound_ready(channel: str | None = None) -> bool:
	status = connection_status()
	ready = bool(
		status["enabled"]
		and status["outbound_enabled"]
		and status["credentials_configured"]
		and status["account_count"]
	)
	if not ready or not channel:
		return ready
	settings = frappe.get_single("WhatsApp Core Settings")
	return any(row.channel == channel and row.account_name for row in settings.accounts)


def resolve_recipient_phone(identity, context: dict | None = None) -> str:
	"""Resolve the exact Meta recipient (phone or portfolio-scoped BSUID)."""
	if isinstance(identity, str):
		identity = frappe.get_cached_doc("WhatsApp Core Identity", identity)
	if getattr(identity, "status", "Active") != "Active":
		frappe.throw(
			"This WhatsApp contact is blocked from outbound messaging",
			frappe.ValidationError,
		)
	context = context or {}
	attributes = _json_dict(getattr(identity, "attributes", None))
	bsuid = str(attributes.get("business_scoped_user_id") or "").strip()
	if getattr(identity, "identifier_type", None) == "BSUID" and not bsuid:
		bsuid = str(identity.normalized_value or "").strip()
	if bsuid and not context.get("require_phone"):
		scope = getattr(identity, "identity_scope", None)
		if context.get("channel") and scope and scope != context["channel"]:
			frappe.throw(
				"This business-scoped user ID belongs to another WhatsApp account",
				frappe.ValidationError,
			)
		return normalize_business_scoped_user_id(bsuid)

	paths = frappe.get_hooks("whatsapp_core_recipient_phone_resolver") or []
	if isinstance(paths, str):
		paths = [paths]
	paths = list(dict.fromkeys(paths))
	if len(paths) > 1:
		frappe.throw(
			"At most one WhatsApp recipient phone resolver may be configured",
			frappe.ValidationError,
		)

	phone_aliases = attributes.get("phone_aliases") or []
	value = (
		phone_aliases[-1]
		if phone_aliases
		else ""
		if bsuid
		else identity.normalized_value
	)
	if paths:
		resolved = frappe.get_attr(paths[0])(
			identity=identity,
			context=context,
		)
		if isinstance(resolved, dict):
			resolved = resolved.get("phone_number")
		if resolved:
			value = resolved
	elif not bsuid:
		value = _linked_recipient_phone(identity, context) or value

	default_country_code = str(
		context.get("default_country_calling_code")
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
	conversation_channel = (
		frappe.db.get_value("WhatsApp Core Conversation", conversation, "channel")
		if conversation
		else None
	)
	if (
		conversation_channel
		and status["account_count"]
		and not outbound_ready(conversation_channel)
	):
		reasons.append("This conversation channel is not mapped to a Hub account")
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
			context={"operation": "start_conversation", "channel": channel_doc.name},
		)
	else:
		default_country_code = (
			frappe.db.get_single_value(
				"WhatsApp Core Settings",
				"default_country_calling_code",
			)
			or "91"
		)
		if is_business_scoped_user_id(phone_number):
			normalized = normalize_business_scoped_user_id(phone_number)
			alias_type = (
				"parent_user_id"
				if is_parent_business_scoped_user_id(normalized)
				else "user_id"
			)
			identity_doc = get_or_create_identity(
				normalized,
				scope=channel_doc.name,
				aliases={alias_type: normalized},
			)
			resolved_phone = normalized
		else:
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
	preview_url=0,
) -> dict:
	return queue_text_internal(
		conversation_name,
		body,
		source,
		context_message_id=context_message_id,
		client_message_id=client_message_id,
		preview_url=preview_url,
	)


def queue_text_internal(
	conversation_name: str,
	body: str,
	source: str = "Core",
	*,
	context_message_id: str | None = None,
	client_message_id: str | None = None,
	preview_url=False,
	enqueue_delivery: bool = True,
	_batch_context: dict | None = None,
) -> dict:
	body = str(body or "").strip()
	if not body:
		frappe.throw("Message cannot be empty")
	if len(body) > 4096:
		frappe.throw("Message cannot exceed 4096 characters")
	preview_url = bool(cint(preview_url))
	return _queue_message(
		conversation_name,
		"text",
		body,
		{
			"body": body,
			"source": source,
			"context_message_id": _provider_context_id(context_message_id),
			**({"preview_url": True} if preview_url else {}),
		},
		client_message_id=client_message_id,
		enqueue_delivery=enqueue_delivery,
		_batch_context=_batch_context,
	)


@frappe.whitelist()
@require_core_access()
def queue_direct_text(
	conversation_name: str,
	body: str,
	category: str,
	source: str = "Core UI",
	client_message_id: str | None = None,
	ttl_seconds=None,
	template_name: str | None = None,
) -> dict:
	"""Queue an allow-listed Meta Direct Send text as a durable Core message."""
	return queue_direct_text_internal(
		conversation_name,
		body,
		category,
		source,
		client_message_id=client_message_id,
		ttl_seconds=ttl_seconds,
		template_name=template_name,
	)


def queue_direct_text_internal(
	conversation_name: str,
	body: str,
	category: str,
	source: str = "Core",
	*,
	client_message_id: str | None = None,
	ttl_seconds=None,
	template_name: str | None = None,
	enqueue_delivery: bool = True,
) -> dict:
	body = str(body or "").strip()
	if not body:
		frappe.throw("Message cannot be empty")
	if len(body) > 4096:
		frappe.throw("Message cannot exceed 4096 characters")
	direct_send_category = _direct_send_category(category, required=True)
	ttl_seconds = _direct_send_ttl_seconds(ttl_seconds, direct_send_category)
	template_name = _direct_send_template_name(template_name, direct_send_category)
	return _queue_message(
		conversation_name,
		"text",
		body,
		{
			"body": body,
			"source": source,
			"direct_send_category": direct_send_category,
			**(
				{"direct_send_ttl_seconds": ttl_seconds}
				if ttl_seconds is not None
				else {}
			),
			**(
				{"direct_send_template_name": template_name}
				if template_name
				else {}
			),
		},
		client_message_id=client_message_id,
		enqueue_delivery=enqueue_delivery,
	)


@frappe.whitelist()
@require_core_access()
def queue_direct_interactive(
	conversation_name: str,
	payload: dict | str,
	category: str = "utility",
	source: str = "Core UI",
	client_message_id: str | None = None,
	ttl_seconds=None,
	template_name: str | None = None,
) -> dict:
	"""Queue a bounded Direct Send CTA or reply-button message."""
	return queue_direct_interactive_internal(
		conversation_name,
		payload,
		category,
		source,
		client_message_id=client_message_id,
		ttl_seconds=ttl_seconds,
		template_name=template_name,
	)


def queue_direct_interactive_internal(
	conversation_name: str,
	payload: dict | str,
	category: str = "utility",
	source: str = "Core",
	*,
	client_message_id: str | None = None,
	ttl_seconds=None,
	template_name: str | None = None,
	enqueue_delivery: bool = True,
) -> dict:
	category = _direct_send_category(category, required=True)
	if category != "utility":
		frappe.throw(
			"Authentication Direct Send supports text messages only",
			frappe.ValidationError,
		)
	if isinstance(payload, str):
		payload = frappe.parse_json(payload)
	if not isinstance(payload, dict):
		frappe.throw("Direct Send payload must be an object", frappe.ValidationError)
	normalized = _validate_direct_send_interactive(
		_validate_rich_payload("interactive", payload)
	)
	ttl_seconds = _direct_send_ttl_seconds(ttl_seconds, category)
	template_name = _direct_send_template_name(template_name, category)
	body = _rich_message_body("interactive", normalized).strip()[:4096]
	return _queue_message(
		conversation_name,
		"interactive",
		body,
		{
			"payload": normalized,
			"source": source,
			"direct_send_category": category,
			**(
				{"direct_send_ttl_seconds": ttl_seconds}
				if ttl_seconds is not None
				else {}
			),
			**(
				{"direct_send_template_name": template_name}
				if template_name
				else {}
			),
		},
		client_message_id=client_message_id,
		enqueue_delivery=enqueue_delivery,
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
	_batch_context: dict | None = None,
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
		_batch_context=_batch_context,
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
	result = upload_meta_media(
		settings.get_account_name(conversation.channel),
		content,
		content_type=(
			mimetypes.guess_type(file_doc.file_name or "")[0]
			or "application/octet-stream"
		),
		filename=file_doc.file_name or "file",
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
	client_message_id: str | None = None,
) -> dict:
	return queue_template_internal(
		conversation_name,
		template,
		language_code,
		components,
		source,
		client_message_id=client_message_id,
	)


@frappe.whitelist()
@require_core_access()
def queue_marketing_template(
	conversation_name: str,
	template: str,
	language_code: str = "",
	components: list | str | None = None,
	product_policy: dict | str | None = None,
	message_activity_sharing=None,
	source: str = "Core UI",
	client_message_id: str | None = None,
) -> dict:
	"""Queue a durable template explicitly for Meta's Marketing Messages API."""
	_assert_marketing_preference(conversation_name)
	if isinstance(product_policy, str):
		product_policy = frappe.parse_json(product_policy)
	if product_policy is not None and not isinstance(product_policy, dict):
		frappe.throw("product_policy must be an object", frappe.ValidationError)
	marketing_options = {}
	if product_policy:
		marketing_options["product_policy"] = product_policy
	if message_activity_sharing not in (None, ""):
		marketing_options["message_activity_sharing"] = bool(cint(message_activity_sharing))
	return queue_template_internal(
		conversation_name,
		template,
		language_code,
		components,
		source,
		client_message_id=client_message_id,
		transport_endpoint="marketing_messages",
		marketing_options=marketing_options,
	)


def _assert_marketing_preference(conversation_name):
	identity_name = frappe.db.get_value(
		"WhatsApp Core Conversation", conversation_name, "remote_identity"
	)
	if not identity_name:
		frappe.throw("Conversation was not found", frappe.DoesNotExistError)
	attributes = frappe.db.get_value("WhatsApp Core Identity", identity_name, "attributes") or {}
	if isinstance(attributes, str):
		attributes = frappe.parse_json(attributes)
	preferences = attributes.get("user_preferences") if isinstance(attributes, dict) else {}
	marketing = (preferences or {}).get("MARKETING_MESSAGES") or {}
	if str(marketing.get("value") or "").upper() == "STOP":
		frappe.throw(
			"Meta reports that this recipient has stopped marketing messages",
			frappe.ValidationError,
		)


def queue_template_internal(
	conversation_name: str,
	template: str,
	language_code: str = "",
	components: list | str | None = None,
	source: str = "Core",
	*,
	client_message_id: str | None = None,
	enqueue_delivery: bool = True,
	_batch_context: dict | None = None,
	_template_doc=None,
	transport_endpoint: str = "messages",
	marketing_options: dict | None = None,
) -> dict:
	conversation_channel = frappe.db.get_value(
		"WhatsApp Core Conversation", conversation_name, "channel"
	)
	if not conversation_channel:
		frappe.throw("Conversation was not found", frappe.DoesNotExistError)
	template_doc = _template_doc or _approved_template(template, channel=conversation_channel)
	if not template_doc.channel or template_doc.channel != conversation_channel:
		frappe.throw(
			"Template is not assigned to this conversation's WhatsApp account",
			frappe.PermissionError,
		)
	if components is None:
		components = []
	elif isinstance(components, str):
		components = frappe.parse_json(components)
	if not isinstance(components, list):
		frappe.throw("Template components must be a list")
	_validate_template_send_parameters(template_doc, components)
	language_code = (
		str(language_code or "").strip()
		or template_doc.language_code
		or "en"
	)
	snapshot = template_message_snapshot(template_doc, components)
	transport_endpoint = _transport_endpoint(transport_endpoint)
	if transport_endpoint == "marketing_messages" and str(template_doc.category or "").upper() != "MARKETING":
		frappe.throw(
			"Only approved MARKETING templates can use marketing_messages",
			frappe.ValidationError,
		)
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
			**(
				{
					"transport_endpoint": transport_endpoint,
					"marketing_options": deepcopy(marketing_options or {}),
				}
				if transport_endpoint != "messages"
				else {}
			),
		},
		client_message_id=client_message_id,
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
	named_values = {
		str(parameter.get("parameter_name") or "").strip(): _template_parameter_text(parameter)
		for parameter in parameters
		if isinstance(parameter, dict) and parameter.get("parameter_name")
	}

	def replace(match):
		position = int(match.group(1)) - 1
		return values[position] if 0 <= position < len(values) else match.group(0)

	rendered = re.sub(r"\{\{\s*(\d+)\s*\}\}", replace, str(text or ""))
	return re.sub(
		r"\{\{\s*([a-z][a-z0-9_]*)\s*\}\}",
		lambda match: named_values.get(match.group(1), match.group(0)),
		rendered,
	)


def _validate_template_send_parameters(template_doc, components: list[dict]) -> None:
	parameter_format = str(
		getattr(template_doc, "parameter_format", None) or "POSITIONAL"
	).strip().upper()
	if parameter_format not in {"POSITIONAL", "NAMED"}:
		frappe.throw("Template parameter format is invalid", frappe.ValidationError)
	definitions = _json_list(getattr(template_doc, "components", None))
	for component_type in ("header", "body"):
		definition = _template_component(definitions, component_type.upper())
		text = str(definition.get("text") or "")
		numeric = re.findall(r"\{\{\s*\d+\s*\}\}", text)
		expected = list(dict.fromkeys(
			re.findall(r"\{\{\s*([a-z][a-z0-9_]*)\s*\}\}", text)
		))
		if parameter_format == "POSITIONAL":
			if expected:
				frappe.throw(
					f"POSITIONAL {component_type.upper()} cannot use named placeholders",
					frappe.ValidationError,
				)
			continue
		if numeric:
			frappe.throw(
				f"NAMED {component_type.upper()} cannot use positional placeholders",
				frappe.ValidationError,
			)
		parameters = _template_supplied_parameters(components, component_type)
		if not expected and not parameters:
			continue
		provided = []
		for parameter in parameters:
			if not isinstance(parameter, dict):
				frappe.throw(
					"Named template parameters must be objects",
					frappe.ValidationError,
				)
			name = str(parameter.get("parameter_name") or "").strip()
			if not re.fullmatch(r"[a-z][a-z0-9_]*", name):
				frappe.throw(
					"Every NAMED template text parameter requires parameter_name",
					frappe.ValidationError,
				)
			provided.append(name)
		if len(provided) != len(set(provided)) or set(provided) != set(expected):
			frappe.throw(
				f"NAMED {component_type.upper()} parameters must exactly match: "
				+ ", ".join(expected),
				frappe.ValidationError,
			)


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
	*,
	_batch_context: dict | None = None,
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
		_batch_context=_batch_context,
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
	conversation_names = []
	# Transport readiness is invariant for this bounded batch. Rechecking and
	# decrypting the same Single DocType for every recipient is avoidable work.
	if not outbound_ready(channel.name):
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
		publish_message_changes([
			{"kind": "message", "status": "created", "name": name}
			for name in message_names
		])

	if message_names:
		frappe.enqueue(
			"frappe_whatsapp_core.outbound.deliver_queued_message_batch",
			queue="short",
			enqueue_after_commit=True,
			message_names=message_names,
		)
	return results


def freeze_campaign_template(template_name: str, channel: str | None = None) -> dict:
	"""Return the approved catalog data a campaign must retain for its full run."""
	template = _approved_template(template_name, channel=channel)
	return {
		"name": template.name,
		"account_name": template.account_name,
		"channel": template.channel,
		"template_name": template.template_name,
		"language_code": template.language_code or "en",
		"category": template.category or "",
		"approval_status": template.approval_status,
		"enabled": bool(template.enabled),
		"parameter_format": template.parameter_format or "POSITIONAL",
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
			if _message_transport_endpoint(message) == "marketing_messages":
				_assert_marketing_preference(conversation.name)
			context = {
				"source": "message",
				"message": message.name,
				"conversation": conversation.name,
				"channel": message.channel,
				"require_phone": _message_requires_phone(message),
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
				"endpoint": _message_transport_endpoint(message),
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
			"endpoint": item["endpoint"],
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
			# JetStream now owns this durable work item. That is the WhatsApp
			# client's single-tick boundary; the provider callback may later
			# advance it to Delivered/Read or report a terminal failure.
			_mark_sent(message, relay_result.get("meta_message_id"))
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
		if _message_transport_endpoint(message) == "marketing_messages":
			try:
				_assert_marketing_preference(conversation.name)
			except frappe.ValidationError as exception:
				_mark_failed(message, {"error": str(exception), "retryable": False})
				return
		context = {
			"source": "message",
			"message": message.name,
			"conversation": conversation.name,
			"channel": message.channel,
			"require_phone": _message_requires_phone(message),
		}
		group_id = _group_id(identity)
		recipient = group_id or resolve_recipient_phone(identity, context)
		payload = _message_payload(
			message,
			recipient,
			recipient_type="group" if group_id else "individual",
		)
		endpoint = _message_transport_endpoint(message)
		arguments = {"endpoint": endpoint} if endpoint != "messages" else {}
		result = send_raw(
			message.channel,
			payload,
			message.idempotency_key,
			**arguments,
		)
		# The provider may have committed a status callback during send_raw().
		# Refresh the transaction boundary so the monotonic UPDATE below operates
		# against the current row rather than the pre-request read snapshot.
		frappe.db.rollback()
		if result.get("accepted"):
			# A successful relay response means the message is durably owned by
			# JetStream. Show one tick immediately; waiting for Meta's later result
			# leaves a successfully submitted message incorrectly stuck at Queued.
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
	conversation = batch_context.get("conversation") or frappe.get_doc(
		"WhatsApp Core Conversation", conversation_name
	)
	if not batch_context:
		frappe.has_permission(
			"WhatsApp Core Conversation",
			"read",
			doc=conversation,
			throw=True,
		)
	local_id = f"local:{_client_uuid(client_message_id)}"
	expected_content = {"client_message_id": local_id, **content}
	if client_message_id:
		existing = _message_by_client_id(local_id, channel=conversation.channel)
		if existing:
			return _validated_message_replay(
				existing,
				conversation=conversation,
				message_type=message_type,
				body=body,
				content=expected_content,
			)
	if not batch_context and not outbound_ready(conversation.channel):
		frappe.throw(
			"WhatsApp outbound is not configured for this conversation channel",
			frappe.ValidationError,
		)
	identity = batch_context.get("identity") or frappe.get_cached_doc(
		"WhatsApp Core Identity", conversation.remote_identity
	)
	group_id = _group_id(identity)
	direct_send_category = _direct_send_category(content.get("direct_send_category"))
	if direct_send_category and group_id:
		frappe.throw(
			"Meta Direct Send does not support group conversations",
			frappe.ValidationError,
		)
	if not group_id and _content_requires_phone(message_type, content):
		resolve_recipient_phone(
			identity,
			{
				"operation": "phone_only_message",
				"channel": conversation.channel,
				"require_phone": True,
			},
		)
	if (
		not group_id
		and message_type != "template"
		and not direct_send_category
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
	message_key = hashlib.sha256(
		f"{conversation.channel}:{local_id}".encode()
	).hexdigest()
	try:
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
				expected_content,
				separators=(",", ":"),
				ensure_ascii=False,
			),
			"provider_timestamp": now_datetime(),
			"delivery_status": "Queued",
		}).insert(ignore_permissions=True)
	except (frappe.DuplicateEntryError, frappe.UniqueValidationError):
		if not client_message_id:
			raise
		# A concurrent request can pass the optimistic lookup and win the unique
		# provider/idempotency-key insert. SELECT FOR UPDATE is a current read, so
		# it observes the winner even under MariaDB's repeatable-read isolation.
		existing = _message_by_client_id(
			local_id,
			channel=conversation.channel,
			for_update=True,
		)
		if not existing:
			raise
		return _validated_message_replay(
			existing,
			conversation=conversation,
			message_type=message_type,
			body=body,
			content=expected_content,
		)
	if not batch_context:
		conversation.last_message_at = message.provider_timestamp
		conversation.save(ignore_permissions=True)
	if enqueue_delivery:
		_enqueue_message_delivery(message.name)
	message_payload = _message_response(message)
	if not batch_context:
		publish_message_changes([{
			"kind": "message",
			"status": "created",
			"name": message.name,
		}])
	return message_payload


def _message_by_client_id(
	local_id: str,
	*,
	channel: str,
	for_update: bool = False,
):
	# Delivery replaces the provisional provider_message_id with Meta's wamid.
	# The channel-scoped idempotency key remains immutable for the lifetime of
	# the row, so it is the authoritative replay lookup before and after send.
	idempotency_key = hashlib.sha256(f"{channel}:{local_id}".encode()).hexdigest()
	message_name = frappe.db.get_value(
		"WhatsApp Core Message",
		{"idempotency_key": idempotency_key},
		"name",
		for_update=for_update,
	)
	return frappe.get_doc("WhatsApp Core Message", message_name) if message_name else None


def _validated_message_replay(
	message,
	*,
	conversation,
	message_type: str,
	body: str,
	content: dict,
) -> dict:
	"""Return an exact idempotent replay and reject client-ID reuse."""
	if (
		message.direction != "Outbound"
		or message.conversation != conversation.name
		or message.channel != conversation.channel
		or message.message_type != message_type
		or (message.body or "") != (body or "")
		or _json_dict(message.content) != content
	):
		frappe.throw(
			"Client message ID is already assigned to a different outbound message",
			frappe.ValidationError,
		)
	return _message_response(message)


def _message_response(message) -> dict:
	payload = message.as_dict()
	payload["sender_name"] = (
		frappe.db.get_value("User", message.owner, "full_name") or message.owner
	)
	return payload


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


def _approved_template(template: str, *, channel: str | None = None):
	template_name = str(template or "").strip()
	if not template_name:
		frappe.throw("Template is required")
	record_name = template_name if frappe.db.exists("WhatsApp Core Template", template_name) else None
	if not record_name:
		for identity_field in ("template_name", "template_id"):
			filters = {identity_field: template_name, "enabled": 1}
			if channel:
				filters["channel"] = channel
			matches = frappe.get_all(
				"WhatsApp Core Template", filters=filters, pluck="name", limit_page_length=2
			)
			if len(matches) > 1:
				frappe.throw(
					"Template identity is ambiguous; select its account-scoped record"
				)
			if matches:
				record_name = matches[0]
				break
	if not record_name:
		frappe.throw("Template is not assigned to this site")
	doc = frappe.get_doc("WhatsApp Core Template", record_name)
	if not doc.account_name or not doc.channel:
		frappe.throw("Template has no verified WhatsApp account assignment")
	if channel and doc.channel != channel:
		frappe.throw("Template is assigned to a different WhatsApp account")
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
	direct_send_category = _direct_send_category(content.get("direct_send_category"))
	direct_send_type_allowed = message.message_type == "text" or (
		message.message_type == "interactive" and direct_send_category == "utility"
	)
	if direct_send_category and (not direct_send_type_allowed or recipient_type != "individual"):
		frappe.throw("Invalid durable Meta Direct Send message", frappe.ValidationError)
	if (
		direct_send_category == "authentication"
		and is_business_scoped_user_id(recipient)
	):
		frappe.throw(
			"Authentication Direct Send requires a recipient phone number",
			frappe.ValidationError,
		)
	payload = {
		"messaging_product": "whatsapp",
		"recipient_type": recipient_type,
		"type": message.message_type,
	}
	if recipient_type == "individual" and is_business_scoped_user_id(recipient):
		payload["recipient"] = normalize_business_scoped_user_id(recipient)
	else:
		payload["to"] = recipient
	if direct_send_category:
		payload["category"] = direct_send_category
		ttl_seconds = _direct_send_ttl_seconds(
			content.get("direct_send_ttl_seconds"),
			direct_send_category,
		)
		if ttl_seconds is not None:
			payload["ttl_seconds"] = ttl_seconds
		template_name = _direct_send_template_name(
			content.get("direct_send_template_name"),
			direct_send_category,
		)
		if template_name:
			payload["direct_send_config"] = {"template_name": template_name}
	if message.message_type == "text":
		if direct_send_category and (
			content.get("preview_url") or content.get("context_message_id")
		):
			frappe.throw(
				"Direct Send text does not support previews or reply context",
				frappe.ValidationError,
			)
		payload["text"] = {"body": message.body}
		if content.get("preview_url") is not None:
			payload["text"]["preview_url"] = bool(content["preview_url"])
		if content.get("context_message_id"):
			payload["context"] = {"message_id": content["context_message_id"]}
	elif message.message_type == "template":
		payload["template"] = {
			"name": content["template"],
			"language": {"code": content.get("language") or "en"},
		}
		if content.get("components"):
			payload["template"]["components"] = content["components"]
		for field, value in (content.get("marketing_options") or {}).items():
			if field not in {"product_policy", "message_activity_sharing"}:
				frappe.throw("Unsupported Marketing Messages option", frappe.ValidationError)
			payload[field] = deepcopy(value)
	elif message.message_type == "interactive":
		if content.get("payload"):
			rich_payload = deepcopy(content["payload"])
			if direct_send_category:
				rich_payload = _validate_direct_send_interactive(
					_validate_rich_payload("interactive", rich_payload)
				)
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


def _transport_endpoint(value) -> str:
	endpoint = str(value or "messages").strip().lower().strip("/")
	if endpoint not in {"messages", "marketing_messages"}:
		frappe.throw("Unsupported Meta transport endpoint", frappe.ValidationError)
	return endpoint


def _direct_send_category(value, *, required=False) -> str:
	category = str(value or "").strip().lower()
	if not category and not required:
		return ""
	if category not in {"utility", "authentication"}:
		frappe.throw(
			"Meta Direct Send category must be utility or authentication",
			frappe.ValidationError,
		)
	return category


def _direct_send_ttl_seconds(value, category: str) -> int | None:
	if value in (None, ""):
		return None
	if isinstance(value, bool) or not str(value).strip().isdigit():
		frappe.throw("Direct Send TTL must be an integer number of seconds", frappe.ValidationError)
	ttl_seconds = int(value)
	maximum = 900 if category == "authentication" else 43200
	if not 30 <= ttl_seconds <= maximum:
		frappe.throw(
			f"{category.title()} Direct Send TTL must be between 30 and {maximum} seconds",
			frappe.ValidationError,
		)
	return ttl_seconds


def _direct_send_template_name(value, category: str) -> str:
	template_name = str(value or "").strip()
	if not template_name:
		return ""
	if category != "utility":
		frappe.throw(
			"Business-named Direct Send templates support utility messages only",
			frappe.ValidationError,
		)
	if len(template_name) > 512 or not re.fullmatch(r"[a-z0-9_]+", template_name):
		frappe.throw(
			"Direct Send template name must contain only lowercase letters, numbers, and underscores (maximum 512 characters)",
			frappe.ValidationError,
		)
	return template_name


def _message_transport_endpoint(message) -> str:
	return _transport_endpoint(_json_dict(message.content).get("transport_endpoint"))


def _template_requires_phone(content: dict) -> bool:
	template_record = str(content.get("template_record") or "").strip()
	if not template_record:
		return False
	category = frappe.db.get_value("WhatsApp Core Template", template_record, "category")
	return str(category or "").upper() == "AUTHENTICATION"


def _message_requires_phone(message) -> bool:
	return _content_requires_phone(message.message_type, _json_dict(message.content))


def _content_requires_phone(message_type: str, content: dict) -> bool:
	return (
		message_type == "template" and _template_requires_phone(content)
	) or (
		_direct_send_category(content.get("direct_send_category"))
		== "authentication"
	)


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
			"button", "cta_url", "list", "product", "product_list", "catalog_message",
			"flow", "location_request_message", "address_message", "order_details",
			"order_status",
		}:
			frappe.throw("Unsupported interactive message type", frappe.ValidationError)
		if not isinstance(result.get("action"), dict):
			frappe.throw("Interactive message requires an action object", frappe.ValidationError)
	return result


def _validate_direct_send_interactive(payload: dict) -> dict:
	"""Validate the currently documented Direct Send interactive subset.

	This deliberately accepts only the established Cloud API CTA URL and reply
	button wire shapes. Direct Send's newer mixed-button samples are not exposed
	until Meta publishes an unambiguous request schema.
	"""
	_allowed_keys(payload, {"type", "header", "body", "footer", "action"}, "interactive")
	interactive_type = str(payload.get("type") or "")
	if interactive_type not in {"cta_url", "button"}:
		frappe.throw(
			"Direct Send interactive type must be cta_url or button",
			frappe.ValidationError,
		)
	_validate_direct_send_text_object(payload.get("body"), "body", maximum=1024, required=True)
	if payload.get("footer") is not None:
		_validate_direct_send_text_object(payload["footer"], "footer", maximum=60, required=True)
	if payload.get("header") is not None:
		_validate_direct_send_header(payload["header"])
	action = payload.get("action")
	if not isinstance(action, dict):
		frappe.throw("Direct Send interactive action must be an object", frappe.ValidationError)
	if interactive_type == "cta_url":
		_validate_direct_send_cta_action(action)
	else:
		_validate_direct_send_reply_action(action)
	return payload


def _validate_direct_send_text_object(
	value, label: str, *, maximum: int, required: bool
) -> None:
	if not isinstance(value, dict):
		frappe.throw(f"Direct Send {label} must be an object", frappe.ValidationError)
	_allowed_keys(value, {"text"}, label)
	text = value.get("text")
	if (
		not isinstance(text, str)
		or text != text.strip()
		or (required and not text)
		or len(text) > maximum
	):
		frappe.throw(
			f"Direct Send {label} text must contain 1 to {maximum} characters",
			frappe.ValidationError,
		)


def _validate_direct_send_header(header) -> None:
	if not isinstance(header, dict):
		frappe.throw("Direct Send header must be an object", frappe.ValidationError)
	header_type = str(header.get("type") or "")
	if header_type == "text":
		_allowed_keys(header, {"type", "text"}, "header")
		text = header.get("text")
		if not isinstance(text, str) or text != text.strip() or not text or len(text) > 60:
			frappe.throw(
				"Direct Send header text must contain 1 to 60 characters",
				frappe.ValidationError,
			)
		return
	if header_type not in {"image", "video", "document"}:
		frappe.throw(
			"Direct Send header type must be text, image, video, or document",
			frappe.ValidationError,
		)
	_allowed_keys(header, {"type", header_type}, "header")
	media = header.get(header_type)
	if not isinstance(media, dict):
		frappe.throw(f"Direct Send {header_type} header is required", frappe.ValidationError)
	allowed = {"id", "link", "filename"} if header_type == "document" else {"id", "link"}
	_allowed_keys(media, allowed, f"{header_type} header")
	for field in set(media) & {"id", "link", "filename"}:
		value = media[field]
		if not isinstance(value, str) or value != value.strip():
			frappe.throw(
				f"Direct Send {header_type} header {field} must be an exact string",
				frappe.ValidationError,
			)
	sources = [key for key in ("id", "link") if media.get(key)]
	if not sources:
		frappe.throw(
			f"Direct Send {header_type} header requires a media id or link",
			frappe.ValidationError,
		)
	if "link" in sources:
		_validate_direct_send_url(media["link"], label=f"{header_type} header link")
	if len(str(media.get("id") or "")) > 512:
		frappe.throw("Direct Send media id is too long", frappe.ValidationError)
	if len(str(media.get("filename") or "")) > 240:
		frappe.throw("Direct Send document filename is too long", frappe.ValidationError)


def _validate_direct_send_cta_action(action: dict) -> None:
	_allowed_keys(action, {"name", "parameters"}, "CTA action")
	if action.get("name") != "cta_url":
		frappe.throw("Direct Send CTA action.name must be cta_url", frappe.ValidationError)
	parameters = action.get("parameters")
	if not isinstance(parameters, dict):
		frappe.throw("Direct Send CTA parameters must be an object", frappe.ValidationError)
	_allowed_keys(parameters, {"display_text", "url"}, "CTA parameters")
	display_text = parameters.get("display_text")
	if (
		not isinstance(display_text, str)
		or display_text != display_text.strip()
		or not display_text
		or len(display_text) > 20
	):
		frappe.throw(
			"Direct Send CTA display text must contain 1 to 20 characters",
			frappe.ValidationError,
		)
	_validate_direct_send_url(parameters.get("url"), label="CTA URL")


def _validate_direct_send_reply_action(action: dict) -> None:
	_allowed_keys(action, {"buttons"}, "reply action")
	buttons = action.get("buttons")
	if not isinstance(buttons, list) or not 1 <= len(buttons) <= 3:
		frappe.throw("Direct Send reply messages require 1 to 3 buttons", frappe.ValidationError)
	identifiers = set()
	titles = set()
	for button in buttons:
		if not isinstance(button, dict):
			frappe.throw("Direct Send reply button must be an object", frappe.ValidationError)
		_allowed_keys(button, {"type", "reply"}, "reply button")
		if button.get("type") != "reply":
			frappe.throw("Direct Send button type must be reply", frappe.ValidationError)
		reply = button.get("reply")
		if not isinstance(reply, dict):
			frappe.throw("Direct Send button.reply must be an object", frappe.ValidationError)
		_allowed_keys(reply, {"id", "title"}, "button.reply")
		identifier = reply.get("id")
		title = reply.get("title")
		if (
			not isinstance(identifier, str)
			or identifier != identifier.strip()
			or not identifier
			or len(identifier) > 256
		):
			frappe.throw("Direct Send reply id must contain 1 to 256 characters", frappe.ValidationError)
		if identifier in identifiers:
			frappe.throw("Direct Send reply ids must be unique", frappe.ValidationError)
		identifiers.add(identifier)
		if (
			not isinstance(title, str)
			or title != title.strip()
			or not title
			or len(title) > 20
		):
			frappe.throw("Direct Send reply title must contain 1 to 20 characters", frappe.ValidationError)
		if title in titles:
			frappe.throw("Direct Send reply titles must be unique", frappe.ValidationError)
		titles.add(title)


def _validate_direct_send_url(value, *, label: str) -> None:
	if not isinstance(value, str) or value != value.strip():
		frappe.throw(f"{label} must be an exact string", frappe.ValidationError)
	url = value
	if len(url) > 2000:
		frappe.throw(f"{label} is too long", frappe.ValidationError)
	parsed = urlsplit(url)
	try:
		parsed.port
	except ValueError:
		frappe.throw(f"{label} contains an invalid port", frappe.ValidationError)
	if (
		parsed.scheme != "https"
		or not parsed.hostname
		or parsed.username
		or parsed.password
	):
		frappe.throw(f"{label} must be an absolute HTTPS URL", frappe.ValidationError)
	try:
		ipaddress.ip_address(parsed.hostname)
	except ValueError:
		return
	frappe.throw(f"{label} cannot use an IP-address host", frappe.ValidationError)


def _allowed_keys(value: dict, allowed: set[str], label: str) -> None:
	unknown = set(value) - allowed
	if unknown:
		frappe.throw(
			f"Unsupported Direct Send {label} field: {sorted(unknown)[0]}",
			frappe.ValidationError,
		)


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
	previous_status = frappe.db.get_value(
		"WhatsApp Core Message", message.name, "delivery_status"
	)
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
	if current.delivery_status != previous_status:
		enqueue_delivery_status_handlers({
			"message_name": message.name,
			"delivery_status": current.delivery_status,
		})
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
	previous_status = frappe.db.get_value(
		"WhatsApp Core Message", message.name, "delivery_status"
	)
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
	if current.delivery_status != previous_status:
		enqueue_delivery_status_handlers({
			"message_name": message.name,
			"delivery_status": current.delivery_status,
		})
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
	publish_message_changes([{
		"kind": "status",
		"status": "updated",
		"name": message.name,
	}])


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
