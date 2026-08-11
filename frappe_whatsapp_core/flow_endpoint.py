"""Authenticated business handler for decrypted Meta Flow data exchanges."""

from __future__ import annotations

import hashlib
import json
import time

import frappe

from frappe_whatsapp_core.flow_actions import execute_registered_action
from frappe_whatsapp_core.flow_responses import record_data_exchange
from frappe_whatsapp_core.meta_flows import _resolve_account_name
from frappe_whatsapp_core.permissions import require_core_access

VALID_ACTIONS = {"ping", "INIT", "BACK", "data_exchange"}


def _canonical(value) -> str:
	return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _channel_for(account_name: str, requested_channel: str | None) -> str:
	settings = frappe.get_single("WhatsApp Core Settings")
	if not settings.enabled:
		frappe.throw("WhatsApp Core is disabled", frappe.ValidationError)
	for row in settings.accounts:
		if row.account_name != account_name:
			continue
		channel = str(row.channel or "").strip()
		if requested_channel:
			phone_number_id = frappe.db.get_value("WhatsApp Core Channel", channel, "phone_number_id")
			if str(phone_number_id or "") != str(requested_channel):
				frappe.throw("Flow channel does not match the mapped Hub account", frappe.PermissionError)
		return channel
	frappe.throw("Hub account is not mapped to this Core site", frappe.PermissionError)


def _handlers() -> list[str]:
	hooks = frappe.get_hooks("whatsapp_core_meta_flow_endpoint_handlers") or []
	if isinstance(hooks, dict):
		hooks = list(hooks.values())
	result = []
	for handler in hooks:
		if isinstance(handler, (list, tuple)):
			result.extend(handler)
		else:
			result.append(handler)
	return [str(handler) for handler in result if handler]


def _dispatch(payload: dict, context: dict) -> dict:
	action = str(payload.get("action") or "")
	if action not in VALID_ACTIONS:
		frappe.throw(f"Unsupported Meta Flow action: {action}", frappe.ValidationError)
	if action == "ping":
		return {"data": {"status": "active"}}
	if isinstance(payload.get("data"), dict) and payload["data"].get("error"):
		return {"data": {"acknowledged": True}}

	data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
	action_reference = str(data.get("_core_action") or "").strip()
	if action_reference:
		params = data.get("_core_params") or {}
		if not isinstance(params, dict):
			frappe.throw("Meta Flow action parameters must be an object", frappe.ValidationError)
		result = execute_registered_action(
			action_reference,
			params,
			context={**context, "payload": payload},
		)
		if isinstance(result, dict) and ("screen" in result or "data" in result):
			return result
		return {
			"screen": str(data.get("_next_screen") or payload.get("screen") or ""),
			"data": {"result": result},
		}

	for handler_path in _handlers():
		response = frappe.get_attr(handler_path)(payload=payload, context=context)
		if response is not None:
			if not isinstance(response, dict):
				frappe.throw(
					f"Meta Flow handler {handler_path} must return an object",
					frappe.ValidationError,
				)
			return response
	frappe.throw(
		"No business application handled this dynamic Meta Flow request",
		frappe.ValidationError,
	)


def _cached_response(request_id: str):
	row = frappe.db.get_value(
		"WhatsApp Core Meta Flow Exchange",
		{"request_id": request_id, "status": ["in", ["Completed", "Rejected"]]},
		["response_payload"],
		as_dict=True,
	)
	if not row or not row.response_payload:
		return None
	response = frappe.parse_json(row.response_payload)
	if not isinstance(response, dict):
		return None
	return response


@frappe.whitelist(methods=["POST"])
@require_core_access(manage=True)
def handle(account_name: str, channel: str | None = None, payload=None):
	"""Handle a clear payload from Integration and return a clear response.

	Integration is the only component that sees Meta credentials and encryption
	keys. This endpoint is authenticated with the connected site's Frappe API
	credentials and permits only mapped accounts/channels.
	"""
	started = time.monotonic()
	account_name = _resolve_account_name(account_name)
	channel_name = _channel_for(account_name, channel)
	if isinstance(payload, str):
		payload = frappe.parse_json(payload)
	if not isinstance(payload, dict):
		frappe.throw("Flow payload must be an object", frappe.ValidationError)

	request_id = hashlib.sha256(f"{account_name}\n{_canonical(payload)}".encode()).hexdigest()
	if cached := _cached_response(request_id):
		return cached

	log = frappe.get_doc(
		{
			"doctype": "WhatsApp Core Meta Flow Exchange",
			"request_id": request_id,
			"account_name": account_name,
			"channel": channel_name,
			"action": str(payload.get("action") or ""),
			"screen": str(payload.get("screen") or ""),
			"flow_token": str(payload.get("flow_token") or "")[:140],
			"status": "Processing",
			"request_payload": _canonical(payload),
		}
	)
	try:
		log.insert(ignore_permissions=True)
	except frappe.DuplicateEntryError:
		if cached := _cached_response(request_id):
			return cached
		frappe.throw(
			"This Meta Flow exchange is already being processed",
			frappe.ValidationError,
		)

	context = {
		"account_name": account_name,
		"channel": channel_name,
		"request_id": request_id,
	}
	try:
		response = _dispatch(payload, context)
		status = int(response.pop("_http_status", 200) or 200)
		if status not in {200, 421, 427, 432}:
			frappe.throw("Invalid Meta Flow endpoint response status", frappe.ValidationError)
		log.status = "Rejected" if status != 200 else "Completed"
		log.response_payload = _canonical({**response, "_http_status": status})
		log.duration_ms = int((time.monotonic() - started) * 1000)
		log.save(ignore_permissions=True)
		record_data_exchange(log, payload, {**response, "_http_status": status})
		return {**response, "_http_status": status}
	except Exception as exception:
		log.status = "Failed"
		log.error = str(exception)
		log.duration_ms = int((time.monotonic() - started) * 1000)
		log.save(ignore_permissions=True)
		record_data_exchange(log, payload, error=str(exception))
		raise
