"""Core proxy for Meta-hosted WhatsApp Flows managed by the Integration Hub."""

from __future__ import annotations

import frappe

from frappe_whatsapp_core.hub_client import call_management, connection_status, get_settings
from frappe_whatsapp_core.permissions import require_core_access

INTEGRATION_API = "frappe_whatsapp_hub.frappe_whatsapp_hub.api"


def _call(module: str, method: str, args: dict) -> dict:
	return call_management(f"{INTEGRATION_API}.{module}.{method}", args)


def _accounts() -> list[dict]:
	settings = get_settings()
	rows = []
	for row in settings.accounts:
		channel = (
			frappe.db.get_value(
				"WhatsApp Core Channel", row.channel, ["display_name", "phone_number_id"], as_dict=True
			)
			or {}
		)
		rows.append(
			{
				"account_name": row.account_name,
				"channel": row.channel,
				"display_name": channel.get("display_name") or row.account_name,
				"phone_number_id": channel.get("phone_number_id") or "",
				"is_default": bool(row.is_default),
			}
		)
	return rows


def _resolve_account_name(account_name: str | None = None) -> str:
	accounts = _accounts()
	requested = str(account_name or "").strip()
	if requested:
		if requested not in {row["account_name"] for row in accounts}:
			frappe.throw("Hub account is not mapped to this Core site", frappe.PermissionError)
		return requested
	for row in accounts:
		if row["is_default"]:
			return row["account_name"]
	if len(accounts) == 1:
		return accounts[0]["account_name"]
	frappe.throw("Select a configured WhatsApp account", frappe.ValidationError)


def _context(account_name: str | None = None) -> dict:
	account_name = _resolve_account_name(account_name)
	return _call("onboarding", "get_account_meta_context", {"account_name": account_name})


def _workspace_failure(error: Exception, **payload) -> dict:
	"""Return a renderable state for read-only workspaces when Hub is unavailable."""
	if isinstance(error, frappe.PermissionError):
		raise error
	try:
		status = connection_status()
	except Exception:
		status = {}
	configured = bool(
		status.get("enabled")
		and status.get("hub_url")
		and status.get("credentials_configured")
		and status.get("account_count")
	)
	return {
		"configured": configured,
		"available": False,
		"error": _public_workspace_error(error),
		**payload,
	}


def _public_workspace_error(error: Exception) -> str:
	"""Keep operator guidance useful without exposing raw Graph responses."""
	message = str(error or "").strip()
	lowered = message.lower()
	if "131215" in lowered or "not eligible to access groups apis" in lowered:
		return (
			"Meta Groups is unavailable for this phone number. Groups currently requires "
			"an eligible Official Business Account (OBA) phone number."
		)
	if "session has expired" in lowered or "error validating access token" in lowered:
		return "Meta access token expired. Update the account credential in Integration, then retry."
	if "401" in lowered or "oauth" in lowered:
		return "Meta authentication failed. Update the account credential in Integration, then retry."
	if "403" in lowered or "permission" in lowered:
		return "Meta rejected this account operation. Check its permissions in Integration."
	if "timeout" in lowered or "timed out" in lowered:
		return "Meta did not respond in time. Retry in a moment."
	return message or "WhatsApp Integration is unavailable"


@frappe.whitelist()
@require_core_access(manage=True)
def flow_workspace(account_name: str | None = None) -> dict:
	accounts = []
	selected = None
	try:
		accounts = _accounts()
		selected = _resolve_account_name(account_name)
		context = _context(selected)
		result = _call("meta_flows", "list_flows", {"waba_name": context["waba_name"]})
		return {
			"configured": True,
			"available": True,
			"error": "",
			"accounts": accounts,
			"selected_account": selected,
			"context": context,
			"flows": result.get("data") or [],
		}
	except Exception as error:
		return _workspace_failure(
			error,
			accounts=accounts,
			selected_account=selected,
			context={},
			flows=[],
		)


@frappe.whitelist()
@require_core_access(manage=True)
def get_flow(account_name: str, flow_id: str) -> dict:
	context = _context(account_name)
	result = _call("meta_flows", "get_flow", {"waba_name": context["waba_name"], "flow_id": flow_id})
	asset = _call("meta_flows", "get_flow_json", {"waba_name": context["waba_name"], "flow_id": flow_id})
	return {
		"account_name": account_name,
		"context": context,
		"flow": result.get("data") or {},
		"flow_json": asset.get("data"),
		"asset": asset.get("asset"),
	}


@frappe.whitelist()
@require_core_access(manage=True)
def create_flow(
	account_name: str,
	flow_name: str,
	categories,
	endpoint_uri: str | None = None,
	flow_json=None,
	clone_flow_id: str | None = None,
):
	context = _context(account_name)
	return _call(
		"meta_flows",
		"create_flow",
		{
			"waba_name": context["waba_name"],
			"flow_name": flow_name,
			"categories": categories,
			"endpoint_uri": endpoint_uri,
			"flow_json": flow_json,
			"publish": 0,
			"clone_flow_id": clone_flow_id,
		},
	)


@frappe.whitelist()
@require_core_access(manage=True)
def update_flow(
	account_name: str,
	flow_id: str,
	flow_name: str | None = None,
	categories=None,
	endpoint_uri: str | None = None,
):
	context = _context(account_name)
	return _call(
		"meta_flows",
		"update_flow_metadata",
		{
			"waba_name": context["waba_name"],
			"flow_id": flow_id,
			"flow_name": flow_name,
			"categories": categories,
			"endpoint_uri": endpoint_uri,
		},
	)


@frappe.whitelist()
@require_core_access(manage=True)
def upload_flow_json(account_name: str, flow_id: str, flow_json):
	context = _context(account_name)
	return _call(
		"meta_flows",
		"upload_flow_json",
		{
			"waba_name": context["waba_name"],
			"flow_id": flow_id,
			"flow_json": flow_json,
		},
	)


def _lifecycle(account_name: str, flow_id: str, method: str):
	context = _context(account_name)
	return _call("meta_flows", method, {"waba_name": context["waba_name"], "flow_id": flow_id})


@frappe.whitelist()
@require_core_access(manage=True)
def publish_flow(account_name: str, flow_id: str):
	return _lifecycle(account_name, flow_id, "publish_flow")


@frappe.whitelist()
@require_core_access(manage=True)
def deprecate_flow(account_name: str, flow_id: str):
	return _lifecycle(account_name, flow_id, "deprecate_flow")


@frappe.whitelist()
@require_core_access(manage=True)
def delete_flow(account_name: str, flow_id: str):
	return _lifecycle(account_name, flow_id, "delete_flow")


@frappe.whitelist()
@require_core_access(manage=True)
def list_flow_assets(account_name: str, flow_id: str):
	context = _context(account_name)
	result = _call(
		"meta_flows",
		"list_flow_assets",
		{
			"waba_name": context["waba_name"],
			"flow_id": flow_id,
		},
	)
	return result.get("data") or []


@frappe.whitelist()
@require_core_access(manage=True)
def migrate_flows(
	account_name: str,
	source_waba_id: str,
	source_flow_names=None,
):
	"""Copy selected native Flows into this site's mapped destination WABA."""
	context = _context(account_name)
	return _call(
		"meta_flows",
		"migrate_flows",
		{
			"destination_waba_name": context["waba_name"],
			"source_waba_id": source_waba_id,
			"source_flow_names": source_flow_names,
		},
	)


@frappe.whitelist()
@require_core_access(manage=True)
def get_business_public_key(account_name: str):
	return _call(
		"meta_flows",
		"get_business_public_key",
		{
			"account_name": _resolve_account_name(account_name),
		},
	)


@frappe.whitelist()
@require_core_access(manage=True)
def set_business_public_key(account_name: str, business_public_key: str):
	return _call(
		"meta_flows",
		"set_business_public_key",
		{
			"account_name": _resolve_account_name(account_name),
			"business_public_key": business_public_key,
		},
	)


@frappe.whitelist()
@require_core_access(manage=True)
def flow_endpoint_status(account_name: str):
	return _call(
		"flow_endpoint",
		"status",
		{
			"account_name": _resolve_account_name(account_name),
		},
	)


@frappe.whitelist()
@require_core_access(manage=True)
def provision_flow_endpoint(account_name: str, rotate=0):
	return _call(
		"flow_endpoint",
		"provision",
		{
			"account_name": _resolve_account_name(account_name),
			"rotate": 1 if frappe.utils.cint(rotate) else 0,
		},
	)
