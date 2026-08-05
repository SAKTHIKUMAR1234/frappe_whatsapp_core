"""Core-owned optimistic outbound messages and crash-safe Hub submission."""

from __future__ import annotations

import hashlib
import json
import uuid
from copy import deepcopy

import frappe
from frappe.utils import add_to_date, now_datetime

from frappe_whatsapp_core.hub_client import (
	connection_status,
	send_batch as send_hub_batch,
	send_raw,
)
from frappe_whatsapp_core.materializer import (
	get_or_create_conversation,
	get_or_create_identity,
	normalize_phone,
)
from frappe_whatsapp_core.permissions import require_core_access


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
	phone_number: str,
	display_name: str = "",
) -> dict:
	channel_doc = frappe.get_doc("WhatsApp Core Channel", channel)
	if not channel_doc.enabled:
		frappe.throw("The selected WhatsApp channel is disabled")
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
	identity = get_or_create_identity(normalized)
	if display_name and identity.display_value in {"", identity.normalized_value}:
		identity.display_value = display_name.strip()[:140]
		identity.save(ignore_permissions=True)
	conversation = get_or_create_conversation(channel_doc, identity)
	return {
		"conversation": conversation.name,
		"identity": identity.name,
		"phone_number": identity.normalized_value,
	}


@frappe.whitelist()
@require_core_access()
def queue_text(
	conversation_name: str,
	body: str,
	source: str = "Core UI",
	context_message_id: str | None = None,
) -> dict:
	return queue_text_internal(
		conversation_name,
		body,
		source,
		context_message_id=context_message_id,
	)


def queue_text_internal(
	conversation_name: str,
	body: str,
	source: str = "Core",
	*,
	context_message_id: str | None = None,
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
	)


@frappe.whitelist()
@require_core_access()
def queue_rich(
	conversation_name: str,
	message_type: str,
	payload: dict | str,
	body: str = "",
	source: str = "Core UI",
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
	preview = str(body or _rich_message_body(message_type, normalized)).strip()[:4096]
	return _queue_message(
		conversation_name,
		message_type,
		preview,
		{"payload": normalized, "source": source},
	)


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
) -> dict:
	template_doc = _approved_template(template)
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
	return _queue_message(
		conversation_name,
		"template",
		template_doc.template_name,
		{
			"template": template_doc.template_name,
			"template_record": template_doc.name,
			"language": language_code,
			"components": components,
			"source": source,
		},
		enqueue_delivery=enqueue_delivery,
	)


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
	message = queue_template_internal(
		conversation.name,
		campaign.template,
		source=f"Campaign:{campaign.name}",
	)
	return {
		"message": message.name,
		"conversation": conversation.name,
	}


def queue_campaign_batch(campaign, recipients) -> dict:
	"""Create optimistic messages, then submit one batch of up to 40 to the Hub."""
	if not recipients:
		return {}
	if len(recipients) > 40:
		frappe.throw(
			"A WhatsApp campaign transport batch cannot exceed 40 recipients",
			frappe.ValidationError,
		)
	channel = frappe.get_cached_doc("WhatsApp Core Channel", campaign.channel)
	template = frappe.get_cached_doc("WhatsApp Core Template", campaign.template)
	results = {}
	submissions = []
	for recipient in recipients:
		try:
			identity = frappe.get_cached_doc(
				"WhatsApp Core Identity",
				recipient.identity,
			)
			conversation = get_or_create_conversation(channel, identity)
			personalization = _json_dict(recipient.personalization)
			message = queue_template_internal(
				conversation.name,
				template.name,
				template.language_code,
				personalization.get("components") or [],
				source=f"Campaign:{campaign.name}",
				enqueue_delivery=False,
			)
			recipient_phone = resolve_recipient_phone(
				identity,
				{
					"source": "campaign",
					"campaign": campaign.name,
					"recipient": recipient.name,
					"conversation": conversation.name,
				},
			)
			submissions.append({
				"recipient": recipient.name,
				"message": message.name,
				"channel": message.channel,
				"payload": _message_payload(
					message,
					recipient_phone,
				),
				"idempotency_key": message.idempotency_key,
			})
		except Exception as exception:
			results[recipient.name] = {
				"success": False,
				"error": str(exception),
			}

	if not submissions:
		return results

	hub_result = send_hub_batch([
		{
			"channel": item["channel"],
			"payload": item["payload"],
			"idempotency_key": item["idempotency_key"],
		}
		for item in submissions
	])
	items_by_key = {
		item.get("idempotency_key"): item
		for item in hub_result.get("items") or []
		if isinstance(item, dict) and item.get("idempotency_key")
	}
	for submission in submissions:
		message = frappe.get_doc(
			"WhatsApp Core Message",
			submission["message"],
		)
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
		results[submission["recipient"]] = {
			"success": True,
			"message": message.name,
			"conversation": message.conversation,
		}
	return results


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
		recipient_phone = resolve_recipient_phone(
			identity,
			{
				"source": "message",
				"message": message.name,
				"conversation": conversation.name,
				"channel": message.channel,
			},
		)
		payload = _message_payload(message, recipient_phone)
		result = send_raw(
			message.channel,
			payload,
			message.idempotency_key,
		)
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
	for message_name in frappe.get_all(
		"WhatsApp Core Message",
		filters={
			"direction": "Outbound",
			"delivery_status": "Queued",
			"modified": ["<=", cutoff],
		},
		pluck="name",
		order_by="modified asc",
		limit_page_length=max(1, min(int(limit), 2000)),
	):
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
) -> dict:
	if not outbound_ready():
		frappe.throw(
			"WhatsApp outbound is not fully configured and enabled",
			frappe.ValidationError,
		)
	conversation = frappe.get_doc(
		"WhatsApp Core Conversation",
		conversation_name,
	)
	frappe.has_permission(
		"WhatsApp Core Conversation",
		"read",
		doc=conversation,
		throw=True,
	)
	if (
		message_type != "template"
		and not _within_service_window(conversation.name)
	):
		frappe.throw(
			"An approved template is required outside the 24-hour customer service window",
			frappe.ValidationError,
		)
	_run_preflight_hooks(
		conversation=conversation,
		message_type=message_type,
		content=content,
	)
	local_id = f"local:{uuid.uuid4()}"
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
	conversation.last_message_at = message.provider_timestamp
	conversation.save(ignore_permissions=True)
	if enqueue_delivery:
		_enqueue_message_delivery(message.name)
	frappe.publish_realtime(
		"whatsapp_core_message",
		{"conversation": conversation.name, "message": message.as_dict()},
		after_commit=True,
	)
	return message.as_dict()


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


def _message_payload(message, recipient: str) -> dict:
	content = _json_dict(message.content)
	payload = {
		"messaging_product": "whatsapp",
		"recipient_type": "individual",
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
	if provider_message_id:
		message.provider_message_id = provider_message_id
	message.delivery_status = "Sent"
	message.failure = None
	message.save(ignore_permissions=True)
	_publish_status(message)


def _record_retryable_submission(message, result: dict) -> None:
	content = _json_dict(message.content)
	submission = content.setdefault("submission", {})
	submission["attempts"] = int(submission.get("attempts") or 0) + 1
	submission["last_attempt_at"] = str(now_datetime())
	submission["last_error"] = str(result.get("error") or "")[:500]
	message.content = json.dumps(
		content,
		separators=(",", ":"),
		ensure_ascii=False,
	)
	message.save(ignore_permissions=True)


def _mark_failed(message, failure: dict) -> None:
	message.delivery_status = "Failed"
	message.failure = json.dumps(
		failure,
		separators=(",", ":"),
		ensure_ascii=False,
	)
	message.save(ignore_permissions=True)
	_publish_status(message)


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
