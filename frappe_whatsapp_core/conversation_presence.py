"""Ephemeral, permission-scoped operator presence for shared conversations."""

from __future__ import annotations

import re
import time

import frappe
from frappe.utils import cint

from frappe_whatsapp_core.permissions import assert_conversation_access, require_core_access
from frappe_whatsapp_core.realtime import publish_conversation_presence


PRESENCE_ACTIVE_SECONDS = 70
PRESENCE_CACHE_SECONDS = 140
_CLIENT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{8,80}$")


@frappe.whitelist(methods=["POST"])
@require_core_access()
def update_conversation_presence(
	conversation: str,
	client_id: str,
	active=1,
) -> dict:
	"""Touch or leave one browser tab's presence without writing business data."""
	conversation = str(conversation or "").strip()
	client_id = str(client_id or "").strip()
	assert_conversation_access(conversation)
	if not _CLIENT_ID_PATTERN.fullmatch(client_id):
		frappe.throw("A valid browser presence identifier is required", frappe.ValidationError)

	now = time.time()
	cache_key = _presence_key(conversation)
	field = _presence_field(frappe.session.user, client_id)
	if cint(active):
		entry = {"user": frappe.session.user, "client_id": client_id, "at": now}
		frappe.cache.hset(cache_key, field, entry)
	else:
		frappe.cache.hdel(cache_key, field)
	entries = _active_entries(cache_key, now=now)
	frappe.cache.expire(frappe.cache.make_key(cache_key), PRESENCE_CACHE_SECONDS)

	viewers, changed = _viewer_snapshot(
		cache_key,
		{entry["user"] for entry in entries.values()},
	)
	if changed:
		publish_conversation_presence(conversation, viewers, after_commit=False)
	return {"conversation": conversation, "viewers": viewers}


def _presence_key(conversation: str) -> str:
	return f"whatsapp_core:conversation_presence:{conversation}"


def _presence_field(user: str, client_id: str) -> str:
	return f"{user}|{client_id}"


def _active_entries(cache_key: str, *, now: float) -> dict[str, dict]:
	active = {}
	for raw_field, value in frappe.cache.hgetall(cache_key).items():
		field = raw_field.decode() if isinstance(raw_field, bytes) else str(raw_field)
		if not isinstance(value, dict) or now - float(value.get("at") or 0) > PRESENCE_ACTIVE_SECONDS:
			frappe.cache.hdel(cache_key, field)
			continue
		user = str(value.get("user") or "").strip()
		if not user:
			frappe.cache.hdel(cache_key, field)
			continue
		active[field] = value
	return active


def _viewer_profiles(users: set[str]) -> list[dict]:
	if not users:
		return []
	rows = frappe.get_all(
		"User",
		filters={"name": ["in", sorted(users)], "enabled": 1},
		fields=["name", "full_name", "first_name", "user_image"],
		limit_page_length=len(users),
	)
	viewers = [
		{
			"user": row.name,
			"display_name": row.full_name or row.first_name or row.name,
			"user_image": row.user_image or "",
		}
		for row in rows
	]
	return sorted(viewers, key=lambda row: (row["display_name"].casefold(), row["user"]))


def _viewer_snapshot(cache_key: str, users: set[str]) -> tuple[list[dict], bool]:
	"""Reuse the viewer projection and fan out only when the visible set changes."""
	signature = "\n".join(sorted(users))
	snapshot_key = f"{cache_key}:viewers"
	# ``expires=True`` avoids Frappe's request-local cache retaining the initial
	# miss after this expiring value is written later in the same heartbeat.
	cached = frappe.cache.get_value(snapshot_key, expires=True) or {}
	if isinstance(cached, dict) and cached.get("signature") == signature:
		return list(cached.get("viewers") or []), False
	viewers = _viewer_profiles(users)
	frappe.cache.set_value(
		snapshot_key,
		{"signature": signature, "viewers": viewers},
		expires_in_sec=PRESENCE_CACHE_SECONDS,
	)
	return viewers, True
