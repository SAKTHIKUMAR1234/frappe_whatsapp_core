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

_CURRENT_HUB_API = "frappe_whatsapp_hub.frappe_whatsapp_hub.api"
_LEGACY_HUB_API = "frappe_whatsapp_integration.frappe_whatsapp_hub.api"

# This is the complete Core-to-Hub control-plane contract. A caller cannot turn
# call_management into a generic authenticated Frappe or Meta proxy.
_MANAGEMENT_METHODS = frozenset({
	"calling.build_call_deep_link",
	"calling.get_call_settings",
	"calling.update_call_settings",
	"flow_endpoint.provision",
	"flow_endpoint.status",
	"groups.approve_join_requests",
	"groups.create_group",
	"groups.delete_group",
	"groups.get_group",
	"groups.get_invite_link",
	"groups.list_groups",
	"groups.list_join_requests",
	"groups.reject_join_requests",
	"groups.remove_participants",
	"groups.reset_invite_link",
	"groups.update_group",
	"groups.update_group_picture",
	"meta_flows.create_flow",
	"meta_flows.delete_flow",
	"meta_flows.deprecate_flow",
	"meta_flows.get_business_public_key",
	"meta_flows.get_flow",
	"meta_flows.get_flow_json",
	"meta_flows.list_flow_assets",
	"meta_flows.list_flows",
	"meta_flows.migrate_flows",
	"meta_flows.publish_flow",
	"meta_flows.set_business_public_key",
	"meta_flows.update_flow_metadata",
	"meta_flows.upload_flow_json",
	"onboarding.get_account_meta_context",
	"onboarding.list_site_accounts",
	"templates.upsert_template_for_site",
})

# Operational routes are fixed here and in the Go server's mux. Only these
# paths may bypass Frappe; no URL or Meta resource is accepted from callers.
_RELAY_OPERATIONS = {
	"call_action": ("POST", "/v1/meta/calls"),
	"call_permission": ("GET", "/v1/meta/call-permissions"),
	"command": ("POST", "/v1/commands/outbound"),
	"media_content": ("GET", "/v1/meta/media/{media_id}/content"),
	"media_delete": ("DELETE", "/v1/meta/media/{media_id}"),
	"media_info": ("GET", "/v1/meta/media/{media_id}"),
	"media_upload": ("POST", "/v1/meta/media"),
	"outbound": ("POST", "/v1/outbound"),
	"outbound_batch": ("POST", "/v1/outbound/batch"),
}


def call_management(method: str, args: dict | None = None) -> dict:
	"""Call an authenticated Integration Hub management API.

	Core never receives Meta credentials. The Hub resolves and audits the Meta
	operation, while this site keeps only its configured Hub account mapping.
	"""
	method = str(method or "").strip()
	suffix = ""
	for prefix in (_CURRENT_HUB_API, _LEGACY_HUB_API):
		if method.startswith(f"{prefix}."):
			suffix = method[len(prefix) + 1:]
			break
	if suffix not in _MANAGEMENT_METHODS:
		frappe.throw("Invalid WhatsApp Hub management method", frappe.ValidationError)
	settings = get_settings()
	url = f"{_hub_url(settings)}/api/method/{_CURRENT_HUB_API}.{suffix}"
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
	"""Queue provider read/typing state on the Go data plane when configured."""
	message_id = str(message_id or "").strip()
	if (
		not message_id.startswith("wamid.")
		or len(message_id) > 512
		or any(character.isspace() for character in message_id)
	):
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
	request_body = {
		"account_name": settings.get_account_name(channel),
		"payload": payload,
		"idempotency_key": idempotency_key,
	}
	if endpoint != "messages":
		request_body["endpoint"] = endpoint
	try:
		response = _relay_request(
			"outbound",
			settings=settings,
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

	try:
		response = _relay_request(
			"outbound_batch",
			settings=settings,
			headers=settings.get_hub_auth_headers(),
			json={"messages": normalized},
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
		response = _relay_request(
			"command",
			settings=settings,
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


def send_account_raw(
	account_name: str,
	payload: dict,
	idempotency_key: str | None = None,
	*,
	endpoint: str = "messages",
) -> dict:
	"""Queue an operational message for an already resolved Hub account."""
	settings = get_settings(outbound=True)
	account_name = _mapped_account_name(settings, account_name)
	request_body = {"account_name": account_name, "payload": payload}
	if idempotency_key:
		request_body["idempotency_key"] = str(idempotency_key)
	endpoint = _outbound_endpoint(endpoint)
	if endpoint != "messages":
		request_body["endpoint"] = endpoint
	return _relay_json_operation(
		"outbound",
		settings=settings,
		json=request_body,
	)


def call_action(account_name: str, payload: dict) -> dict:
	settings = get_settings(outbound=True)
	return _relay_json_operation(
		"call_action",
		settings=settings,
		json={
			"account_name": _mapped_account_name(settings, account_name),
			"payload": payload,
		},
	)


def get_call_permission(
	account_name: str,
	*,
	user_wa_id: str | None = None,
	recipient: str | None = None,
) -> dict:
	settings = get_settings(relay=True)
	parameters = {
		"account_name": _mapped_account_name(settings, account_name),
	}
	if user_wa_id:
		parameters["user_wa_id"] = str(user_wa_id)
	if recipient:
		parameters["recipient"] = str(recipient)
	return _relay_json_operation(
		"call_permission",
		settings=settings,
		params=parameters,
	)


def upload_media(
	account_name: str,
	content: bytes,
	*,
	content_type: str,
	filename: str,
	use_case: str | None = None,
	description: str | None = None,
) -> dict:
	settings = get_settings(outbound=True)
	if not isinstance(content, bytes) or not content:
		frappe.throw("Media content is empty", frappe.ValidationError)
	if len(content) > 100 * 1024 * 1024:
		frappe.throw("Media exceeds the 100 MB relay limit", frappe.ValidationError)
	parameters = {
		"account_name": _mapped_account_name(settings, account_name),
		"filename": str(filename or "file"),
	}
	if use_case:
		parameters["use_case"] = str(use_case)
	if description:
		parameters["description"] = str(description)
	return _relay_json_operation(
		"media_upload",
		settings=settings,
		params=parameters,
		data=content,
		headers={
			**settings.get_hub_auth_headers(),
			"Content-Type": str(content_type or "application/octet-stream"),
		},
		timeout=max(_request_timeout(settings), 120),
	)


def get_media_url(account_name: str, media_id: str) -> dict:
	settings = get_settings(relay=True)
	return _relay_json_operation(
		"media_info",
		settings=settings,
		media_id=media_id,
		params={"account_name": _mapped_account_name(settings, account_name)},
	)


def download_media(account_name: str, media_id: str) -> dict:
	settings = get_settings(relay=True)
	try:
		response = _relay_request(
			"media_content",
			settings=settings,
			media_id=media_id,
			params={"account_name": _mapped_account_name(settings, account_name)},
			headers=settings.get_hub_auth_headers(),
			timeout=max(_request_timeout(settings), 120),
		)
	except requests.RequestException as exception:
		frappe.throw(f"WhatsApp relay is unavailable: {exception}", frappe.ValidationError)
	if not response.ok:
		frappe.throw(_response_error(response), frappe.ValidationError)
	return {
		"success": True,
		"content": response.content,
		"mime_type": response.headers.get("Content-Type", "application/octet-stream"),
	}


def delete_media(account_name: str, media_id: str) -> dict:
	settings = get_settings(outbound=True)
	return _relay_json_operation(
		"media_delete",
		settings=settings,
		media_id=media_id,
		params={"account_name": _mapped_account_name(settings, account_name)},
	)


def _relay_json_operation(operation: str, *, settings, **kwargs) -> dict:
	try:
		response = _relay_request(
			operation,
			settings=settings,
			headers=kwargs.pop("headers", settings.get_hub_auth_headers()),
			**kwargs,
		)
	except requests.RequestException as exception:
		frappe.throw(f"WhatsApp relay is unavailable: {exception}", frappe.ValidationError)
	try:
		result = response.json()
	except ValueError:
		result = {"raw": response.text[:2000]}
	if not response.ok:
		frappe.throw(_error_message(result), frappe.ValidationError)
	if not isinstance(result, dict):
		frappe.throw("WhatsApp relay returned an invalid response", frappe.ValidationError)
	return result


def _relay_request(
	operation: str,
	*,
	settings,
	media_id: str | None = None,
	headers: dict | None = None,
	timeout: int | None = None,
	**kwargs,
):
	method_path = _RELAY_OPERATIONS.get(str(operation or ""))
	if not method_path:
		frappe.throw("Unsupported WhatsApp relay operation", frappe.ValidationError)
	method, path = method_path
	if "{media_id}" in path:
		media_id = str(media_id or "").strip()
		if not media_id or len(media_id) > 256 or not all(
			character.isalnum() or character in "_-" for character in media_id
		):
			frappe.throw("Invalid WhatsApp media id", frappe.ValidationError)
		path = path.format(media_id=media_id)
	url = f"{_relay_url(settings)}{path}"
	request_method = {
		"DELETE": _session.delete,
		"GET": _session.get,
		"POST": _session.post,
	}[method]
	return request_method(
		url,
		headers=headers or settings.get_hub_auth_headers(),
		timeout=timeout or _request_timeout(settings),
		allow_redirects=False,
		**kwargs,
	)


def _response_error(response) -> str:
	try:
		return _error_message(response.json())
	except ValueError:
		return str(response.text or "WhatsApp relay request failed")[:2000]


def _mapped_account_name(settings, account_name: str) -> str:
	account_name = str(account_name or "").strip()
	if account_name not in {
		str(row.account_name or "").strip()
		for row in settings.accounts
	}:
		frappe.throw("Hub account is not mapped to this Core site", frappe.PermissionError)
	return account_name


def get_settings(*, outbound: bool = False, relay: bool = False):
	settings = frappe.get_single("WhatsApp Core Settings")
	if not settings.enabled:
		frappe.throw("WhatsApp Core is not enabled on this site")
	if outbound and not settings.outbound_enabled:
		frappe.throw("Outbound WhatsApp messages are disabled on this site")
	if (outbound or relay) and not _relay_url(settings):
		frappe.throw("WhatsApp Go Relay URL is not configured")
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
		"relay_url": getattr(settings, "relay_url", None) or "",
		"data_plane": "go_relay" if _relay_url(settings) else "not_configured",
		"credentials_configured": bool(
			settings.get_password("api_key", raise_exception=False)
			and settings.get_password("api_secret", raise_exception=False)
		),
		"account_count": len(settings.accounts),
	}


def _request_timeout(settings) -> int:
	return max(2, min(int(settings.request_timeout or 30), 120))


def _relay_url(settings) -> str:
	"""Return the mandatory Go data-plane endpoint for operational requests."""
	return validate_service_origin(
		getattr(settings, "relay_url", None), label="Go Relay URL"
	)


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
