"""Authenticated Core client for the central WhatsApp Integration Hub."""

from __future__ import annotations

import requests

import frappe

_session = requests.Session()


def send_raw(
	channel: str,
	payload: dict,
	idempotency_key: str,
) -> dict:
	settings = get_settings(outbound=True)
	url = (
		f"{settings.hub_url}/api/method/"
		"frappe_whatsapp_integration.frappe_whatsapp_hub.api.send.send_raw"
	)
	try:
		response = _session.post(
			url,
			headers=settings.get_hub_auth_headers(),
			json={
				"account_name": settings.get_account_name(channel),
				"payload": payload,
				"idempotency_key": idempotency_key,
			},
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
		if not channel or not isinstance(payload, dict) or not idempotency_key:
			frappe.throw(
				"Every Hub batch item requires channel, payload, and idempotency_key",
				frappe.ValidationError,
			)
		normalized.append({
			"account_name": settings.get_account_name(channel),
			"payload": payload,
			"idempotency_key": idempotency_key,
		})

	url = (
		f"{settings.hub_url}/api/method/"
		"frappe_whatsapp_integration.frappe_whatsapp_hub.api.send.send_batch"
	)
	try:
		response = _session.post(
			url,
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


def get_settings(*, outbound: bool = False):
	settings = frappe.get_single("WhatsApp Core Settings")
	if not settings.enabled:
		frappe.throw("WhatsApp Core is not enabled on this site")
	if outbound and not settings.outbound_enabled:
		frappe.throw("Outbound WhatsApp messages are disabled on this site")
	if not settings.hub_url:
		frappe.throw("WhatsApp Core Hub URL is not configured")
	return settings


def connection_status() -> dict:
	settings = frappe.get_single("WhatsApp Core Settings")
	return {
		"enabled": bool(settings.enabled),
		"outbound_enabled": bool(settings.outbound_enabled),
		"hub_url": settings.hub_url or "",
		"credentials_configured": bool(
			settings.get_password("api_key", raise_exception=False)
			and settings.get_password("api_secret", raise_exception=False)
		),
		"account_count": len(settings.accounts),
	}


def _request_timeout(settings) -> int:
	return max(2, min(int(settings.request_timeout or 30), 120))


def _error_message(result) -> str:
	if not isinstance(result, dict):
		return "WhatsApp Hub request failed"
	error = result.get("error") or result.get("message") or result.get("raw")
	if isinstance(error, dict):
		return (
			error.get("message")
			or error.get("error_user_msg")
			or str(error)
		)
	return str(error or "WhatsApp Hub request failed")


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
