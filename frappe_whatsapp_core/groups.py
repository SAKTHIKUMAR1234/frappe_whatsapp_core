"""Site-scoped Core facade for Meta-hosted WhatsApp Groups."""

import frappe

from frappe_whatsapp_core.meta_flows import _accounts, _call, _resolve_account_name
from frappe_whatsapp_core.permissions import require_core_access


def _account(account_name=None):
	return _resolve_account_name(account_name)


@frappe.whitelist()
@require_core_access()
def group_workspace(account_name=None, limit=100, after=None, before=None):
	selected = _account(account_name)
	result = _call("groups", "list_groups", {
		"account_name": selected, "limit": limit, "after": after, "before": before,
	})
	return {"accounts": _accounts(), "selected_account": selected, **result}


@frappe.whitelist()
@require_core_access()
def get_group(account_name, group_id):
	return _call("groups", "get_group", {"account_name": _account(account_name), "group_id": group_id})


@frappe.whitelist()
@require_core_access(manage=True)
def create_group(account_name, subject, description=None, join_approval_mode="auto_approve"):
	return _call("groups", "create_group", {
		"account_name": _account(account_name), "subject": subject,
		"description": description, "join_approval_mode": join_approval_mode,
	})


@frappe.whitelist()
@require_core_access(manage=True)
def update_group(account_name, group_id, subject=None, description=None):
	return _call("groups", "update_group", {
		"account_name": _account(account_name), "group_id": group_id,
		"subject": subject, "description": description,
	})


@frappe.whitelist()
@require_core_access(manage=True)
def update_group_picture(account_name, group_id, file_content_b64, filename="group.jpg"):
	return _call("groups", "update_group_picture", {
		"account_name": _account(account_name), "group_id": group_id,
		"file_content_b64": file_content_b64, "filename": filename,
	})


@frappe.whitelist()
@require_core_access(manage=True)
def delete_group(account_name, group_id):
	return _call("groups", "delete_group", {"account_name": _account(account_name), "group_id": group_id})


@frappe.whitelist()
@require_core_access()
def get_invite_link(account_name, group_id):
	return _call("groups", "get_invite_link", {"account_name": _account(account_name), "group_id": group_id})


@frappe.whitelist()
@require_core_access(manage=True)
def reset_invite_link(account_name, group_id):
	return _call("groups", "reset_invite_link", {"account_name": _account(account_name), "group_id": group_id})


@frappe.whitelist()
@require_core_access()
def list_join_requests(account_name, group_id):
	return _call("groups", "list_join_requests", {"account_name": _account(account_name), "group_id": group_id})


@frappe.whitelist()
@require_core_access(manage=True)
def change_join_requests(account_name, group_id, join_requests, approve=1):
	method = "approve_join_requests" if int(approve) else "reject_join_requests"
	return _call("groups", method, {
		"account_name": _account(account_name), "group_id": group_id, "join_requests": join_requests,
	})


@frappe.whitelist()
@require_core_access(manage=True)
def remove_participants(account_name, group_id, participants):
	return _call("groups", "remove_participants", {
		"account_name": _account(account_name), "group_id": group_id, "participants": participants,
	})


@frappe.whitelist()
@require_core_access()
def send_group_message(account_name, group_id, message_type, content, idempotency_key=None):
	return _call("groups", "send_group_message", {
		"account_name": _account(account_name), "group_id": group_id,
		"message_type": message_type, "content": content, "idempotency_key": idempotency_key,
	})


@frappe.whitelist()
@require_core_access()
def pin_group_message(account_name, group_id, message_id, operation="pin", expiration_days=None):
	return _call("groups", "pin_group_message", {
		"account_name": _account(account_name), "group_id": group_id,
		"message_id": message_id, "operation": operation, "expiration_days": expiration_days,
	})
