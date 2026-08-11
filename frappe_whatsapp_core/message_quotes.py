"""Resolve reply context into safe, compact message previews."""

from __future__ import annotations

import json

import frappe

from frappe_whatsapp_core.message_media import add_media_url


def attach_quoted_messages(messages, conversation: str) -> None:
	"""Attach the original message to replies without exposing provider ids in the UI.

	The referenced message can be outside the current pagination window, so resolving
	it only in Vue is insufficient.  Every lookup is constrained to the conversation
	that the caller has already authorized.
	"""
	references = {
		message_id
		for row in messages or []
		if (message_id := context_message_id(row))
	}
	if not references:
		return

	targets = frappe.get_all(
		"WhatsApp Core Message",
		filters={
			"conversation": conversation,
			"provider_message_id": ["in", list(references)],
		},
		fields=[
			"name",
			"provider_message_id",
			"direction",
			"message_type",
			"body",
			"content",
			"owner",
		],
		limit_page_length=len(references),
	)
	owners = {
		row.owner
		for row in targets
		if row.direction == "Outbound" and row.owner
	}
	owner_names = {
		row.name: row.full_name or row.name
		for row in frappe.get_all(
			"User",
			filters={"name": ["in", list(owners)]},
			fields=["name", "full_name"],
			limit_page_length=len(owners),
		)
	} if owners else {}

	by_provider_id = {}
	for target in targets:
		target.content = _json_dict(target.content)
		target.sender_name = (
			owner_names.get(target.owner, target.owner)
			if target.direction == "Outbound"
			else ""
		)
		add_media_url(target)
		by_provider_id[target.provider_message_id] = {
			"name": target.name,
			"direction": target.direction,
			"message_type": target.message_type,
			"body": target.body,
			"content": target.content,
			"media_url": target.get("media_url") or "",
			"sender_name": target.sender_name,
		}

	for row in messages or []:
		message_id = context_message_id(row)
		if message_id:
			row["quoted_message"] = by_provider_id.get(message_id)


def context_message_id(message) -> str:
	content = _json_dict(message.get("content"))
	message_type = str(message.get("message_type") or "")
	candidates = [
		(content.get("context") or {}).get("id")
		if isinstance(content.get("context"), dict)
		else None,
		(content.get("context") or {}).get("message_id")
		if isinstance(content.get("context"), dict)
		else None,
		content.get("context_message_id"),
	]
	for nested in (content.get("payload"), content.get(message_type)):
		if isinstance(nested, dict):
			candidates.extend([
				nested.get("context_message_id"),
				(nested.get("context") or {}).get("id")
				if isinstance(nested.get("context"), dict)
				else None,
			])
	return next((str(value).strip() for value in candidates if str(value or "").strip()), "")


def _json_dict(value) -> dict:
	if isinstance(value, dict):
		return value
	if not value:
		return {}
	try:
		parsed = json.loads(value)
		return parsed if isinstance(parsed, dict) else {}
	except (TypeError, ValueError):
		return {}
