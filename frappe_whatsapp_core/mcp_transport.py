"""Authenticated stateless MCP Streamable HTTP endpoint for Core tools."""

from __future__ import annotations

import json
import time
import uuid
from urllib.parse import urlparse

import frappe
from werkzeug.wrappers import Response

from frappe_whatsapp_core.mcp_tools import TOOL_DEFINITIONS, call_tool
from frappe_whatsapp_core.permissions import require_core_access
from frappe_whatsapp_core.realtime import publish_invalidation

SUPPORTED_PROTOCOL_VERSIONS = (
	"2025-11-25",
	"2025-06-18",
	"2025-03-26",
)
DEFAULT_PROTOCOL_VERSION = "2025-03-26"


@frappe.whitelist(methods=["GET", "POST"])
@require_core_access(manage=True)
def handle(**_request_arguments):
	"""Serve one stateless JSON-RPC request at a Frappe-authenticated endpoint."""
	if frappe.request.method == "GET":
		return Response(status=405, headers={"Allow": "POST"})
	if not _origin_allowed():
		return _json_response(
			_error(None, -32000, "Origin is not allowed"),
			status=403,
		)

	request = frappe.request.get_json(silent=True)
	if not isinstance(request, dict):
		return _json_response(
			_error(None, -32700, "Request body must be a JSON object"),
			status=400,
		)
	if request.get("jsonrpc") != "2.0":
		return _json_response(
			_error(request.get("id"), -32600, "jsonrpc must be 2.0"),
			status=400,
		)
	if request.get("method", "").startswith("notifications/"):
		return Response(status=202)

	protocol_version = frappe.request.headers.get("MCP-Protocol-Version")
	if (
		request.get("method") != "initialize"
		and protocol_version
		and protocol_version not in SUPPORTED_PROTOCOL_VERSIONS
	):
		return _json_response(
			_error(
				request.get("id"),
				-32600,
				f"Unsupported MCP protocol version: {protocol_version}",
			),
			status=400,
		)
	return _json_response(_dispatch(request))


def _dispatch(request: dict) -> dict:
	request_id = request.get("id")
	method = request.get("method")
	params = request.get("params") or {}
	if method == "initialize":
		requested_version = params.get("protocolVersion")
		version = (
			requested_version
			if requested_version in SUPPORTED_PROTOCOL_VERSIONS
			else SUPPORTED_PROTOCOL_VERSIONS[0]
		)
		return _result(request_id, {
			"protocolVersion": version,
			"capabilities": {"tools": {"listChanged": False}},
			"serverInfo": {
				"name": "frappe-whatsapp-core",
				"version": "0.1.0",
			},
		})
	if method == "ping":
		return _result(request_id, {})
	if method == "tools/list":
		return _result(request_id, {"tools": TOOL_DEFINITIONS})
	if method == "tools/call":
		return _result(request_id, _invoke_tool(params))
	return _error(request_id, -32601, f"Method not found: {method}")


def _invoke_tool(params: dict) -> dict:
	tool_name = params.get("name")
	arguments = params.get("arguments") or {}
	started_at = time.monotonic()
	invocation_key = str(uuid.uuid4())
	try:
		result = call_tool(tool_name, arguments)
		duration_ms = round((time.monotonic() - started_at) * 1000)
		failed_result = isinstance(result, dict) and result.get("success") is False
		result_error = (
			str(result.get("error") or "WhatsApp operation failed")[:2000]
			if failed_result
			else ""
		)
		_log_invocation(
			invocation_key,
			tool_name,
			arguments,
			"Failed" if failed_result else "Completed",
			duration_ms,
			result=result if not failed_result else None,
			error=result_error or None,
		)
		return {
			"content": [{
				"type": "text",
				"text": (
					result_error
					if failed_result
					else json.dumps(result, default=str, ensure_ascii=False)
				),
			}],
			"structuredContent": result,
			"isError": failed_result,
		}
	except Exception as exception:
		duration_ms = round((time.monotonic() - started_at) * 1000)
		_log_invocation(
			invocation_key,
			tool_name,
			arguments,
			"Failed",
			duration_ms,
			error=str(exception),
		)
		return {
			"content": [{"type": "text", "text": str(exception)}],
			"isError": True,
		}


def _log_invocation(
	invocation_key: str,
	tool_name: str | None,
	arguments: dict,
	status: str,
	duration_ms: int,
	result=None,
	error: str | None = None,
) -> None:
	invocation = frappe.get_doc({
		"doctype": "WhatsApp Core MCP Invocation",
		"invocation_key": invocation_key,
		"user": frappe.session.user,
		"method": "tools/call",
		"tool_name": tool_name or "",
		"status": status,
		"duration_ms": duration_ms,
		"arguments": json.dumps(
			_safe_audit_value(arguments),
			default=str,
			ensure_ascii=False,
		)[:65535],
		"result": json.dumps(
			_safe_audit_value(result),
			default=str,
			ensure_ascii=False,
		)[:100000] if result is not None else "",
		"error": (error or "")[:100000],
	}).insert(ignore_permissions=True)
	publish_invalidation("whatsapp_core_mcp_invocation")


def _safe_audit_value(value, key: str = ""):
	"""Keep MCP audit useful without persisting credentials or large binaries."""
	normalized_key = str(key or "").lower()
	if normalized_key in {
		"access_token",
		"api_secret",
		"app_secret",
		"authorization",
		"password",
		"private_key",
		"sip_credentials",
	} or normalized_key.endswith(("_password", "_secret", "_token")):
		return "[redacted]"
	if normalized_key in {"file_content_b64", "sdp"} and value:
		return f"[redacted {len(str(value))} characters]"
	if isinstance(value, dict):
		return {
			str(child_key): _safe_audit_value(child_value, str(child_key))
			for child_key, child_value in value.items()
		}
	if isinstance(value, (list, tuple)):
		return [_safe_audit_value(item, key) for item in value]
	return value


def _origin_allowed() -> bool:
	origin = frappe.request.headers.get("Origin")
	if not origin:
		return True
	return urlparse(origin).netloc == frappe.request.host


def _result(request_id, result) -> dict:
	return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id, code: int, message: str) -> dict:
	return {
		"jsonrpc": "2.0",
		"id": request_id,
		"error": {"code": code, "message": message},
	}


def _json_response(payload: dict, status: int = 200) -> Response:
	return Response(
		json.dumps(payload, default=str, ensure_ascii=False),
		status=status,
		content_type="application/json",
	)
