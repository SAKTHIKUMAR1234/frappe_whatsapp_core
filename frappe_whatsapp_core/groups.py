"""Site-scoped Core facade for Meta-hosted WhatsApp Groups."""

import frappe

from frappe_whatsapp_core.hub_client import send_account_raw
from frappe_whatsapp_core.identity import contact_options
from frappe_whatsapp_core.materializer import (
	get_or_create_conversation,
	get_or_create_group_identity,
	sync_group_identity,
)
from frappe_whatsapp_core.meta_flows import _accounts, _call, _resolve_account_name, _workspace_failure
from frappe_whatsapp_core.outbound import (
	queue_rich,
	queue_template_internal,
	queue_text_internal,
	start_conversation,
	upload_media,
)
from frappe_whatsapp_core.naming import name_by_key
from frappe_whatsapp_core.permissions import require_core_access


def _account(account_name=None):
	return _resolve_account_name(account_name)


def _sync_group_summaries(account_name, rows, accounts):
	"""Project Meta list responses so existing groups are readable before a webhook arrives."""
	account = next((row for row in accounts if row.get("account_name") == account_name), None)
	if (
		not account
		or not account.get("channel")
		or not frappe.db.exists("WhatsApp Core Channel", account["channel"])
	):
		return
	for row in rows or []:
		group_id = str(row.get("id") or row.get("group_id") or "").strip()
		if not group_id:
			continue
		status = str(row.get("status") or "Active").strip().title()
		if status not in {"Active", "Suspended", "Deleted", "Failed"}:
			status = "Active"
		values = {
			"channel": account["channel"],
			"status": status,
			"last_event_type": "group_list_sync",
			"last_event": row,
			"last_synced": frappe.utils.now_datetime(),
		}
		for fieldname, source in {
			"subject": "subject",
			"description": "description",
			"join_approval_mode": "join_approval_mode",
			"invite_link": "invite_link",
		}.items():
			if row.get(source) is not None:
				values[fieldname] = row[source]
		participant_count = row.get("total_participant_count", row.get("participant_count"))
		if participant_count is not None:
			values["participant_count"] = int(participant_count or 0)
		record_name = name_by_key("WhatsApp Core Group", group_id)
		if record_name:
			group = frappe.get_doc("WhatsApp Core Group", record_name)
			group.update(values)
			group.save(ignore_permissions=True)
		else:
			group = frappe.get_doc({
				"doctype": "WhatsApp Core Group",
				"group_id": group_id,
				**values,
			}).insert(ignore_permissions=True)
		sync_group_identity(group)


@frappe.whitelist()
@require_core_access(manage=True)
def group_workspace(account_name=None, limit=100, after=None, before=None):
	accounts = []
	selected = None
	templates = []
	contacts = contact_options(limit=50)
	try:
		accounts = _accounts()
		selected = _account(account_name)
		channel = next(row["channel"] for row in accounts if row["account_name"] == selected)
		templates = frappe.get_all(
			"WhatsApp Core Template",
			filters={"approval_status": "APPROVED", "enabled": 1, "channel": channel},
			fields=["name", "template_name", "language_code", "body_text"],
			order_by="template_name asc, language_code asc",
			limit_page_length=500,
		)
		result = _call("groups", "list_groups", {
			"account_name": selected, "limit": limit, "after": after, "before": before,
		})
		_sync_group_summaries(selected, result.get("data") or [], accounts)
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
	group_name = name_by_key("WhatsApp Core Group", group_id)
	group = (
		frappe.get_doc("WhatsApp Core Group", group_name).as_dict()
		if group_name
		else None
	)
	conversation = None
	messages = []
	if group:
		identity = get_or_create_group_identity(group_id)
		conversation = frappe.db.get_value(
			"WhatsApp Core Conversation",
			{"channel": group.channel, "remote_identity": identity.name},
			"name",
			order_by="last_message_at desc",
		)
		if conversation:
			messages = frappe.get_all(
				"WhatsApp Core Message",
				# Include optimistic local ids. The management dialog refreshes
				# immediately after queueing; hiding these rows makes a successful
				# message disappear until Meta's provider-id callback arrives.
				filters={"conversation": conversation},
				fields=[
					"name", "provider_message_id", "direction", "message_type",
					"body", "delivery_status", "provider_timestamp",
				],
				order_by="provider_timestamp desc, creation desc",
				limit_page_length=50,
			)
	return {
		"group": group,
		"conversation": conversation,
		"messages": messages,
		"members": frappe.get_all(
			"WhatsApp Core Group Member",
			filters={"group": group.name},
			fields=["participant_id", "status", "join_request_id", "reason", "last_synced"],
			order_by="modified desc",
			limit_page_length=100,
		) if group else [],
		"receipts": frappe.get_all(
			"WhatsApp Core Group Receipt",
			filters={"group": group.name},
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

	BSUID-only recipients are queued directly through the Go relay because Core
	cannot create a phone identity for them without inventing a number.
	"""
	selected = _account(account_name)
	if isinstance(additional_body_parameters, str):
		additional_body_parameters = frappe.parse_json(additional_body_parameters)
	additional_body_parameters = additional_body_parameters or []
	if not isinstance(additional_body_parameters, list):
		frappe.throw("additional_body_parameters must be a list", frappe.ValidationError)
	if not to_number and not identity:
		if not recipient:
			frappe.throw("A recipient is required", frappe.ValidationError)
		payload = {
			"messaging_product": "whatsapp",
			"recipient_type": "individual",
			"recipient": str(recipient),
			"type": "template",
			"template": {
				"name": str(template_name or "").strip(),
				"language": {"code": str(language_code or "en").strip()},
				"components": [{
					"type": "body",
					"parameters": [
						{"type": "group_id", "group_id": group_id},
						*additional_body_parameters,
					],
				}],
			},
		}
		if not payload["template"]["name"]:
			frappe.throw("template_name is required", frappe.ValidationError)
		return send_account_raw(selected, payload, idempotency_key)
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
		local_file_url = ""
		if file_url:
			uploaded = upload_media(conversation.name, file_url, message_type)
			content["id"] = uploaded["media_id"]
			local_file_url = uploaded.get("file_url") or file_url
			if message_type == "document" and not content.get("filename"):
				content["filename"] = uploaded.get("filename")
		message = queue_rich(
			conversation.name,
			message_type,
			content,
			source="Core Group UI",
			local_file_url=local_file_url or None,
		)
	return {"success": True, "conversation": conversation.name, "message": message}


@frappe.whitelist()
@require_core_access(manage=True)
def pin_group_message(account_name, group_id, message_id, operation="pin", expiration_days=None):
	operation = str(operation or "").lower()
	if operation not in {"pin", "unpin"}:
		frappe.throw("operation must be pin or unpin", frappe.ValidationError)
	pin = {"type": operation, "message_id": message_id}
	if operation == "pin":
		days = int(expiration_days or 0)
		if not 1 <= days <= 30:
			frappe.throw("expiration_days must be between 1 and 30", frappe.ValidationError)
		pin["expiration_days"] = days
	return send_account_raw(
		_account(account_name),
		{
			"messaging_product": "whatsapp",
			"recipient_type": "group",
			"to": str(group_id),
			"type": "pin",
			"pin": pin,
		},
	)
