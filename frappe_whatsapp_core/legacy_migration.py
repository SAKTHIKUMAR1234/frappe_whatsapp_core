"""Business-neutral import of legacy WhatsApp contacts and conversations.

Legacy applications own their source schemas and pass a fixed, server-side
configuration to :func:`migrate_legacy_source`.  The Core app never imports a
business app and the configuration is intentionally not exposed as an HTTP
API.  Source records and tables are left untouched for rollback/audit.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from urllib.parse import unquote, urlsplit

import frappe
from frappe.utils import now_datetime

from frappe_whatsapp_core.materializer import (
	get_or_create_channel,
	get_or_create_conversation,
	get_or_create_identity,
)
from frappe_whatsapp_core.party_bindings import upsert_party_binding
from frappe_whatsapp_core.template_catalog import scoped_template_key


def legacy_source_plan(config: dict) -> dict:
	"""Return a read-only migration plan without exposing contact information."""
	config = _validated_config(config)
	contact_source = config["contact"]
	message_sources = _message_sources(config)
	phones = frappe.get_all(
		contact_source["doctype"],
		pluck=contact_source["phone_field"],
		limit_page_length=100000,
	)
	configured_channels, using_core_fallback = _resolved_channel_sources(config)
	eligible_contacts = sum(bool(str(phone or "").strip()) for phone in phones)
	blockers = []
	warnings = []
	if not configured_channels:
		blockers.append("No WhatsApp channel with a phone number ID is configured")
	elif using_core_fallback:
		warnings.append(
			"Legacy routing is missing; migration will use the sole enabled WhatsApp Core channel"
		)
	if not eligible_contacts:
		warnings.append("No legacy contacts contain a usable phone number")
	legacy_marker = f"%{config['source_key']}%"
	template_source = config.get("template") or {}
	campaign_source = config.get("campaign") or {}
	category_source = config.get("category") or {}
	source_messages = sum(frappe.db.count(source["doctype"]) for source in message_sources)
	source_media_files = sum(_source_local_media_count(source) for source in message_sources)
	source_templates = frappe.db.count(template_source["doctype"]) if template_source else 0
	source_campaigns = frappe.db.count(campaign_source["doctype"]) if campaign_source else 0
	recipient_source = campaign_source.get("recipient") or {}
	source_campaign_recipients = frappe.db.count(recipient_source["doctype"]) if recipient_source else 0
	source_categories = frappe.db.count(category_source["doctype"]) if category_source else 0
	assignment_source = category_source.get("assignment") or {}
	source_category_assignments = (
		frappe.db.count(
			assignment_source["doctype"],
			{"parenttype": assignment_source["message_doctype"]},
		)
		if assignment_source
		else 0
	)
	warnings.append(
		"Per-user read markers are not present in the legacy schemas and will start fresh in Core"
	)
	return {
		"source": config["source_key"],
		"migration_ready": not blockers,
		"blockers": blockers,
		"warnings": warnings,
		"source_channels": len(configured_channels),
		"source_contacts": len(phones),
		"eligible_contacts": eligible_contacts,
		"source_messages": source_messages,
		"source_media_files": source_media_files,
		"source_templates": source_templates,
		"source_campaigns": source_campaigns,
		"source_campaign_recipients": source_campaign_recipients,
		"source_categories": source_categories,
		"source_category_assignments": source_category_assignments,
		"core_messages_from_source": frappe.db.count(
			"WhatsApp Core Message",
			{"content": ["like", legacy_marker]},
		),
		"excluded": [
			"webhook and transport logs",
			"retry and delivery work queues",
			"AI runtime queues and model settings",
			"polls",
			"legacy scheduler state",
		],
		"included": [
			"channels and account routing",
			"contacts, identities, conversations and party bindings",
			"message history, provider IDs, media metadata and delivery status",
			"templates and component definitions",
			"historical campaigns and recipients",
			"message categories and assignments when available",
		],
		"source_is_read_only": True,
		"rerun_safe": True,
	}


def migrate_legacy_source(
	config: dict,
	*,
	batch_size: int = 500,
	commit_every_batch: bool = False,
) -> dict:
	"""Idempotently import one app's channels, contacts and unique messages.

	Business records required after cutover are copied; operational queues and
	webhook logs remain in their legacy tables and are never replayed.  Every
	target key is deterministic, so a failed run can safely resume by rerunning.
	"""
	config = _validated_config(config)
	batch_size = max(50, min(int(batch_size), 1000))
	channels = _migrate_channels(config)
	contact_result = _migrate_contacts(config, channels)
	message_result = _migrate_all_messages(
		config,
		channels,
		contact_result["conversation_map"],
		batch_size,
		commit_every_batch=commit_every_batch,
	)
	history_result = migrate_legacy_history(
		config,
		channels=channels,
		legacy_message_map=message_result.pop("_legacy_message_map"),
		batch_size=batch_size,
		commit_every_batch=commit_every_batch,
	)
	if commit_every_batch:
		frappe.db.commit()
	result = {
		"source": config["source_key"],
		"channels": len(channels),
		"contacts": contact_result["contacts"],
		"conversations": len(set(contact_result["conversation_map"].values())),
		"party_bindings": contact_result["party_bindings"],
		"conversations_refreshed": refresh_conversation_activity(),
		**history_result,
		**message_result,
		"source_is_read_only": True,
		"rerun_safe": True,
	}
	result["reconciliation"] = _migration_reconciliation(config, result)
	result["reconciliation_ok"] = all(check["ok"] for check in result["reconciliation"].values())
	return result


def migrate_legacy_history(
	config: dict,
	*,
	channels: dict[str, object],
	legacy_message_map: dict | None = None,
	batch_size: int = 500,
	commit_every_batch: bool = False,
) -> dict:
	"""Import reusable templates and immutable campaign/category history."""
	config = _validated_config(config)
	template_result = _migrate_templates(config, channels)
	campaign_result = _migrate_campaigns(
		config,
		channels,
		template_result.pop("_template_map"),
		legacy_message_map or {},
		batch_size=max(50, min(int(batch_size), 1000)),
		commit_every_batch=commit_every_batch,
	)
	category_result = _migrate_categories(config, legacy_message_map or {})
	return {
		**template_result,
		**campaign_result,
		**category_result,
	}


def _migration_reconciliation(config: dict, result: dict) -> dict:
	plan = legacy_source_plan(config)
	checks = {
		"channels": (
			plan["source_channels"],
			result["channels"],
			"exact",
		),
		"contacts": (
			plan["eligible_contacts"],
			result["contacts"],
			"exact",
		),
		"messages": (
			plan["source_messages"],
			sum(
				result.get(key, 0)
				for key in (
					"messages_inserted",
					"messages_existing",
					"messages_skipped",
				)
			),
			"exact",
		),
		"media_files": (
			plan["source_media_files"],
			sum(
				result.get(key, 0)
				for key in (
					"media_files_inserted",
					"media_files_existing",
					"media_files_skipped",
				)
			),
			"exact",
		),
		"templates": (
			plan["source_templates"],
			sum(
				result.get(key, 0)
				for key in (
					"templates_inserted",
					"templates_existing",
					"templates_skipped",
				)
			),
			"exact",
		),
		"campaigns": (
			plan["source_campaigns"],
			sum(
				result.get(key, 0)
				for key in (
					"campaigns_inserted",
					"campaigns_existing",
					"campaigns_skipped",
				)
			),
			"at_least",
		),
		"campaign_recipients": (
			plan["source_campaign_recipients"],
			sum(
				result.get(key, 0)
				for key in (
					"campaign_recipients_inserted",
					"campaign_recipients_existing",
					"campaign_recipients_skipped",
				)
			),
			"exact",
		),
		"categories": (
			plan["source_categories"],
			result.get("categories_inserted", 0) + result.get("categories_existing", 0),
			"exact",
		),
		"category_assignments": (
			plan["source_category_assignments"],
			sum(
				result.get(key, 0)
				for key in (
					"category_assignments_inserted",
					"category_assignments_existing",
					"category_assignments_skipped",
				)
			),
			"exact",
		),
	}
	return {
		name: {
			"source": source_count,
			"processed": processed_count,
			"ok": (
				processed_count >= source_count
				if comparison == "at_least"
				else processed_count == source_count
			),
		}
		for name, (source_count, processed_count, comparison) in checks.items()
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
	sources, _using_core_fallback = _resolved_channel_sources(config)
	settings = frappe.get_single("WhatsApp Core Settings")
	settings_changed = False
	for source in sources:
		phone_number_id = str(source.get("phone_number_id") or "").strip()
		if not phone_number_id:
			continue
		channel = get_or_create_channel(phone_number_id, source.get("waba_id"))
		channel.display_name = str(
			source.get("display_name") or source.get("source_name") or phone_number_id
		).strip()[:140]
		channel.enabled = 1 if source.get("enabled", True) else 0
		channel.save(ignore_permissions=True)
		source_name = str(source.get("source_name") or phone_number_id).strip()
		account_name, mapping_created = _ensure_legacy_channel_mapping(
			settings,
			channel.name,
			str(source.get("account_name") or source_name).strip(),
		)
		settings_changed = settings_changed or mapping_created
		channel._legacy_hub_account_name = account_name
		channels[source_name] = channel
	if not channels:
		frappe.throw(
			f"{config['source_key']} has no configured WhatsApp channel",
			frappe.ValidationError,
		)
	if settings_changed:
		settings.save(ignore_permissions=True)
	return channels


def _ensure_legacy_channel_mapping(settings, channel: str, account_name: str) -> tuple[str, bool]:
	"""Return the canonical Hub account for a migrated channel.

	A legacy import can create its Core channel before Integration has projected
	account routing. Templates, however, must always carry the same account/channel
	identity used by live transport. Reuse an existing channel mapping when one is
	present; otherwise create the unambiguous legacy mapping without overwriting a
	different route.
	"""
	for row in settings.accounts:
		if row.channel == channel:
			return str(row.account_name or "").strip(), False
	if not account_name:
		frappe.throw(
			f"A Hub account name is required for migrated Core channel {channel}",
			frappe.ValidationError,
		)
	for row in settings.accounts:
		if row.account_name == account_name:
			frappe.throw(
				f"Hub account {account_name} is already mapped to Core channel {row.channel}; "
				f"it cannot also map to {channel}",
				frappe.ValidationError,
			)
	settings.append(
		"accounts",
		{
			"account_name": account_name,
			"channel": channel,
			"is_default": 1 if not settings.accounts else 0,
		},
	)
	return account_name, True


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
		contact_channels = (
			channels.items()
			if source.get("all_channels") and not source.get("account_field")
			else [(account_name, channels.get(account_name))]
		)
		for mapped_account, channel in contact_channels:
			if not channel:
				continue
			conversation = get_or_create_conversation(channel, identity)
			last_message = (
				row.get(source.get("last_message_field")) if source.get("last_message_field") else None
			)
			if last_message:
				conversation.last_message_at = last_message
				conversation.save(ignore_permissions=True)
			conversation_map[(mapped_account, row.name)] = conversation.name
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


def _migrate_all_messages(
	config,
	channels,
	conversation_map,
	batch_size: int,
	*,
	commit_every_batch: bool = False,
) -> dict:
	total = {
		"messages_inserted": 0,
		"messages_existing": 0,
		"messages_skipped": 0,
		"media_files_inserted": 0,
		"media_files_existing": 0,
		"media_files_skipped": 0,
		"files_reattached": 0,
		"files_already_attached": 0,
	}
	legacy_message_map = {}
	for source in _message_sources(config):
		result = _migrate_message_source(
			config,
			source,
			channels,
			conversation_map,
			batch_size,
			commit_every_batch=commit_every_batch,
		)
		for key in total:
			total[key] += result[key]
		legacy_message_map.update(result["_legacy_message_map"])
	total["_legacy_message_map"] = legacy_message_map
	return total


def _migrate_message_source(
	config,
	source,
	channels,
	conversation_map,
	batch_size: int,
	*,
	commit_every_batch: bool = False,
) -> dict:
	fields = _source_fields(
		source["doctype"],
		[
			"name",
			"creation",
			"modified",
			source.get("contact_field"),
			source.get("account_field"),
			source.get("direction_field"),
			source.get("status_field"),
			source.get("timestamp_field"),
			source.get("type_field"),
			source.get("body_field"),
			source.get("error_field"),
			source.get("inbound_phone_field"),
			source.get("outbound_phone_field"),
			*(source.get("provider_id_fields") or []),
			*(source.get("content_fields") or {}).values(),
		],
	)
	inserted = existing = skipped = offset = 0
	files_reattached = files_already_attached = 0
	media_counts = {"inserted": 0, "existing": 0, "skipped": 0}
	legacy_message_map = {}
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
		candidates = {}
		provider_ids = []
		message_keys = []
		for row in rows:
			account_name = _row_account(source, row, channels)
			channel = channels.get(account_name)
			provider_id = _provider_id(config["source_key"], source, row)
			message_key = (
				hashlib.sha256(f"{channel.name}:{provider_id}".encode()).hexdigest() if channel else ""
			)
			candidates[row.name] = (account_name, channel, provider_id, message_key)
			provider_ids.append(provider_id)
			if message_key:
				message_keys.append(message_key)
		existing_by_provider, existing_by_key, existing_content = _existing_message_candidates(
			provider_ids,
			message_keys,
		)
		for row in rows:
			account_name, channel, provider_id, message_key = candidates[row.name]
			contact_field = source.get("contact_field")
			contact_name = row.get(contact_field) if contact_field else None
			conversation = conversation_map.get((account_name, contact_name))
			if channel and not conversation:
				conversation = _message_conversation(source, row, channel)
			if not channel or not conversation:
				skipped += 1
				continue
			direction = _direction(row.get(source.get("direction_field")))
			message_type = str(row.get(source.get("type_field")) or "unknown").lower()
			content = _legacy_message_content(config, source, row, message_type)
			existing_name = existing_by_key.get(message_key) or existing_by_provider.get(provider_id)
			if existing_name:
				existing += 1
				existing_content[existing_name] = _annotate_existing_message(
					existing_name,
					config["source_key"],
					source["doctype"],
					row.name,
					existing_content.get(existing_name),
					content,
				)
				_media_result(media_counts, _media_reference_result(content, existing=True))
				attachment_result = _reattach_legacy_files(source, row, existing_name)
				files_reattached += attachment_result["reattached"]
				files_already_attached += attachment_result["already_attached"]
				legacy_message_map[(source["doctype"], row.name)] = existing_name
				legacy_message_map.setdefault(row.name, existing_name)
				continue
			error = row.get(source.get("error_field")) if source.get("error_field") else None
			message_doc = frappe.get_doc(
				{
					"doctype": "WhatsApp Core Message",
					"message_key": message_key,
					"conversation": conversation,
					"channel": channel.name,
					"provider_message_id": provider_id,
					"direction": direction,
					"message_type": message_type,
					"body": str(row.get(source.get("body_field")) or ""),
					"content": _json_value(content),
					"provider_timestamp": (
						row.get(source.get("timestamp_field")) if source.get("timestamp_field") else None
					)
					or row.get("creation")
					or row.get("modified")
					or now_datetime(),
					"delivery_status": _delivery_status(
						direction,
						row.get(source.get("status_field")) if source.get("status_field") else None,
					),
					"failure": _json_value({"legacy_error": error}) if error else None,
				}
			).insert(ignore_permissions=True)
			legacy_message_map[(source["doctype"], row.name)] = message_doc.name
			legacy_message_map.setdefault(row.name, message_doc.name)
			_media_result(media_counts, _media_reference_result(content, existing=False))
			attachment_result = _reattach_legacy_files(source, row, message_doc.name)
			files_reattached += attachment_result["reattached"]
			files_already_attached += attachment_result["already_attached"]
			existing_by_key[message_key] = message_doc.name
			existing_by_provider[provider_id] = message_doc.name
			existing_content[message_doc.name] = content
			inserted += 1
		offset += len(rows)
		if commit_every_batch:
			frappe.db.commit()
	return {
		"messages_inserted": inserted,
		"messages_existing": existing,
		"messages_skipped": skipped,
		"media_files_inserted": media_counts["inserted"],
		"media_files_existing": media_counts["existing"],
		"media_files_skipped": media_counts["skipped"],
		"files_reattached": files_reattached,
		"files_already_attached": files_already_attached,
		"_legacy_message_map": legacy_message_map,
	}


def _legacy_message_content(config, source, row, message_type: str) -> dict:
	content = {
		"legacy_source": config["source_key"],
		"legacy_doctype": source["doctype"],
		"legacy_message": row.name,
		"legacy_sources": {
			f"{config['source_key']}:{source['doctype']}": row.name,
		},
		**{
			key: row.get(fieldname)
			for key, fieldname in (source.get("content_fields") or {}).items()
			if row.get(fieldname) not in (None, "")
		},
	}
	# Legacy template sends can carry an image/video/document header in the same
	# media columns as ordinary media messages.  Preserve that attachment while
	# retaining the original message type and template metadata.
	if message_type not in {"audio", "document", "image", "sticker", "template", "video"}:
		return content
	local_url = _local_media_url(source, row)
	media_id = _text(content.get("media_id"))
	local_file_exists = bool(local_url and frappe.db.exists("File", {"file_url": local_url}))
	if local_url and not local_file_exists:
		# Retain an auditable source reference, but do not expose a local link
		# when the legacy File record itself is absent.
		content["legacy_missing_file_url"] = local_url
	if not media_id and not local_file_exists:
		return content
	descriptor = {
		"filename": _text(content.get("file_name")),
		"mime_type": _text(content.get("mime_type")),
	}
	if media_id:
		descriptor["id"] = media_id
	if local_file_exists:
		# Reference the existing site File URL. The physical blob stays in place;
		# attachment metadata is re-pointed after the Core message is available.
		descriptor["local_file_url"] = local_url
	content["payload"] = {key: value for key, value in descriptor.items() if value}
	return content


def _media_reference_result(content: dict, *, existing: bool) -> str | None:
	payload = content.get("payload") if isinstance(content, dict) else None
	if isinstance(payload, dict) and payload.get("local_file_url"):
		return "existing" if existing else "inserted"
	if isinstance(content, dict) and content.get("legacy_missing_file_url"):
		return "skipped"
	return None


def _media_result(counts: dict, result: str | None) -> None:
	if result in counts:
		counts[result] += 1


def _reattach_legacy_files(source, row, core_message: str) -> dict:
	"""Point legacy message File rows at their migrated Core message.

	Only File attachment metadata changes. The file URL and physical bytes are
	left untouched. Files owned by another business document remain attached to
	that document even when a WhatsApp message references their URL.
	"""
	legacy_files = frappe.get_all(
		"File",
		filters={
			"attached_to_doctype": source["doctype"],
			"attached_to_name": row.name,
		},
		pluck="name",
		limit_page_length=1000,
	)
	for file_name in legacy_files:
		frappe.db.set_value(
			"File",
			file_name,
			{
				"attached_to_doctype": "WhatsApp Core Message",
				"attached_to_name": core_message,
			},
			update_modified=False,
		)
	local_url = _local_media_url(source, row)
	already_attached = 0
	if not legacy_files and local_url:
		already_attached = frappe.db.count(
			"File",
			{
				"file_url": local_url,
				"attached_to_doctype": "WhatsApp Core Message",
				"attached_to_name": core_message,
			},
		)
	return {
		"reattached": len(legacy_files),
		"already_attached": already_attached,
	}


def _local_media_url(source, row) -> str:
	for fieldname in source.get("local_media_fields") or []:
		value = _text(row.get(fieldname))
		if not value:
			continue
		if value.startswith(("/files/", "/private/files/")):
			return value.split("?", 1)[0].split("#", 1)[0]
		# Restored legacy sites commonly retain their public production origin
		# (for example https://sihma.org/files/...) in message rows.  The File
		# record itself still uses a site-local path, so normalize only Frappe's
		# two file namespaces and let the File lookup prove that the blob exists.
		parsed = urlsplit(value)
		if parsed.scheme in {"http", "https"}:
			path = unquote(parsed.path)
			if path.startswith(("/files/", "/private/files/")):
				return path
	return ""


def _source_local_media_count(source) -> int:
	if not source.get("local_media_fields"):
		return 0
	fields = _source_fields(
		source["doctype"],
		["name", *(source.get("local_media_fields") or [])],
	)
	if len(fields) == 1:
		return 0
	return sum(
		bool(_local_media_url(source, row))
		for row in frappe.get_all(
			source["doctype"],
			fields=fields,
			limit_page_length=1000000,
		)
	)


def _existing_message_candidates(provider_ids, message_keys) -> tuple[dict, dict, dict]:
	provider_rows = (
		frappe.get_all(
			"WhatsApp Core Message",
			filters={"provider_message_id": ["in", list(dict.fromkeys(provider_ids))]},
			fields=["name", "provider_message_id", "content"],
			limit_page_length=max(len(provider_ids), 1),
		)
		if provider_ids
		else []
	)
	key_rows = (
		frappe.get_all(
			"WhatsApp Core Message",
			filters={"name": ["in", list(dict.fromkeys(message_keys))]},
			fields=["name", "content"],
			limit_page_length=max(len(message_keys), 1),
		)
		if message_keys
		else []
	)
	return (
		{row.provider_message_id: row.name for row in provider_rows},
		{row.name: row.name for row in key_rows},
		{row.name: row.content for row in [*provider_rows, *key_rows]},
	)


def _annotate_existing_message(
	message_name: str,
	source_key: str,
	source_doctype: str,
	source_name: str,
	content_value=None,
	source_content: dict | None = None,
) -> dict:
	content = _json_dict(
		content_value
		if content_value is not None
		else frappe.db.get_value("WhatsApp Core Message", message_name, "content")
	)
	legacy_sources = content.setdefault("legacy_sources", {})
	marker = f"{source_key}:{source_doctype}"
	content_changed = legacy_sources.get(marker) != source_name
	if source_content:
		for key, value in source_content.items():
			if key == "legacy_sources":
				for legacy_key, legacy_name in value.items():
					if legacy_sources.get(legacy_key) != legacy_name:
						legacy_sources[legacy_key] = legacy_name
						content_changed = True
			elif key not in content and value not in (None, "", [], {}):
				content[key] = value
				content_changed = True
	if not content_changed:
		return content
	legacy_sources[marker] = source_name
	content.setdefault("legacy_source", source_key)
	content.setdefault("legacy_doctype", source_doctype)
	content.setdefault("legacy_message", source_name)
	frappe.db.set_value(
		"WhatsApp Core Message",
		message_name,
		"content",
		_json_value(content),
		update_modified=False,
	)
	return content


def _migrate_templates(config, channels) -> dict:
	source = config.get("template") or {}
	if not source:
		return {
			"templates_inserted": 0,
			"templates_existing": 0,
			"templates_skipped": 0,
			"_template_map": {},
		}
	fields = _source_fields(
		source["doctype"],
		[
			"name",
			"creation",
			"modified",
			source.get("name_field"),
			source.get("language_field"),
			source.get("category_field"),
			source.get("status_field"),
			source.get("provider_id_field"),
			source.get("provider_id_json_field"),
			source.get("account_field"),
			source.get("header_type_field"),
			source.get("header_content_field"),
			source.get("body_field"),
			source.get("footer_field"),
			source.get("components_field"),
			source.get("last_synced_field"),
		],
	)
	rows = frappe.get_all(
		source["doctype"],
		fields=fields,
		order_by="name asc",
		limit_page_length=100000,
	)
	inserted = existing = skipped = 0
	template_map = {}
	for row in rows:
		template_name = _text(row.get(source.get("name_field")))
		language = _text(row.get(source.get("language_field"))) or "en"
		if not template_name:
			skipped += 1
			continue
		route_account = _row_account(source, row, channels)
		channel = channels.get(route_account)
		account = str(getattr(channel, "_legacy_hub_account_name", "") or "").strip()
		if not route_account or not account or not channel:
			skipped += 1
			continue
		template_key = scoped_template_key(account, template_name, language)
		existing_name = frappe.db.exists("WhatsApp Core Template", template_key)
		if existing_name:
			existing += 1
			core_name = existing_name
		else:
			status = _approval_status(row.get(source.get("status_field")))
			components = _template_components(source, row)
			provider_template_id = _text(row.get(source.get("provider_id_field")))
			provider_payload = _json_any(
				row.get(source.get("provider_id_json_field"))
				if source.get("provider_id_json_field")
				else None,
				{},
			)
			if isinstance(provider_payload, dict):
				provider_template_id = _text(
					provider_payload.get("id") or provider_payload.get("template_id") or provider_template_id
				)
			core_doc = frappe.get_doc(
				{
					"doctype": "WhatsApp Core Template",
					"template_key": template_key,
					"account_name": account,
					"channel": channel.name,
					"template_name": template_name,
					"language_code": language,
					"category": _text(row.get(source.get("category_field"))),
					"approval_status": status,
					"enabled": 0 if status == "DISABLED" else 1,
					"template_id": provider_template_id,
					"header_type": _text(row.get(source.get("header_type_field"))),
					"header_content": _text(row.get(source.get("header_content_field"))),
					"body_text": _text(row.get(source.get("body_field"))),
					"footer_text": _text(row.get(source.get("footer_field"))),
					"components": _json_value(components),
					"last_synced_at": (
						row.get(source.get("last_synced_field")) if source.get("last_synced_field") else None
					)
					or row.get("modified")
					or row.get("creation")
					or now_datetime(),
				}
			).insert(ignore_permissions=True)
			core_name = core_doc.name
			inserted += 1
		for legacy_name in {row.name, template_name}:
			template_map[(route_account, legacy_name)] = core_name
			template_map[(account, legacy_name)] = core_name
			template_map.setdefault(("", legacy_name), core_name)
	return {
		"templates_inserted": inserted,
		"templates_existing": existing,
		"templates_skipped": skipped,
		"_template_map": template_map,
	}


def _template_components(source: dict, row) -> list:
	raw = row.get(source.get("components_field")) if source.get("components_field") else None
	parsed = _json_any(raw, None)
	if isinstance(parsed, dict):
		parsed = parsed.get("components")
	if isinstance(parsed, list) and parsed:
		return parsed
	components = []
	header_type = _text(row.get(source.get("header_type_field"))).upper()
	header_content = _text(row.get(source.get("header_content_field")))
	if header_type:
		header = {"type": "HEADER", "format": header_type}
		if header_content:
			header["text"] = header_content
		components.append(header)
	body = _text(row.get(source.get("body_field")))
	if body:
		components.append({"type": "BODY", "text": body})
	footer = _text(row.get(source.get("footer_field")))
	if footer:
		components.append({"type": "FOOTER", "text": footer})
	template_doc = None
	button_source = source.get("buttons") or {}
	if button_source:
		template_doc = frappe.get_doc(source["doctype"], row.name)
		buttons = []
		for child in template_doc.get(button_source.get("field")) or []:
			button = {
				"type": _text(child.get(button_source.get("type_field"))).upper(),
				"text": _text(child.get(button_source.get("text_field"))),
			}
			for target, fieldname in (button_source.get("extra_fields") or {}).items():
				value = child.get(fieldname)
				if value not in (None, ""):
					button[target] = value
			buttons.append({key: value for key, value in button.items() if value})
		if buttons:
			components.append({"type": "BUTTONS", "buttons": buttons})
	sample_source = source.get("samples") or {}
	if sample_source:
		template_doc = template_doc or frappe.get_doc(source["doctype"], row.name)
		samples = defaultdict(list)
		for child in template_doc.get(sample_source.get("field")) or []:
			component = _text(child.get(sample_source.get("component_field"))).upper()
			value = child.get(sample_source.get("value_field"))
			if component and value not in (None, ""):
				samples[component].append(
					(
						child.get(sample_source.get("position_field")) or child.idx,
						value,
					)
				)
		for component_name, values in samples.items():
			component = next(
				(item for item in components if _text(item.get("type")).upper() == component_name),
				None,
			)
			if not component:
				continue
			ordered = [
				value for _position, value in sorted(values, key=lambda item: _sample_sort_key(item[0]))
			]
			if component_name == "HEADER":
				component["example"] = {"header_text": ordered}
			elif component_name == "BODY":
				component["example"] = {"body_text": [ordered]}
	return components


def _sample_sort_key(value) -> tuple:
	text = _text(value)
	return (0, int(text)) if text.isdigit() else (1, text.casefold())


def _migrate_campaigns(
	config,
	channels,
	template_map,
	legacy_message_map,
	*,
	batch_size: int,
	commit_every_batch: bool,
) -> dict:
	source = config.get("campaign") or {}
	if not source:
		return {
			"campaigns_inserted": 0,
			"campaigns_existing": 0,
			"campaigns_skipped": 0,
			"campaign_recipients_inserted": 0,
			"campaign_recipients_existing": 0,
			"campaign_recipients_skipped": 0,
		}
	recipient_source = source["recipient"]
	parent_fields = _source_fields(
		source["doctype"],
		[
			"name",
			"creation",
			"modified",
			source.get("title_field"),
			source.get("description_field"),
			source.get("status_field"),
			source.get("template_field"),
			source.get("language_field"),
			source.get("account_field"),
			source.get("started_field"),
			source.get("completed_field"),
			*(source.get("audience_fields") or {}).values(),
		],
	)
	parents = frappe.get_all(
		source["doctype"],
		fields=parent_fields,
		order_by="name asc",
		limit_page_length=100000,
	)
	result = {
		"campaigns_inserted": 0,
		"campaigns_existing": 0,
		"campaigns_skipped": 0,
		"campaign_recipients_inserted": 0,
		"campaign_recipients_existing": 0,
		"campaign_recipients_skipped": 0,
	}
	for parent in parents:
		groups = _campaign_recipient_groups(source, recipient_source, parent)
		for (account_name, template_name), recipients in groups.items():
			channel = channels.get(account_name) or (
				next(iter(channels.values()), None) if not account_name else None
			)
			if not channel:
				result["campaigns_skipped"] += 1
				result["campaign_recipients_skipped"] += len(recipients)
				continue
			core_template = template_map.get((account_name, template_name)) or template_map.get(
				("", template_name)
			)
			campaign_key = _legacy_key(
				config["source_key"],
				source["doctype"],
				parent.name,
				account_name,
				template_name,
			)
			existing_name = frappe.db.exists("WhatsApp Core Campaign", campaign_key)
			if existing_name:
				campaign_name = existing_name
				result["campaigns_existing"] += 1
			else:
				title = _text(parent.get(source.get("title_field"))) or parent.name
				if len(groups) > 1:
					suffix = " / ".join(value for value in (account_name, template_name) if value)
					title = f"{title} · {suffix}" if suffix else title
				audience = {
					"legacy_source": config["source_key"],
					"legacy_doctype": source["doctype"],
					"legacy_campaign": parent.name,
					"legacy_status": parent.get(source.get("status_field")),
					"legacy_account": account_name,
					"legacy_template": template_name,
					**{
						key: parent.get(fieldname)
						for key, fieldname in (source.get("audience_fields") or {}).items()
						if parent.get(fieldname) not in (None, "")
					},
				}
				core_doc = frappe.get_doc(
					{
						"doctype": "WhatsApp Core Campaign",
						"campaign_key": campaign_key,
						"title": title[:140],
						"description": _text(parent.get(source.get("description_field")))[:140],
						"channel": channel.name,
						"content_type": "Template" if core_template else "Text",
						"template": core_template,
						"message_text": "" if core_template else f"Legacy template: {template_name}",
						"audience_source": _json_value(audience),
						"status": _campaign_status(parent.get(source.get("status_field"))),
						"send_authorized": 0,
						"prepared_at": parent.get("creation"),
						"started_at": parent.get(source.get("started_field"))
						if source.get("started_field")
						else None,
						"completed_at": parent.get(source.get("completed_field"))
						if source.get("completed_field")
						else None,
					}
				).insert(ignore_permissions=True)
				campaign_name = core_doc.name
				result["campaigns_inserted"] += 1
			_migrate_campaign_recipients(
				config,
				source,
				recipient_source,
				campaign_name,
				recipients,
				legacy_message_map,
				result,
				batch_size=batch_size,
				commit_every_batch=commit_every_batch,
			)
			from frappe_whatsapp_core.campaigns import refresh_campaign_counts

			refresh_campaign_counts(campaign_name)
	return result


def _campaign_recipient_groups(source, recipient_source, parent) -> dict:
	fields = _source_fields(
		recipient_source["doctype"],
		[
			"name",
			"parent",
			"parenttype",
			"parentfield",
			"idx",
			"creation",
			"modified",
			recipient_source.get("phone_field"),
			recipient_source.get("status_field"),
			recipient_source.get("variables_field"),
			recipient_source.get("message_field"),
			recipient_source.get("error_field"),
			recipient_source.get("account_field"),
			recipient_source.get("template_field"),
			recipient_source.get("sent_at_field"),
		],
	)
	filters = {"parent": parent.name, "parenttype": source["doctype"]}
	if recipient_source.get("parentfield"):
		filters["parentfield"] = recipient_source["parentfield"]
	recipients = frappe.get_all(
		recipient_source["doctype"],
		filters=filters,
		fields=fields,
		order_by="idx asc, name asc",
		limit_page_length=1000000,
	)
	groups = defaultdict(list)
	for row in recipients:
		account = _text(
			row.get(recipient_source.get("account_field"))
			or parent.get(source.get("account_field"))
			or recipient_source.get("default_account")
			or source.get("default_account")
		)
		template = _text(
			row.get(recipient_source.get("template_field")) or parent.get(source.get("template_field"))
		)
		groups[(account, template)].append(row)
	if not groups:
		account = _text(parent.get(source.get("account_field")) or source.get("default_account"))
		template = _text(parent.get(source.get("template_field")))
		groups[(account, template)] = []
	return groups


def _migrate_campaign_recipients(
	config,
	source,
	recipient_source,
	campaign_name,
	recipients,
	legacy_message_map,
	result,
	*,
	batch_size: int,
	commit_every_batch: bool,
) -> None:
	for index, row in enumerate(recipients, start=1):
		phone = row.get(recipient_source.get("phone_field"))
		if not _text(phone):
			result["campaign_recipients_skipped"] += 1
			continue
		identity = get_or_create_identity(phone)
		recipient_key = _legacy_key(config["source_key"], recipient_source["doctype"], row.name)
		if frappe.db.exists("WhatsApp Core Campaign Recipient", recipient_key):
			result["campaign_recipients_existing"] += 1
			continue
		variables = _json_any(
			row.get(recipient_source.get("variables_field"))
			if recipient_source.get("variables_field")
			else None,
			[],
		)
		legacy_message = (
			row.get(recipient_source.get("message_field")) if recipient_source.get("message_field") else None
		)
		message_doctype = config["message"]["doctype"]
		core_message = legacy_message_map.get((message_doctype, legacy_message)) or legacy_message_map.get(
			legacy_message
		)
		status = _recipient_status(row.get(recipient_source.get("status_field")))
		sent_at = (
			row.get(recipient_source.get("sent_at_field")) if recipient_source.get("sent_at_field") else None
		)
		frappe.get_doc(
			{
				"doctype": "WhatsApp Core Campaign Recipient",
				"recipient_key": recipient_key,
				"campaign": campaign_name,
				"identity": identity.name,
				"status": status,
				"personalization": _json_value(
					{
						"variables": variables,
						"legacy_source": config["source_key"],
						"legacy_doctype": recipient_source["doctype"],
						"legacy_recipient": row.name,
					}
				),
				"core_message": core_message,
				"attempts": 1 if status in {"Sent", "Delivered", "Read", "Failed"} else 0,
				"last_error": _text(row.get(recipient_source.get("error_field")))[:140],
				"queued_at": sent_at or row.get("creation"),
				"completed_at": sent_at if status in {"Sent", "Delivered", "Read", "Failed"} else None,
			}
		).insert(ignore_permissions=True)
		result["campaign_recipients_inserted"] += 1
		if commit_every_batch and index % batch_size == 0:
			frappe.db.commit()


def _migrate_categories(config, legacy_message_map) -> dict:
	source = config.get("category") or {}
	if not source:
		return {
			"categories_inserted": 0,
			"categories_existing": 0,
			"category_assignments_inserted": 0,
			"category_assignments_existing": 0,
			"category_assignments_skipped": 0,
		}
	rows = frappe.get_all(
		source["doctype"],
		fields=_source_fields(
			source["doctype"],
			["name", source.get("name_field"), source.get("description_field")],
		),
		order_by="name asc",
		limit_page_length=100000,
	)
	category_map = {}
	inserted = existing = 0
	for row in rows:
		category_name = _text(row.get(source.get("name_field")) or row.name)[:140]
		if frappe.db.exists("WhatsApp Core Message Category", category_name):
			existing += 1
		else:
			frappe.get_doc(
				{
					"doctype": "WhatsApp Core Message Category",
					"category_name": category_name,
					"description": _text(row.get(source.get("description_field"))),
					"source": source.get("source") or "AI",
					"enabled": 1,
				}
			).insert(ignore_permissions=True)
			inserted += 1
		category_map[row.name] = category_name
	assignment_source = source.get("assignment") or {}
	assignment_inserted = assignment_existing = assignment_skipped = 0
	context_cache = {}
	if assignment_source:
		assignments = frappe.get_all(
			assignment_source["doctype"],
			filters={"parenttype": assignment_source["message_doctype"]},
			fields=_source_fields(
				assignment_source["doctype"],
				[
					"name",
					"parent",
					"creation",
					assignment_source.get("category_field"),
					assignment_source.get("confidence_field"),
				],
			),
			limit_page_length=1000000,
		)
		for row in assignments:
			core_message = legacy_message_map.get(
				(assignment_source["message_doctype"], row.parent)
			) or legacy_message_map.get(row.parent)
			category = category_map.get(row.get(assignment_source.get("category_field")))
			if not core_message or not category:
				assignment_skipped += 1
				continue
			assignment_key = _legacy_key(config["source_key"], assignment_source["doctype"], row.name)
			if frappe.db.exists("WhatsApp Core Message Category Assignment", assignment_key):
				assignment_existing += 1
				continue
			if core_message not in context_cache:
				conversation = frappe.db.get_value("WhatsApp Core Message", core_message, "conversation")
				identity = (
					frappe.db.get_value("WhatsApp Core Conversation", conversation, "remote_identity")
					if conversation
					else None
				)
				context_cache[core_message] = (conversation, identity)
			conversation, identity = context_cache[core_message]
			if not conversation or not identity:
				assignment_skipped += 1
				continue
			frappe.get_doc(
				{
					"doctype": "WhatsApp Core Message Category Assignment",
					"assignment_key": assignment_key,
					"message": core_message,
					"conversation": conversation,
					"identity": identity,
					"category": category,
					"source": source.get("source") or "AI",
					"confidence": _percent_value(row.get(assignment_source.get("confidence_field"))),
					"assigned_at": row.get("creation") or now_datetime(),
				}
			).insert(ignore_permissions=True)
			assignment_inserted += 1
	return {
		"categories_inserted": inserted,
		"categories_existing": existing,
		"category_assignments_inserted": assignment_inserted,
		"category_assignments_existing": assignment_existing,
		"category_assignments_skipped": assignment_skipped,
	}


def _legacy_key(*parts) -> str:
	seed = ":".join(_text(part) for part in parts)
	return f"legacy.{hashlib.sha256(seed.encode()).hexdigest()}"


def _approval_status(value) -> str:
	status = _text(value).upper()
	if status == "PENDING":
		return "IN_REVIEW"
	return (
		status
		if status
		in {
			"UNKNOWN",
			"DRAFT",
			"IN_REVIEW",
			"APPROVED",
			"REJECTED",
			"PAUSED",
			"DISABLED",
		}
		else "UNKNOWN"
	)


def _campaign_status(value) -> str:
	status = _text(value).lower()
	if status == "draft":
		return "Draft"
	if status in {"queued", "sending", "processing"}:
		return "Paused"
	if status == "cancelled":
		return "Cancelled"
	return "Completed"


def _recipient_status(value) -> str:
	return {
		"pending": "Prepared",
		"prepared": "Prepared",
		"sending": "Queued",
		"queued": "Queued",
		"sent": "Sent",
		"delivered": "Delivered",
		"read": "Read",
		"failed": "Failed",
		"skipped": "Skipped",
	}.get(_text(value).lower(), "Prepared")


def _percent_value(value) -> float:
	try:
		number = float(value or 0)
	except (TypeError, ValueError):
		return 0
	return number * 100 if 0 < number <= 1 else number


def _message_conversation(source, row, channel):
	direction = _direction(row.get(source.get("direction_field")))
	phone_field = (
		source.get("inbound_phone_field") if direction == "Inbound" else source.get("outbound_phone_field")
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
		if account_name in channels:
			return account_name
		if len({channel.name for channel in channels.values()}) == 1:
			return next(iter(channels), account_name)
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


def _message_sources(config: dict) -> list[dict]:
	return [config["message"], *(config.get("additional_messages") or [])]


def _validated_config(config: dict) -> dict:
	if not isinstance(config, dict):
		frappe.throw("Legacy migration config must be an object", frappe.ValidationError)
	for key in ("source_key", "contact", "message"):
		if not config.get(key):
			frappe.throw(f"Legacy migration config requires {key}", frappe.ValidationError)
	if "channels" not in config or not isinstance(config["channels"], list):
		frappe.throw("Legacy migration config requires channels", frappe.ValidationError)
	sections = [config["contact"], *_message_sources(config)]
	for optional_name in ("template", "campaign", "category"):
		if config.get(optional_name):
			sections.append(config[optional_name])
	for source in sections:
		if not frappe.db.exists("DocType", source.get("doctype")):
			frappe.throw(
				f"Legacy DocType {source.get('doctype')} was not found",
				frappe.DoesNotExistError,
			)
	for child_source in (
		(config.get("campaign") or {}).get("recipient"),
		(config.get("category") or {}).get("assignment"),
	):
		if child_source and not frappe.db.exists("DocType", child_source.get("doctype")):
			frappe.throw(
				f"Legacy DocType {child_source.get('doctype')} was not found",
				frappe.DoesNotExistError,
			)
	return config


def _resolved_channel_sources(config: dict) -> tuple[list[dict], bool]:
	"""Return explicit legacy routes or an unambiguous Core-only fallback."""
	explicit = [
		dict(channel)
		for channel in (config.get("channels") or [])
		if str(channel.get("phone_number_id") or "").strip()
	]
	if explicit:
		return explicit, False
	core_channels = frappe.get_all(
		"WhatsApp Core Channel",
		filters={"enabled": 1},
		fields=["name", "phone_number_id", "waba_id", "display_name", "enabled"],
		limit_page_length=2,
	)
	if len(core_channels) != 1:
		return [], False
	core = core_channels[0]
	legacy_sources = config.get("channels") or [{"source_name": "default"}]
	resolved = []
	for source in legacy_sources:
		resolved.append({
			**dict(source),
			"source_name": source.get("source_name") or "default",
			"phone_number_id": core.phone_number_id,
			"waba_id": source.get("waba_id") or core.waba_id,
			"display_name": source.get("display_name") or core.display_name,
			"enabled": core.enabled,
		})
	return resolved, True


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


def _json_any(value, fallback):
	if value in (None, ""):
		return fallback
	if isinstance(value, (dict, list)):
		return value
	try:
		return json.loads(value)
	except (TypeError, ValueError):
		return fallback


def _text(value) -> str:
	return str(value or "").strip()


def _json_value(value) -> str:
	return json.dumps(
		value,
		sort_keys=True,
		separators=(",", ":"),
		ensure_ascii=False,
		default=str,
	)
