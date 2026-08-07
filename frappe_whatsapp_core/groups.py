"""Site-scoped Core facade for Meta-hosted WhatsApp Groups."""

import frappe

from frappe_whatsapp_core.materializer import get_or_create_conversation, get_or_create_group_identity
from frappe_whatsapp_core.meta_flows import _accounts, _call, _resolve_account_name, _workspace_failure
from frappe_whatsapp_core.outbound import (
	queue_rich,
	queue_template_internal,
	queue_text_internal,
	start_conversation,
	upload_media,
)
from frappe_whatsapp_core.permissions import require_core_access


def _account(account_name=None):
	return _resolve_account_name(account_name)


def _contact_options() -> list[dict]:
	identities = frappe.get_all(
		"WhatsApp Core Identity",
		filters={"identity_type": "WhatsApp", "status": "Active"},
		fields=["name", "normalized_value", "display_value", "primary_link"],
		order_by="display_value asc, normalized_value asc",
		limit_page_length=1000,
	)
	link_names = [row.primary_link for row in identities if row.primary_link]
	links = {
		row.name: row
		for row in frappe.get_all(
			"WhatsApp Core Identity Link",
			filters={"name": ["in", link_names], "status": "Active"},
			fields=["name", "display_name", "reference_doctype", "reference_name"],
			limit_page_length=max(1, len(link_names)),
		)
	} if link_names else {}
	return [
		{
			"identity": row.name,
			"phone_number": row.normalized_value,
			"label": (
				links[row.primary_link].display_name
				or links[row.primary_link].reference_name
				if row.primary_link in links
				else row.display_value or row.normalized_value
			),
			"reference": (
				f"{links[row.primary_link].reference_doctype} · {links[row.primary_link].reference_name}"
				if row.primary_link in links
				else "WhatsApp contact"
			),
		}
		for row in identities
	]


@frappe.whitelist()
@require_core_access(manage=True)
def group_workspace(account_name=None, limit=100, after=None, before=None):
	accounts = []
	selected = None
	templates = frappe.get_all(
		"WhatsApp Core Template",
		filters={"approval_status": "APPROVED", "enabled": 1},
		fields=["name", "template_name", "language_code", "body_text"],
		order_by="template_name asc, language_code asc",
		limit_page_length=500,
	)
	contacts = _contact_options()
	try:
		accounts = _accounts()
		selected = _account(account_name)
		result = _call("groups", "list_groups", {
			"account_name": selected, "limit": limit, "after": after, "before": before,
		})
		return {
			"configured": True,
			"available": True,
			"error": "",
			"accounts": accounts,
			"selected_account": selected,
			"templates": templates,
			"contacts": contacts,
			**result,
		}
	except Exception as error:
		return _workspace_failure(
			error,
			accounts=accounts,
			selected_account=selected,
			templates=templates,
			contacts=contacts,
			data=[],
		)


@frappe.whitelist()
@require_core_access(manage=True)
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
@require_core_access(manage=True)
def get_invite_link(account_name, group_id):
	return _call("groups", "get_invite_link", {"account_name": _account(account_name), "group_id": group_id})


@frappe.whitelist()
@require_core_access(manage=True)
def reset_invite_link(account_name, group_id):
	return _call("groups", "reset_invite_link", {"account_name": _account(account_name), "group_id": group_id})


@frappe.whitelist()
@require_core_access(manage=True)
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
@require_core_access(manage=True)
def group_activity(group_id):
	"""Return durable management state and per-participant message receipts."""
	group_id = str(group_id or "").strip()
	group = (
		frappe.get_doc("WhatsApp Core Group", group_id).as_dict()
		if frappe.db.exists("WhatsApp Core Group", group_id)
		else None
	)
	return {
		"group": group,
		"members": frappe.get_all(
			"WhatsApp Core Group Member",
			filters={"group": group_id},
			fields=["participant_id", "status", "join_request_id", "reason", "last_synced"],
			order_by="modified desc",
			limit_page_length=100,
		) if group else [],
		"receipts": frappe.get_all(
			"WhatsApp Core Group Receipt",
			filters={"group": group_id},
			fields=["message", "participant_id", "status", "provider_timestamp"],
			order_by="provider_timestamp desc",
			limit_page_length=250,
		) if group else [],
	}


@frappe.whitelist()
@require_core_access(manage=True)
def send_group_invite_template(
	account_name,
	group_id,
	template_name,
	language_code="en",
	to_number=None,
	identity=None,
	recipient=None,
	additional_body_parameters=None,
	idempotency_key=None,
):
	"""Queue an invite template locally when addressed by phone.

	BSUID-only recipients are passed to Integration because Core cannot create a
	phone identity for them without inventing a number.
	"""
	selected = _account(account_name)
	if isinstance(additional_body_parameters, str):
		additional_body_parameters = frappe.parse_json(additional_body_parameters)
	additional_body_parameters = additional_body_parameters or []
	if not isinstance(additional_body_parameters, list):
		frappe.throw("additional_body_parameters must be a list", frappe.ValidationError)
	if not to_number and not identity:
		return _call("groups", "send_group_invite_template", {
			"account_name": selected,
			"group_id": group_id,
			"template_name": template_name,
			"language_code": language_code,
			"recipient": recipient,
			"additional_body_parameters": additional_body_parameters,
			"idempotency_key": idempotency_key,
		})
	account = next((row for row in _accounts() if row["account_name"] == selected), None)
	if not account:
		frappe.throw("Hub account is not mapped to this Core site", frappe.PermissionError)
	if identity:
		identity_doc = frappe.get_doc("WhatsApp Core Identity", identity)
		channel = frappe.get_cached_doc("WhatsApp Core Channel", account["channel"])
		conversation = get_or_create_conversation(channel, identity_doc).name
	else:
		conversation = start_conversation(account["channel"], to_number)["conversation"]
	components = [{
		"type": "body",
		"parameters": [
			{"type": "group_id", "group_id": group_id},
			*additional_body_parameters,
		],
	}]
	message = queue_template_internal(
		conversation,
		template_name,
		language_code,
		components,
		source="Core Group Invite",
	)
	return {"success": True, "conversation": conversation, "message": message}


@frappe.whitelist()
@require_core_access(manage=True)
def send_group_message(account_name, group_id, message_type, content, idempotency_key=None):
	"""Persist a Core group message, then deliver it durably through JetStream."""
	selected = _account(account_name)
	account = next((row for row in _accounts() if row["account_name"] == selected), None)
	if not account:
		frappe.throw("Hub account is not mapped to this Core site", frappe.PermissionError)
	if isinstance(content, str):
		content = frappe.parse_json(content)
	if not isinstance(content, dict):
		frappe.throw("content must be an object", frappe.ValidationError)
	message_type = str(message_type or "").strip().lower()
	if message_type not in {"text", "image", "video", "audio", "document", "template"}:
		frappe.throw("Unsupported group message type", frappe.ValidationError)
	identity = get_or_create_group_identity(group_id)
	channel = frappe.get_cached_doc("WhatsApp Core Channel", account["channel"])
	conversation = get_or_create_conversation(channel, identity)
	if message_type == "text":
		message = queue_text_internal(
			conversation.name,
			str(content.get("body") or ""),
			source="Core Group UI",
		)
	elif message_type == "template":
		template_name = content.get("name") or content.get("template_name")
		message = queue_template_internal(
			conversation.name,
			template_name,
			content.get("language", {}).get("code") or content.get("language_code") or "en",
			content.get("components") or [],
			source="Core Group UI",
		)
	else:
		file_url = str(content.pop("file_url", "") or "").strip()
		if file_url:
			uploaded = upload_media(conversation.name, file_url)
			content["id"] = uploaded["media_id"]
			if message_type == "document" and not content.get("filename"):
				content["filename"] = uploaded.get("filename")
		message = queue_rich(
			conversation.name,
			message_type,
			content,
			source="Core Group UI",
		)
	return {"success": True, "conversation": conversation.name, "message": message}


@frappe.whitelist()
@require_core_access(manage=True)
def pin_group_message(account_name, group_id, message_id, operation="pin", expiration_days=None):
	return _call("groups", "pin_group_message", {
		"account_name": _account(account_name), "group_id": group_id,
		"message_id": message_id, "operation": operation, "expiration_days": expiration_days,
	})
