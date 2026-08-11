"""Business-neutral import of legacy WhatsApp contacts and conversations.

Legacy applications own their source schemas and pass a fixed, server-side
configuration to :func:`migrate_legacy_source`.  The Core app never imports a
business app and the configuration is intentionally not exposed as an HTTP
API.  Source records and tables are left untouched for rollback/audit.
"""

from __future__ import annotations

import hashlib
import json

import frappe
from frappe.utils import now_datetime

from frappe_whatsapp_core.materializer import (
	get_or_create_channel,
	get_or_create_conversation,
	get_or_create_identity,
)
from frappe_whatsapp_core.party_bindings import upsert_party_binding


def legacy_source_plan(config: dict) -> dict:
	"""Return a read-only migration plan without exposing contact information."""
	config = _validated_config(config)
	contact_source = config["contact"]
	message_source = config["message"]
	phones = frappe.get_all(
		contact_source["doctype"],
		pluck=contact_source["phone_field"],
		limit_page_length=100000,
	)
	configured_channels = [
		channel for channel in config["channels"] if channel.get("phone_number_id")
	]
	eligible_contacts = sum(bool(str(phone or "").strip()) for phone in phones)
	blockers = []
	warnings = []
	if not configured_channels:
		blockers.append("No WhatsApp channel with a phone number ID is configured")
	if not eligible_contacts:
		warnings.append("No legacy contacts contain a usable phone number")
	legacy_marker = f'%"legacy_source":"{config["source_key"]}"%'
	return {
		"source": config["source_key"],
		"migration_ready": not blockers,
		"blockers": blockers,
		"warnings": warnings,
		"source_channels": len(configured_channels),
		"source_contacts": len(phones),
		"eligible_contacts": eligible_contacts,
		"source_messages": frappe.db.count(message_source["doctype"]),
		"core_messages_from_source": frappe.db.count(
			"WhatsApp Core Message",
			{"content": ["like", legacy_marker]},
		),
		"excluded": [
			"bulk messaging jobs",
			"AI queues",
			"webhook and transport logs",
			"polls",
			"legacy scheduler state",
		],
		"source_is_read_only": True,
	}


def migrate_legacy_source(config: dict, *, batch_size: int = 500) -> dict:
	"""Idempotently import one app's channels, contacts and unique messages.

	Only the messaging history required by the shared inbox is imported.  Bulk
	jobs, AI queues, webhook logs, polls and other operational records remain in
	their legacy tables and are deliberately outside this contract.
	"""
	config = _validated_config(config)
	batch_size = max(50, min(int(batch_size), 1000))
	channels = _migrate_channels(config)
	contact_result = _migrate_contacts(config, channels)
	message_result = _migrate_messages(
		config,
		channels,
		contact_result["conversation_map"],
		batch_size,
	)
	return {
		"source": config["source_key"],
		"channels": len(channels),
		"contacts": contact_result["contacts"],
		"conversations": len(set(contact_result["conversation_map"].values())),
		"party_bindings": contact_result["party_bindings"],
		"conversations_refreshed": refresh_conversation_activity(),
		**message_result,
	}


def refresh_conversation_activity() -> int:
	"""Rebuild conversation activity from immutable Core messages."""
	frappe.db.sql(
		"""
		UPDATE `tabWhatsApp Core Conversation` AS conversation
		INNER JOIN (
			SELECT
				message.conversation,
				MAX(message.provider_timestamp) AS last_message_at,
				MAX(
					CASE WHEN message.direction = 'Inbound'
					THEN message.provider_timestamp END
				) AS last_inbound_at
			FROM `tabWhatsApp Core Message` AS message
			GROUP BY message.conversation
		) AS activity ON activity.conversation = conversation.name
		SET
			conversation.last_message_at = activity.last_message_at,
			conversation.last_inbound_at = activity.last_inbound_at
		"""
	)
	return frappe.db.sql(
		"""
		SELECT COUNT(*) FROM `tabWhatsApp Core Conversation`
		WHERE last_message_at IS NOT NULL
		"""
	)[0][0]


def _migrate_channels(config: dict) -> dict[str, object]:
	channels = {}
	for source in config["channels"]:
		phone_number_id = str(source.get("phone_number_id") or "").strip()
		if not phone_number_id:
			continue
		channel = get_or_create_channel(phone_number_id, source.get("waba_id"))
		channel.display_name = (
			str(source.get("display_name") or source.get("source_name") or phone_number_id)
			.strip()[:140]
		)
		channel.enabled = 1 if source.get("enabled", True) else 0
		channel.save(ignore_permissions=True)
		channels[str(source.get("source_name") or phone_number_id)] = channel
	if not channels:
		frappe.throw(
			f"{config['source_key']} has no configured WhatsApp channel",
			frappe.ValidationError,
		)
	return channels


def _migrate_contacts(config: dict, channels: dict[str, object]) -> dict:
	source = config["contact"]
	fields = _source_fields(
		source["doctype"],
		[
			"name",
			source["phone_field"],
			source.get("display_field"),
			source.get("account_field"),
			source.get("last_message_field"),
			*(source.get("attribute_fields") or {}).values(),
			(source.get("party") or {}).get("name_field"),
			(source.get("party") or {}).get("role_field"),
		],
	)
	rows = frappe.get_all(
		source["doctype"],
		fields=fields,
		order_by="name asc",
		limit_page_length=100000,
	)
	conversation_map = {}
	bindings = 0
	contact_count = 0
	for row in rows:
		phone = row.get(source["phone_field"])
		if not str(phone or "").strip():
			continue
		contact_count += 1
		identity = get_or_create_identity(phone)
		display_value = row.get(source.get("display_field")) if source.get("display_field") else None
		identity.display_value = str(display_value or phone).strip()[:140]
		attributes = _json_dict(identity.attributes)
		legacy_sources = attributes.setdefault("legacy_sources", {})
		legacy_sources[config["source_key"]] = {
			"doctype": source["doctype"],
			"name": row.name,
			**{
				key: row.get(fieldname)
				for key, fieldname in (source.get("attribute_fields") or {}).items()
				if row.get(fieldname) not in (None, "")
			},
		}
		identity.attributes = _json_value(attributes)
		identity.save(ignore_permissions=True)
		bindings += _migrate_party_binding(config, source, row, identity.name)

		account_name = _row_account(source, row, channels)
		channel = channels.get(account_name)
		if not channel:
			continue
		conversation = get_or_create_conversation(channel, identity)
		last_message = (
			row.get(source.get("last_message_field"))
			if source.get("last_message_field")
			else None
		)
		if last_message:
			conversation.last_message_at = last_message
			conversation.save(ignore_permissions=True)
		conversation_map[(account_name, row.name)] = conversation.name
	return {
		"contacts": contact_count,
		"party_bindings": bindings,
		"conversation_map": conversation_map,
	}


def _migrate_party_binding(config, source, row, identity: str) -> int:
	party = source.get("party") or {}
	party_doctype = str(party.get("doctype") or "").strip()
	party_name = row.get(party.get("name_field")) if party.get("name_field") else None
	if not party_doctype or not party_name or not frappe.db.exists(party_doctype, party_name):
		return 0
	party_role = row.get(party.get("role_field")) if party.get("role_field") else None
	upsert_party_binding(
		identity,
		party_doctype,
		party_name,
		workspace_key=party.get("workspace_key") or config["source_key"],
		party_role=party_role or party.get("role") or "",
		is_primary=bool(party.get("is_primary", True)),
		status="Verified",
		source=f"legacy.{config['source_key']}",
		source_reference=str(row.name),
		attributes={"legacy_contact": row.name},
	)
	return 1


def _migrate_messages(config, channels, conversation_map, batch_size: int) -> dict:
	source = config["message"]
	fields = _source_fields(
		source["doctype"],
		[
			"name", "creation", "modified",
			source.get("contact_field"), source.get("account_field"),
			source.get("direction_field"), source.get("status_field"),
			source.get("timestamp_field"), source.get("type_field"),
			source.get("body_field"), source.get("error_field"),
			source.get("inbound_phone_field"), source.get("outbound_phone_field"),
			*(source.get("provider_id_fields") or []),
			*(source.get("content_fields") or {}).values(),
		],
	)
	inserted = existing = skipped = offset = 0
	while True:
		rows = frappe.get_all(
			source["doctype"],
			fields=fields,
			order_by=f"{source.get('timestamp_field') or 'creation'} asc, name asc",
			limit_start=offset,
			limit_page_length=batch_size,
		)
		if not rows:
			break
		for row in rows:
			account_name = _row_account(source, row, channels)
			channel = channels.get(account_name)
			contact_field = source.get("contact_field")
			contact_name = row.get(contact_field) if contact_field else None
			conversation = conversation_map.get((account_name, contact_name))
			if channel and not conversation:
				conversation = _message_conversation(source, row, channel)
			if not channel or not conversation:
				skipped += 1
				continue
			provider_id = _provider_id(config["source_key"], source, row)
			message_key = hashlib.sha256(f"{channel.name}:{provider_id}".encode()).hexdigest()
			if frappe.db.exists("WhatsApp Core Message", message_key) or frappe.db.exists(
				"WhatsApp Core Message", {"provider_message_id": provider_id}
			):
				existing += 1
				continue
			direction = _direction(row.get(source.get("direction_field")))
			content = {
				"legacy_source": config["source_key"],
				"legacy_doctype": source["doctype"],
				"legacy_message": row.name,
				**{
					key: row.get(fieldname)
					for key, fieldname in (source.get("content_fields") or {}).items()
					if row.get(fieldname) not in (None, "")
				},
			}
			error = row.get(source.get("error_field")) if source.get("error_field") else None
			frappe.get_doc({
				"doctype": "WhatsApp Core Message",
				"message_key": message_key,
				"conversation": conversation,
				"channel": channel.name,
				"provider_message_id": provider_id,
				"direction": direction,
				"message_type": str(row.get(source.get("type_field")) or "unknown").lower(),
				"body": str(row.get(source.get("body_field")) or ""),
				"content": _json_value(content),
				"provider_timestamp": (
					row.get(source.get("timestamp_field"))
					if source.get("timestamp_field")
					else None
				) or row.get("creation") or row.get("modified") or now_datetime(),
				"delivery_status": _delivery_status(
					direction,
					row.get(source.get("status_field")) if source.get("status_field") else None,
				),
				"failure": _json_value({"legacy_error": error}) if error else None,
			}).insert(ignore_permissions=True)
			inserted += 1
		offset += len(rows)
	return {
		"messages_inserted": inserted,
		"messages_existing": existing,
		"messages_skipped": skipped,
	}


def _message_conversation(source, row, channel):
	direction = _direction(row.get(source.get("direction_field")))
	phone_field = (
		source.get("inbound_phone_field")
		if direction == "Inbound"
		else source.get("outbound_phone_field")
	)
	phone = row.get(phone_field) if phone_field else None
	if not str(phone or "").strip():
		return None
	identity = get_or_create_identity(phone)
	return get_or_create_conversation(channel, identity).name


def _row_account(source, row, channels) -> str:
	account_field = source.get("account_field")
	account_name = str(row.get(account_field) or "").strip() if account_field else ""
	if account_name:
		return account_name
	default = str(source.get("default_account") or "").strip()
	return default or next(iter(channels), "")


def _provider_id(source_key: str, source: dict, row) -> str:
	for fieldname in source.get("provider_id_fields") or []:
		value = str(row.get(fieldname) or "").strip()
		if value:
			return value
	return f"legacy:{source_key}:{source['doctype']}:{row.get('name')}"


def _direction(value) -> str:
	return "Inbound" if str(value or "").strip().lower() == "inbound" else "Outbound"


def _delivery_status(direction: str, value) -> str:
	if direction == "Inbound":
		return "Received"
	return {
		"queued": "Queued",
		"sent": "Sent",
		"delivered": "Delivered",
		"read": "Read",
		"failed": "Failed",
		"deleted": "Deleted",
	}.get(str(value or "").strip().lower(), "Queued")


def _source_fields(doctype: str, candidates) -> list[str]:
	meta = frappe.get_meta(doctype)
	fields = []
	for fieldname in candidates:
		if not fieldname or fieldname in fields:
			continue
		if fieldname in {"name", "creation", "modified"} or meta.has_field(fieldname):
			fields.append(fieldname)
	return fields


def _validated_config(config: dict) -> dict:
	if not isinstance(config, dict):
		frappe.throw("Legacy migration config must be an object", frappe.ValidationError)
	for key in ("source_key", "channels", "contact", "message"):
		if not config.get(key):
			frappe.throw(f"Legacy migration config requires {key}", frappe.ValidationError)
	for section in ("contact", "message"):
		if not frappe.db.exists("DocType", config[section].get("doctype")):
			frappe.throw(
				f"Legacy {section} DocType {config[section].get('doctype')} was not found",
				frappe.DoesNotExistError,
			)
	return config


def _json_dict(value) -> dict:
	if isinstance(value, dict):
		return dict(value)
	if not value:
		return {}
	try:
		parsed = json.loads(value)
		return parsed if isinstance(parsed, dict) else {}
	except (TypeError, ValueError):
		return {}


def _json_value(value: dict) -> str:
	return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
