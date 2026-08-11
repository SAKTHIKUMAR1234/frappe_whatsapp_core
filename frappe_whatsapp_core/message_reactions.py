from __future__ import annotations

import json

import frappe


def attach_message_reactions(messages, conversation: str, limit: int = 2000) -> None:
	"""Attach reaction metadata to its target without exposing reaction rows as chat bubbles."""
	if not messages:
		return
	targets = {
		str(row.get("provider_message_id") or ""): row
		for row in messages
		if row.get("provider_message_id")
	}
	if not targets:
		return
	reactions = frappe.get_all(
		"WhatsApp Core Message",
		filters={"conversation": conversation, "message_type": "reaction"},
		fields=[
			"name",
			"provider_message_id",
			"direction",
			"content",
			"owner",
			"provider_timestamp",
			"creation",
		],
		order_by="provider_timestamp asc, creation asc",
		limit_page_length=max(1, min(int(limit or 2000), 5000)),
	)
	owners = {row.owner for row in reactions if row.direction == "Outbound" and row.owner}
	owner_names = {
		row.name: row.full_name or row.name
		for row in frappe.get_all(
			"User",
			filters={"name": ["in", list(owners)]},
			fields=["name", "full_name"],
			limit_page_length=len(owners),
		)
	} if owners else {}
	by_target = {}
	for row in reactions:
		reaction = reaction_from_content(row.content)
		target_id = str(reaction.get("message_id") or "")
		if target_id not in targets:
			continue
		actor_key = f"{row.direction}:{row.owner or 'remote'}"
		bucket = by_target.setdefault(target_id, {})
		emoji = str(reaction.get("emoji") or "")
		if not emoji:
			bucket.pop(actor_key, None)
			continue
		bucket[actor_key] = {
			"message": row.name,
			"emoji": emoji,
			"direction": row.direction,
			"actor_key": actor_key,
			"actor": (
				owner_names.get(row.owner, row.owner)
				if row.direction == "Outbound"
				else "Contact"
			),
			"provider_timestamp": row.provider_timestamp,
		}
	for target_id, target in targets.items():
		target["reactions"] = list((by_target.get(target_id) or {}).values())


def reaction_from_content(content) -> dict:
	value = _dict(content)
	for candidate in (
		value.get("reaction"),
		value.get("payload"),
		(value.get("payload") or {}).get("reaction") if isinstance(value.get("payload"), dict) else None,
	):
		if isinstance(candidate, dict) and ("message_id" in candidate or "emoji" in candidate):
			return candidate
	return {}


def _dict(value) -> dict:
	if isinstance(value, dict):
		return value
	if not value:
		return {}
	try:
		parsed = json.loads(value)
		return parsed if isinstance(parsed, dict) else {}
	except (TypeError, ValueError):
		return {}
