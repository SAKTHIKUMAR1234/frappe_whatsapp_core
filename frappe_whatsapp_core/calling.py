"""Site-scoped Core facade for WhatsApp Business Calling signaling."""

import frappe

from frappe_whatsapp_core.meta_flows import _accounts, _call, _resolve_account_name
from frappe_whatsapp_core.permissions import require_core_access


@frappe.whitelist()
@require_core_access(manage=True)
def calling_workspace(account_name=None, include_sip_credentials=0):
	selected = _resolve_account_name(account_name)
	settings = _call("calling", "get_call_settings", {
		"account_name": selected, "include_sip_credentials": include_sip_credentials,
	})
	calls = frappe.get_all(
		"WhatsApp Core Call", fields=["name", "call_id", "channel", "direction", "status", "remote_number", "started_at", "ended_at", "modified"],
		order_by="modified desc", limit_page_length=100,
	)
	return {"accounts": _accounts(), "selected_account": selected, "settings": settings, "calls": calls}


@frappe.whitelist()
@require_core_access(manage=True)
def update_call_settings(account_name, calling):
	return _call("calling", "update_call_settings", {
		"account_name": _resolve_account_name(account_name), "calling": calling,
	})


@frappe.whitelist()
@require_core_access(manage=True)
def get_call_permission(account_name, user_wa_id=None, recipient=None):
	return _call("calling", "get_call_permission", {
		"account_name": _resolve_account_name(account_name), "user_wa_id": user_wa_id, "recipient": recipient,
	})


@frappe.whitelist()
@require_core_access(manage=True)
def request_call_permission(account_name, body_text, to_number=None, recipient=None):
	return _call("calling", "request_call_permission", {
		"account_name": _resolve_account_name(account_name), "body_text": body_text,
		"to_number": to_number, "recipient": recipient,
	})


@frappe.whitelist()
@require_core_access(manage=True)
def call_action(account_name, action, call_id=None, to_number=None, recipient=None, sdp_type=None, sdp=None, biz_opaque_callback_data=None):
	return _call("calling", "call_action", {
		"account_name": _resolve_account_name(account_name), "action": action,
		"call_id": call_id, "to_number": to_number, "recipient": recipient,
		"sdp_type": sdp_type, "sdp": sdp,
		"biz_opaque_callback_data": biz_opaque_callback_data,
	})
