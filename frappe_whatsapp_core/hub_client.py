"""Authenticated Core client for the central WhatsApp Integration Hub."""

from __future__ import annotations

import json
import time
from zoneinfo import ZoneInfo

import frappe
from frappe.utils import get_datetime, get_system_timezone

from frappe_whatsapp_core import safe_http as requests
from frappe_whatsapp_core.network_security import validate_service_origin

_session = requests.Session()
_HUB_RELAY_GATEWAY_METHODS = {
	"/v1/outbound": "frappe_whatsapp_hub.frappe_whatsapp_hub.api.gateway.outbound",
	"/v1/outbound/batch": (
		"frappe_whatsapp_hub.frappe_whatsapp_hub.api.gateway.outbound_batch"
	),
	"/v1/commands/outbound": (
		"frappe_whatsapp_hub.frappe_whatsapp_hub.api.gateway.outbound_command"
	),
}


def call_management(method: str, args: dict | None = None) -> dict:
	"""Call an authenticated Integration Hub management API.

	Core never receives Meta credentials. The Hub resolves and audits the Meta
	operation, while this site keeps only its configured Hub account mapping.
	"""
	method = str(method or "").strip()
	allowed_prefix = "frappe_whatsapp_integration.frappe_whatsapp_hub.api."
	if not method.startswith(allowed_prefix):
		frappe.throw("Invalid WhatsApp Hub management method", frappe.ValidationError)
	settings = get_settings()
	url = f"{_hub_url(settings)}/api/method/{method}"
	try:
		response = _session.post(
			url,
			allow_redirects=False,
			headers=settings.get_hub_auth_headers(),
			json=args or {},
			timeout=_request_timeout(settings),
		)
	except requests.RequestException as exception:
		frappe.throw(f"WhatsApp Hub is unavailable: {exception}", frappe.ValidationError)
	try:
		body = response.json()
	except ValueError:
		body = {"raw": response.text[:2000]}
	result = body.get("message", body) if isinstance(body, dict) else body
	if not response.ok:
		frappe.throw(_error_message(result), frappe.ValidationError)
	if not isinstance(result, dict):
		frappe.throw("WhatsApp Hub returned an invalid response", frappe.ValidationError)
	return result


def mark_message_read(
	channel: str,
	message_id: str,
	*,
	typing_indicator: bool = False,
) -> dict:
	"""Queue provider read/typing state through the managed Hub data plane."""
	get_settings(outbound=True)
	message_id = str(message_id or "").strip()
	if not message_id or message_id.startswith("local:"):
		frappe.throw("A provider inbound message id is required", frappe.ValidationError)
	result = send_raw(
			channel,
			{
				"messaging_product": "whatsapp",
				"status": "read",
				"message_id": message_id,
				**(
					{"typing_indicator": {"type": "text"}}
					if typing_indicator
					else {}
				),
			},
			(
				f"typing:{message_id}:{time.time_ns()}"
				if typing_indicator
				else f"read:{message_id}"
			),
		)
	if result.get("accepted"):
		return result.get("result") or {
			"success": True,
			"status": result.get("status") or "queued",
		}
	return {
		"success": False,
		"error": result.get("error") or "Relay did not accept read state",
		"retryable": bool(result.get("retryable")),
	}


def send_raw(
	channel: str,
	payload: dict,
	idempotency_key: str,
	*,
	endpoint: str = "messages",
) -> dict:
	endpoint = _outbound_endpoint(endpoint)
	settings = get_settings(outbound=True)
	url = _gateway_endpoint(settings, "/v1/outbound")
	request_body = {
		"account_name": settings.get_account_name(channel),
		"payload": payload,
		"idempotency_key": idempotency_key,
	}
	if endpoint != "messages":
		request_body["endpoint"] = endpoint
	try:
		response = _session.post(
			url,
			allow_redirects=False,
			headers=settings.get_hub_auth_headers(),
			json=request_body,
			timeout=_request_timeout(settings),
		)
	except requests.RequestException as exception:
		return {
			"accepted": False,
			"retryable": True,
			"error": str(exception),
		}

	try:
		body = response.json()
	except ValueError:
		body = {"raw": response.text[:2000]}
	result = body.get("message", body) if isinstance(body, dict) else {}
	if not response.ok:
		return {
			"accepted": False,
			"retryable": response.status_code >= 500,
			"status_code": response.status_code,
			"error": _error_message(result),
		}
	if not isinstance(result, dict):
		return {
			"accepted": False,
			"retryable": True,
			"error": "WhatsApp Hub returned an invalid response",
		}
	if not result.get("success"):
		return {
			"accepted": False,
			"retryable": _retryable_result(result),
			"status_code": result.get("status_code"),
			"error": _error_message(result),
			"result": result,
		}
	return {
		"accepted": True,
		"result": result,
		"status": result.get("status") or "sent",
		"meta_message_id": _provider_message_id(result),
	}


def send_batch(messages: list[dict]) -> dict:
	"""Submit at most 40 independent sends to the Hub in one request."""
	if not isinstance(messages, list) or not 1 <= len(messages) <= 40:
		frappe.throw(
			"WhatsApp Hub batches require between 1 and 40 messages",
			frappe.ValidationError,
		)
	settings = get_settings(outbound=True)
	normalized = []
	for message in messages:
		channel = str(message.get("channel") or "").strip()
		payload = message.get("payload")
		idempotency_key = str(message.get("idempotency_key") or "").strip()
		endpoint = _outbound_endpoint(message.get("endpoint"))
		if not channel or not isinstance(payload, dict) or not idempotency_key:
			frappe.throw(
				"Every Hub batch item requires channel, payload, and idempotency_key",
				frappe.ValidationError,
			)
		item = {
			"account_name": settings.get_account_name(channel),
			"payload": payload,
			"idempotency_key": idempotency_key,
		}
		if endpoint != "messages":
			item["endpoint"] = endpoint
		normalized.append(item)

	url = _gateway_endpoint(settings, "/v1/outbound/batch")
	try:
		response = _session.post(
			url,
			allow_redirects=False,
			headers=settings.get_hub_auth_headers(),
			json={"messages": normalized},
			timeout=_request_timeout(settings),
		)
	except requests.RequestException as exception:
		return {
			"accepted": False,
			"retryable": True,
			"error": str(exception),
		}

	try:
		body = response.json()
	except ValueError:
		body = {"raw": response.text[:2000]}
	result = body.get("message", body) if isinstance(body, dict) else {}
	if not response.ok:
		return {
			"accepted": False,
			"retryable": response.status_code >= 500,
			"status_code": response.status_code,
			"error": _error_message(result),
		}
	if not isinstance(result, dict) or not isinstance(result.get("items"), list):
		return {
			"accepted": False,
			"retryable": True,
			"error": "WhatsApp Hub returned an invalid batch response",
		}
	return {
		"accepted": True,
		"success": bool(result.get("success")),
		"queued": int(result.get("queued") or 0),
		"duplicates": int(result.get("duplicates") or 0),
		"items": result["items"],
	}


def publish_outbound_command(
	command_id: str,
	messages: list[dict],
	*,
	execute_at=None,
) -> dict:
	"""Publish one approved campaign/automation command to the Go runtime.

	Frappe resolves management definitions into immutable payloads once. Go owns
	scheduling, provider execution, idempotency, retry and operational state.
	"""
	command_id = str(command_id or "").strip()
	if not command_id:
		frappe.throw("Runtime command_id is required", frappe.ValidationError)
	if not isinstance(messages, list) or not 1 <= len(messages) <= 5_000:
		frappe.throw(
			"A runtime command requires between 1 and 5000 messages",
			frappe.ValidationError,
		)
	settings = get_settings(outbound=True)
	normalized = []
	for message in messages:
		channel = str(message.get("channel") or "").strip()
		payload = message.get("payload")
		idempotency_key = str(message.get("idempotency_key") or "").strip()
		endpoint = _outbound_endpoint(message.get("endpoint"))
		if not channel or not isinstance(payload, dict) or not idempotency_key:
			frappe.throw(
				"Every runtime message requires channel, payload, and idempotency_key",
				frappe.ValidationError,
			)
		item = {
			"account_name": settings.get_account_name(channel),
			"payload": payload,
			"idempotency_key": idempotency_key,
		}
		if endpoint != "messages":
			item["endpoint"] = endpoint
		normalized.append(item)
	request_body = {"command_id": command_id, "messages": normalized}
	if execute_at:
		scheduled_for = get_datetime(execute_at)
		if scheduled_for.tzinfo is None:
			scheduled_for = scheduled_for.replace(tzinfo=ZoneInfo(get_system_timezone()))
		request_body["execute_at"] = scheduled_for.isoformat()
	try:
		response = _session.post(
			_gateway_endpoint(settings, "/v1/commands/outbound"),
			allow_redirects=False,
			headers=settings.get_hub_auth_headers(),
			json=request_body,
			timeout=max(_request_timeout(settings), 120),
		)
	except requests.RequestException as exception:
		return {"accepted": False, "retryable": True, "error": str(exception)}
	try:
		result = response.json()
	except ValueError:
		result = {"raw": response.text[:2000]}
	if not response.ok or not isinstance(result, dict) or not result.get("success"):
		return {
			"accepted": False,
			"retryable": response.status_code >= 500,
			"status_code": response.status_code,
			"error": _error_message(result),
		}
	return {"accepted": True, **result}


def get_settings(*, outbound: bool = False):
	settings = frappe.get_single("WhatsApp Core Settings")
	if not settings.enabled:
		frappe.throw("WhatsApp Core is not enabled on this site")
	if outbound and not settings.outbound_enabled:
		frappe.throw("Outbound WhatsApp messages are disabled on this site")
	if not settings.hub_url:
		frappe.throw("WhatsApp Core Hub URL is not configured")
	return settings


def _outbound_endpoint(value) -> str:
	endpoint = str(value or "messages").strip().lower().strip("/")
	if endpoint not in {"messages", "marketing_messages"}:
		frappe.throw("Unsupported Meta transport endpoint", frappe.ValidationError)
	return endpoint


def connection_status() -> dict:
	settings = frappe.get_single("WhatsApp Core Settings")
	return {
		"enabled": bool(settings.enabled),
		"outbound_enabled": bool(settings.outbound_enabled),
		"hub_url": settings.hub_url or "",
		"data_plane": "hub_gateway",
		"credentials_configured": bool(
			settings.get_password("api_key", raise_exception=False)
			and settings.get_password("api_secret", raise_exception=False)
		),
		"account_count": len(settings.accounts),
	}


def _request_timeout(settings) -> int:
	return max(2, min(int(settings.request_timeout or 30), 120))


def _gateway_endpoint(settings, path: str) -> str:
	"""Resolve one of the fixed Hub-to-relay gateway methods."""
	path = f"/{str(path or '').strip('/')}"
	method = _HUB_RELAY_GATEWAY_METHODS.get(path)
	if not method:
		frappe.throw("Unsupported Hub relay gateway operation", frappe.ValidationError)
	return f"{_hub_url(settings)}/api/method/{method}"


def _hub_url(settings) -> str:
	return validate_service_origin(settings.hub_url, label="Hub URL")


def _error_message(result) -> str:
	if not isinstance(result, dict):
		return "WhatsApp Hub request failed"
	error = (
		result.get("error")
		or result.get("message")
		or _server_message(result.get("_server_messages"))
		or result.get("exception")
		or result.get("exc_type")
		or result.get("raw")
	)
	if isinstance(error, dict):
		return (
			error.get("message")
			or error.get("error_user_msg")
			or str(error)
		)
	return str(error or "WhatsApp Hub request failed")


def _server_message(value) -> str:
	"""Extract Frappe's user-safe server message without returning a traceback."""
	if not value:
		return ""
	try:
		messages = json.loads(value) if isinstance(value, str) else value
	except (TypeError, ValueError):
		return ""
	if not isinstance(messages, list):
		messages = [messages]
	for item in messages:
		try:
			item = json.loads(item) if isinstance(item, str) else item
		except (TypeError, ValueError):
			continue
		if isinstance(item, dict) and item.get("message"):
			return str(item["message"])
	return ""


def _retryable_result(result: dict) -> bool:
	status_code = int(result.get("status_code") or 0)
	if status_code >= 500:
		return True
	status = str(result.get("status") or "").lower()
	return status in {"queued", "retrying", "unavailable"}


def _provider_message_id(result: dict) -> str | None:
	if result.get("meta_message_id"):
		return result["meta_message_id"]
	messages = result.get("messages") or []
	if messages and isinstance(messages[0], dict):
		return messages[0].get("id")
	response = result.get("response") or {}
	messages = response.get("messages") or []
	if messages and isinstance(messages[0], dict):
		return messages[0].get("id")
	return None
