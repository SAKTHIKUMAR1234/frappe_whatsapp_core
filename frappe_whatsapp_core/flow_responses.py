"""Durable response ledger shared by visual automations and Meta Flows."""

from __future__ import annotations

import json
from typing import Any

import frappe
from frappe.utils import now

from frappe_whatsapp_core.permissions import assert_conversation_access, require_core_access


def upsert_instance_response(instance, status: str | None = None):
	context = _dict(instance.context)
	response_key = f"instance:{instance.name}"
	values = {
		"doctype": "WhatsApp Core Flow Response",
		"response_key": response_key,
		"response_type": "Automation",
		"flow": instance.flow,
		"flow_instance": instance.name,
		"conversation": instance.conversation,
		"status": status or _instance_status(instance.status),
		"response_payload": _json(context),
		"processed_at": now(),
		"error": instance.error or "",
	}
	return _upsert(response_key, values)


def record_meta_submission(message, event, flow_event: dict[str, Any]):
	flow_token = str(flow_event.get("flow_token") or "").strip()
	instance = None
	if flow_token:
		instance = frappe.db.get_value(
			"WhatsApp Core Flow Instance",
			{"waiting_flow_token": flow_token, "status": ["in", ["Running", "Waiting"]]},
			["name", "flow"],
			as_dict=True,
		)
	response_key = f"message:{message.name}"
	values = {
		"doctype": "WhatsApp Core Flow Response",
		"response_key": response_key,
		"response_type": "Meta Submission",
		"flow": instance.flow if instance else None,
		"flow_instance": instance.name if instance else None,
		"conversation": message.conversation,
		"message": message.name,
		"relay_event": event.name if event else None,
		"channel": message.channel,
		"provider_flow_name": str(flow_event.get("flow_name") or ""),
		"flow_token": flow_token[:140],
		"status": "Received",
		"response_payload": _json(flow_event.get("flow_response")),
		"received_at": message.provider_timestamp,
	}
	return _upsert(response_key, values)


def record_data_exchange(log, payload: dict, response: dict | None = None, error: str = ""):
	response_key = f"exchange:{log.request_id}"
	values = {
		"doctype": "WhatsApp Core Flow Response",
		"response_key": response_key,
		"response_type": "Data Exchange",
		"channel": log.channel,
		"provider_flow_name": str(payload.get("flow_id") or payload.get("flow_name") or ""),
		"flow_token": str(payload.get("flow_token") or "")[:140],
		"action": str((payload.get("data") or {}).get("_core_action") or ""),
		"screen": str(payload.get("screen") or ""),
		"status": "Failed" if error else "Completed",
		"request_payload": _json(payload),
		"response_payload": _json(response),
		"processed_at": now(),
		"error": error,
	}
	return _upsert(response_key, values)


def complete_meta_submission(response_doc, result: dict[str, Any] | None = None, error: str = ""):
	if not response_doc:
		return None
	doc = (
		response_doc
		if getattr(response_doc, "doctype", None) == "WhatsApp Core Flow Response"
		else frappe.get_doc("WhatsApp Core Flow Response", response_doc)
	)
	doc.status = "Failed" if error else "Completed"
	doc.action_results = _json(result)
	doc.processed_at = now()
	doc.error = error
	doc.save(ignore_permissions=True)
	return doc


@frappe.whitelist()
@require_core_access(manage=True)
def list_flow_responses(
	flow: str | None = None,
	conversation: str | None = None,
	response_type: str | None = None,
	limit: int = 100,
) -> list[dict]:
	if conversation:
		assert_conversation_access(conversation)
	filters = {}
	if flow:
		filters["flow"] = flow
	if conversation:
		filters["conversation"] = conversation
	if response_type:
		filters["response_type"] = response_type
	limit = max(1, min(int(limit or 100), 500))
	return frappe.get_all(
		"WhatsApp Core Flow Response",
		filters=filters,
		fields=[
			"name",
			"response_key",
			"response_type",
			"flow",
			"flow_instance",
			"conversation",
			"message",
			"provider_flow_name",
			"action",
			"screen",
			"status",
			"response_payload",
			"action_results",
			"received_at",
			"processed_at",
			"error",
			"creation",
		],
		order_by="creation desc",
		limit_page_length=limit,
	)


def _upsert(response_key: str, values: dict):
	if frappe.db.exists("WhatsApp Core Flow Response", response_key):
		doc = frappe.get_doc("WhatsApp Core Flow Response", response_key)
		doc.update(values)
		doc.save(ignore_permissions=True)
		return doc
	return frappe.get_doc(values).insert(ignore_permissions=True)


def _instance_status(status: str) -> str:
	return {
		"Completed": "Completed",
		"Failed": "Failed",
		"Cancelled": "Rejected",
		"Expired": "Rejected",
	}.get(status, "Processing")


def _dict(value) -> dict:
	if isinstance(value, dict):
		return value
	if not value:
		return {}
	parsed = frappe.parse_json(value)
	return parsed if isinstance(parsed, dict) else {}


def _json(value) -> str:
	return json.dumps(value or {}, separators=(",", ":"), ensure_ascii=False, default=str)
