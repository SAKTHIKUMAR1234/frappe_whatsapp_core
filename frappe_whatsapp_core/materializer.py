import hashlib
import json
import re
from datetime import datetime, timezone

import frappe
from frappe.utils import convert_utc_to_system_timezone, get_datetime, now_datetime

from frappe_whatsapp_core.campaigns import refresh_campaigns_for_messages
from frappe_whatsapp_core.delivery import (
	advance_delivery_status,
	enqueue_delivery_status_handlers,
)
from frappe_whatsapp_core.identity import (
	get_or_create_identity as get_or_create_core_identity,
	link_business_scoped_user_id_change,
)
from frappe_whatsapp_core.naming import name_by_key
from frappe_whatsapp_core.party_bindings import ensure_party_bindings


def materialize_event(event, payload, channel_cache=None, projection_cache=None):
	"""Project a raw provider event into the reusable messaging kernel."""
	results = []
	projection_cache = projection_cache if projection_cache is not None else {}
	channel_cache = (
		channel_cache
		if channel_cache is not None
		else projection_cache.setdefault("channels", {})
	)
	for entry in payload.get("entry", []):
		for change in entry.get("changes", []):
			value = change.get("value") or {}
			phone_number_id = value.get("metadata", {}).get("phone_number_id")
			if phone_number_id:
				channel = channel_cache.get(str(phone_number_id))
				if channel is None:
					channel = get_or_create_channel(phone_number_id, entry.get("id"))
					channel_cache[str(phone_number_id)] = channel
				contacts = value.get("contacts") or []
				for message in value.get("messages") or []:
					results.append(materialize_inbound_message(
						event,
						channel,
						message,
						contact=_matching_contact(message, contacts, "Inbound"),
						projection_cache=projection_cache,
					))
				for message in value.get("message_echoes") or []:
					results.append(materialize_provider_message(
						event,
						channel,
						message,
						"Outbound",
						contact=_matching_contact(message, contacts, "Outbound"),
						projection_cache=projection_cache,
					))
				for status in value.get("statuses") or []:
					results.append(materialize_status(
						channel,
						status,
						event=event,
						contact=_matching_status_contact(status, contacts),
					))
				for call in value.get("calls") or []:
					results.append(materialize_call(
						event,
						channel,
						call,
						contact=_matching_contact(call, contacts, "Inbound"),
					))
				for group_event in value.get("groups") or []:
					results.append(
						materialize_group_event(
							event,
							channel,
							group_event,
							change.get("field") or "groups",
						)
					)
			results.extend(materialize_history(
				event,
				entry,
				value,
				projection_cache=projection_cache,
			))
			results.extend(materialize_state_sync(
				value,
				channel if phone_number_id else None,
			))
			results.extend(materialize_identity_updates(
				value,
				change.get("field") or "",
				channel if phone_number_id else None,
			))
	return results


def get_or_create_channel(phone_number_id, waba_id=None):
	phone_number_id = str(phone_number_id or "").strip()
	if not phone_number_id:
		frappe.throw("Phone Number ID is required", frappe.ValidationError)
	existing_name = frappe.db.get_value(
		"WhatsApp Core Channel",
		{"phone_number_id": phone_number_id},
		"name",
	)
	if existing_name:
		return frappe.get_doc("WhatsApp Core Channel", existing_name)
	channel_key = f"meta:{phone_number_id}"
	if existing_name := name_by_key("WhatsApp Core Channel", channel_key):
		return frappe.get_doc("WhatsApp Core Channel", existing_name)
	doc = frappe.get_doc({
		"doctype": "WhatsApp Core Channel",
		"channel_key": channel_key,
		"provider": "meta",
		"phone_number_id": phone_number_id,
		"waba_id": waba_id or "",
		"display_name": phone_number_id,
		"enabled": 1,
	})
	try:
		doc.insert(ignore_permissions=True)
	except (frappe.DuplicateEntryError, frappe.UniqueValidationError):
		existing_name = frappe.db.get_value(
			"WhatsApp Core Channel",
			{"phone_number_id": phone_number_id},
			"name",
		)
		if existing_name:
			return frappe.get_doc("WhatsApp Core Channel", existing_name)
		return frappe.get_doc(
			"WhatsApp Core Channel",
			name_by_key("WhatsApp Core Channel", channel_key),
		)
	return doc


def get_or_create_identity(value, *, scope=None, aliases=None, resolve=True):
	return get_or_create_core_identity(
		value,
		resolve=resolve,
		scope=scope,
		aliases=aliases,
	)


def get_or_create_conversation(channel, identity):
	existing_name = frappe.db.get_value(
		"WhatsApp Core Conversation",
		{"channel": channel.name, "remote_identity": identity.name},
		"name",
		order_by="creation asc",
	)
	if existing_name:
		return frappe.get_doc("WhatsApp Core Conversation", existing_name)
	conversation_key = hashlib.sha256(f"{channel.name}:{identity.name}:active".encode()).hexdigest()
	if existing_name := name_by_key("WhatsApp Core Conversation", conversation_key):
		return frappe.get_doc("WhatsApp Core Conversation", existing_name)
	doc = frappe.get_doc({
		"doctype": "WhatsApp Core Conversation",
		"conversation_key": conversation_key,
		"channel": channel.name,
		"remote_identity": identity.name,
		"status": "Open",
		"last_message_at": now_datetime(),
	})
	try:
		doc.insert(ignore_permissions=True)
	except (frappe.DuplicateEntryError, frappe.UniqueValidationError):
		return frappe.get_doc(
			"WhatsApp Core Conversation",
			name_by_key("WhatsApp Core Conversation", conversation_key),
		)
	return doc


def materialize_inbound_message(
	event,
	channel,
	provider_message,
	contact=None,
	projection_cache=None,
):
	return materialize_provider_message(
		event,
		channel,
		provider_message,
		"Inbound",
		contact=contact,
		projection_cache=projection_cache,
	)


def materialize_provider_message(
	event,
	channel,
	provider_message,
	direction="Inbound",
	*,
	contact=None,
	projection_cache=None,
):
	"""Project inbound, history, or Business App echo messages into one model."""
	message_type = str(provider_message.get("type") or "unknown").lower()
	if message_type in {"edit", "revoke"}:
		return materialize_message_mutation(event, channel, provider_message, message_type)
	provider_id = provider_message.get("id")
	if not provider_id:
		return {"kind": "message", "status": "ignored", "reason": "missing_provider_id"}
	existing_name = frappe.db.get_value(
		"WhatsApp Core Message",
		{"provider_message_id": provider_id},
		"name",
	)
	if existing_name:
		return {"kind": "message", "status": "duplicate", "name": existing_name}
	message_key = hashlib.sha256(f"{channel.name}:{provider_id}".encode()).hexdigest()
	if existing_name := name_by_key("WhatsApp Core Message", message_key):
		return {"kind": "message", "status": "duplicate", "name": existing_name}

	group_id = provider_message.get("group_id")
	remote_number = (
		provider_message.get("from")
		if direction == "Inbound"
		else provider_message.get("to") or provider_message.get("recipient_id")
	)
	remote_user_id = (
		provider_message.get("from_user_id")
		if direction == "Inbound"
		else provider_message.get("to_user_id") or provider_message.get("recipient_user_id")
	)
	remote_parent_user_id = (
		provider_message.get("from_parent_user_id")
		if direction == "Inbound"
		else provider_message.get("to_parent_user_id") or provider_message.get("recipient_parent_user_id")
	)
	aliases = _identity_aliases(
		contact,
		phone=remote_number,
		user_id=remote_user_id,
		parent_user_id=remote_parent_user_id,
	)
	identity = _system_identity_change(channel, provider_message, aliases)
	if not group_id and not identity and not any(
		str(value or "").strip()
		for value in (remote_user_id, remote_parent_user_id, remote_number)
	):
		return {"kind": "message", "status": "ignored", "reason": "missing_remote_identity"}
	if group_id:
		identity = get_or_create_group_identity(group_id)
		if remote_user_id or remote_number:
			participant = _cached_identity(
				projection_cache,
				remote_user_id or remote_parent_user_id or remote_number,
				scope=channel.name if remote_user_id or remote_parent_user_id else None,
				aliases=aliases,
			)
			_cached_party_bindings(
				projection_cache,
				participant.name,
				{"channel": channel.name, "provider_message": provider_message},
			)
	elif not identity:
		identity = _cached_identity(
			projection_cache,
			remote_user_id or remote_parent_user_id or remote_number,
			scope=channel.name if remote_user_id or remote_parent_user_id else None,
			aliases=aliases,
		)
	if not group_id:
		_cached_party_bindings(
			projection_cache,
			identity.name,
			{"channel": channel.name, "provider_message": provider_message},
		)
	conversation = _cached_conversation(projection_cache, channel, identity)
	content = provider_message.get(message_type) or {}
	body = inbound_message_body(message_type, content)
	timestamp = provider_message.get("timestamp")
	provider_timestamp = parse_provider_timestamp(timestamp)
	doc = frappe.get_doc({
		"doctype": "WhatsApp Core Message",
		"message_key": message_key,
		"conversation": conversation.name,
		"relay_event": event.name,
		"channel": channel.name,
		"provider_message_id": provider_id,
		"direction": direction,
		"message_type": message_type,
		"body": body or "",
		"content": json.dumps(provider_message, separators=(",", ":"), ensure_ascii=False),
		"provider_timestamp": provider_timestamp,
		"delivery_status": "Received" if direction == "Inbound" else "Sent",
	})
	try:
		doc.insert(ignore_permissions=True)
	except (frappe.DuplicateEntryError, frappe.UniqueValidationError):
		return {
			"kind": "message",
			"status": "duplicate",
			"name": name_by_key("WhatsApp Core Message", message_key),
		}
	if direction == "Inbound":
		# A customer reply starts (or resumes) an actionable conversation.  Keeping
		# a previously resolved row resolved makes the new message disappear from
		# the default Shared Inbox even though the webhook was processed correctly.
		conversation.status = "Open"
		conversation.last_inbound_at = provider_timestamp
	conversation.last_message_at = provider_timestamp
	conversation.save(ignore_permissions=True)
	return {"kind": "message", "status": "created", "name": doc.name}


def _cached_identity(projection_cache, value, *, scope=None, aliases=None):
	if projection_cache is None:
		return get_or_create_identity(value, scope=scope, aliases=aliases)
	key = (
		str(scope or ""),
		str(value or "").strip(),
		json.dumps(aliases or {}, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
	)
	identities = projection_cache.setdefault("identities", {})
	if key not in identities:
		identities[key] = get_or_create_identity(value, scope=scope, aliases=aliases)
	return identities[key]


def _cached_party_bindings(projection_cache, identity, context):
	if projection_cache is None:
		return ensure_party_bindings(identity, context)
	bindings = projection_cache.setdefault("party_bindings", {})
	key = (str(identity), str((context or {}).get("channel") or ""))
	if key not in bindings:
		bindings[key] = ensure_party_bindings(identity, context)
	return bindings[key]


def _cached_conversation(projection_cache, channel, identity):
	if projection_cache is None:
		return get_or_create_conversation(channel, identity)
	conversations = projection_cache.setdefault("conversations", {})
	key = (channel.name, identity.name)
	if key not in conversations:
		conversations[key] = get_or_create_conversation(channel, identity)
	return conversations[key]


def _matching_contact(provider_row, contacts, direction="Inbound"):
	if not isinstance(contacts, list):
		return None
	keys = (
		("from_user_id", "from_parent_user_id", "from")
		if direction == "Inbound"
		else (
			"to_user_id", "recipient_user_id", "to_parent_user_id",
			"recipient_parent_user_id", "to", "recipient_id",
		)
	)
	identifiers = {
		str(provider_row.get(key) or "").strip()
		for key in keys
		if str(provider_row.get(key) or "").strip()
	}
	for contact in contacts:
		if not isinstance(contact, dict):
			continue
		contact_ids = {
			str(contact.get(key) or "").strip()
			for key in ("user_id", "parent_user_id", "wa_id")
			if str(contact.get(key) or "").strip()
		}
		if identifiers.intersection(contact_ids):
			return contact
	return None


def _matching_status_contact(provider_status, contacts):
	if not isinstance(contacts, list):
		return None
	identifiers = {
		str(provider_status.get(key) or "").strip()
		for key in (
			"recipient_id", "recipient_user_id", "recipient_parent_user_id",
			"parent_recipient_user_id", "recipient_participant_id",
			"participant_recipient_id", "recipient_participant_user_id",
			"recipient_participant_parent_user_id",
		)
		if str(provider_status.get(key) or "").strip()
	}
	for contact in contacts:
		if not isinstance(contact, dict):
			continue
		contact_ids = {
			str(contact.get(key) or "").strip()
			for key in ("user_id", "parent_user_id", "wa_id")
			if str(contact.get(key) or "").strip()
		}
		if identifiers.intersection(contact_ids):
			return contact
	return None


def _identity_aliases(contact=None, *, phone=None, user_id=None, parent_user_id=None):
	contact = contact if isinstance(contact, dict) else {}
	profile = contact.get("profile") if isinstance(contact.get("profile"), dict) else {}
	return {
		"phone": phone or contact.get("wa_id"),
		"user_id": user_id or contact.get("user_id"),
		"parent_user_id": parent_user_id or contact.get("parent_user_id"),
		"profile": profile,
		"username": profile.get("username") or contact.get("username"),
		"profile_name": profile.get("name"),
	}


def _system_identity_change(channel, provider_message, aliases):
	if str(provider_message.get("type") or "").lower() != "system":
		return None
	system = provider_message.get("system") or {}
	if not isinstance(system, dict) or str(system.get("type") or "").lower() not in {
		"user_changed_user_id", "user_changed_number",
	}:
		return None
	body_match = re.search(
		r"(?i)changed\s+from\s+([A-Za-z]{2}\.(?:[A-Za-z0-9]{1,128}|ENT\.[A-Za-z0-9]{1,128}))\s+to\s+([A-Za-z]{2}\.(?:[A-Za-z0-9]{1,128}|ENT\.[A-Za-z0-9]{1,128}))",
		str(system.get("body") or ""),
	)
	old_user_id = (
		system.get("old_user_id")
		or system.get("previous_user_id")
		or (body_match.group(1) if body_match else None)
		or provider_message.get("from_user_id")
	)
	new_user_id = (
		system.get("new_user_id")
		or system.get("user_id")
		or (body_match.group(2) if body_match else None)
	)
	if not old_user_id or not new_user_id:
		return None
	return link_business_scoped_user_id_change(
		old_user_id,
		new_user_id,
		scope=channel.name,
		aliases={
			**aliases,
			"user_id": new_user_id,
			"parent_user_id": system.get("parent_user_id") or aliases.get("parent_user_id"),
			"previous_parent_user_id": system.get("previous_parent_user_id"),
			"phone": system.get("wa_id") or aliases.get("phone"),
		},
	)


def materialize_message_mutation(event, channel, provider_message, mutation_type):
	"""Apply WhatsApp Business App edit/revoke echoes to their original message."""
	mutation = provider_message.get(mutation_type) or {}
	if not isinstance(mutation, dict):
		mutation = {}
	nested_message = mutation.get("message") or provider_message.get("message") or {}
	if not isinstance(nested_message, dict):
		nested_message = {}
	context = provider_message.get("context") or {}
	target_id = str(
		mutation.get("message_id")
		or mutation.get("original_message_id")
		or nested_message.get("id")
		or context.get("id")
		or provider_message.get("id")
		or ""
	).strip()
	if not target_id:
		return {"kind": mutation_type, "status": "ignored", "reason": "missing_provider_id"}
	message_name = frappe.db.get_value(
		"WhatsApp Core Message",
		{"channel": channel.name, "provider_message_id": target_id},
		"name",
	)
	if not message_name:
		return {"kind": mutation_type, "status": "orphan", "provider_message_id": target_id}
	doc = frappe.get_doc("WhatsApp Core Message", message_name)
	try:
		content = json.loads(doc.content or "{}") if isinstance(doc.content, str) else (doc.content or {})
	except (TypeError, ValueError):
		content = {}
	if not isinstance(content, dict):
		content = {}
	content.setdefault("mutations", []).append(provider_message)
	if mutation_type == "revoke":
		doc.delivery_status = "Deleted"
		doc.body = "[Message deleted]"
	else:
		replacement = nested_message or mutation
		replacement_type = str(replacement.get("type") or doc.message_type or "text").lower()
		replacement_content = replacement.get(replacement_type) or replacement.get("text") or replacement
		doc.message_type = replacement_type
		doc.body = inbound_message_body(replacement_type, replacement_content)
	doc.content = json.dumps(content, separators=(",", ":"), ensure_ascii=False)
	doc.relay_event = event.name
	doc.save(ignore_permissions=True)
	return {"kind": mutation_type, "status": "updated", "name": doc.name}


def materialize_history(event, entry, value, projection_cache=None):
	"""Import coexistence history batches while preserving message directions."""
	results = []
	history_batches = value.get("history") or []
	if isinstance(history_batches, dict):
		history_batches = [history_batches]
	for batch in history_batches:
		if not isinstance(batch, dict):
			continue
		metadata = batch.get("metadata") or value.get("metadata") or {}
		phone_number_id = metadata.get("phone_number_id")
		if not phone_number_id:
			continue
		channel = get_or_create_channel(phone_number_id, entry.get("id"))
		for thread in batch.get("threads") or []:
			if not isinstance(thread, dict):
				continue
			thread_id = str(thread.get("id") or thread.get("wa_id") or thread.get("phone_number") or "")
			for provider_message in thread.get("messages") or []:
				if not isinstance(provider_message, dict):
					continue
				message = dict(provider_message)
				direction = str(message.pop("direction", "") or "").title()
				if direction not in {"Inbound", "Outbound"}:
					direction = "Inbound" if message.get("from") == thread_id else "Outbound"
				if direction == "Inbound" and not message.get("from"):
					message["from"] = thread_id
				if direction == "Outbound" and not message.get("to"):
					message["to"] = thread_id
				results.append(materialize_provider_message(
					event,
					channel,
					message,
					direction,
					projection_cache=projection_cache,
				))
	return results


def materialize_state_sync(value, channel=None):
	"""Resolve coexistence contacts; raw state remains durable in the Core Event."""
	results = []
	states = value.get("state_sync") or []
	if isinstance(states, dict):
		states = [states]
	for state in states:
		if not isinstance(state, dict):
			continue
		contacts = state.get("contacts") or []
		for contact in contacts:
			if not isinstance(contact, dict):
				continue
			contact_value = (
				contact.get("user_id")
				or contact.get("parent_user_id")
				or contact.get("wa_id")
				or contact.get("phone_number")
				or contact.get("phone")
			)
			if contact_value:
				identity = get_or_create_identity(
					contact_value,
					scope=(
						channel.name
						if channel and (contact.get("user_id") or contact.get("parent_user_id"))
						else None
					),
					aliases=_identity_aliases(
						contact,
						phone=contact.get("wa_id") or contact.get("phone_number") or contact.get("phone"),
					),
				)
				results.append({"kind": "state_sync", "status": "resolved", "name": identity.name})
		if not contacts:
			results.append({"kind": "state_sync", "status": "recorded"})
	return results


def materialize_identity_updates(value, webhook_field, channel):
	"""Resolve identity-bearing management webhooks without inventing phone IDs."""
	if not channel:
		return []
	if webhook_field == "user_id_update":
		return _materialize_user_id_update(value, channel)
	rows = []
	if webhook_field == "user_preferences":
		rows = value.get("user_preferences") or []
	elif webhook_field == "group_participants_update":
		rows = value.get("group_participants_update") or []
	if isinstance(rows, dict):
		rows = [rows]
	results = []
	for row in rows:
		if not isinstance(row, dict):
			continue
		user_id = row.get("user_id") or row.get("parent_user_id")
		phone = row.get("wa_id") or row.get("input")
		if not user_id and not phone:
			results.append({
				"kind": webhook_field,
				"status": "ignored",
				"reason": "missing_remote_identity",
			})
			continue
		contact = _matching_identity_update_contact(user_id, phone, value.get("contacts") or [])
		identity = get_or_create_identity(
			user_id or phone,
			scope=channel.name if user_id else None,
			aliases=_identity_aliases(
				{**contact, **row},
				phone=phone,
				user_id=row.get("user_id"),
				parent_user_id=row.get("parent_user_id"),
			),
		)
		if webhook_field == "user_preferences":
			_record_user_preference(identity, row)
		results.append({"kind": webhook_field, "status": "resolved", "name": identity.name})
	return results


def _record_user_preference(identity, row):
	category = str(row.get("category") or "").strip().upper()
	preference = str(row.get("value") or row.get("preference") or "").strip().upper()
	if not category or preference not in {"STOP", "RESUME"}:
		return
	attributes = identity.attributes or {}
	if isinstance(attributes, str):
		attributes = frappe.parse_json(attributes)
	if not isinstance(attributes, dict):
		attributes = {}
	preferences = dict(attributes.get("user_preferences") or {})
	existing = preferences.get(category) or {}
	if not _preference_update_wins(existing, preference, row.get("timestamp")):
		return
	preferences[category] = {
		"value": preference,
		"timestamp": str(row.get("timestamp") or ""),
	}
	attributes["user_preferences"] = preferences
	identity.attributes = attributes
	identity.save(ignore_permissions=True)


def _preference_update_wins(existing, incoming_value, incoming_timestamp):
	if not existing:
		return True
	try:
		existing_timestamp = float(existing.get("timestamp"))
		new_timestamp = float(incoming_timestamp)
	except (TypeError, ValueError):
		return incoming_value == "STOP" and str(existing.get("value") or "").upper() != "STOP"
	if new_timestamp != existing_timestamp:
		return new_timestamp > existing_timestamp
	return incoming_value == "STOP" and str(existing.get("value") or "").upper() != "STOP"


def _materialize_user_id_update(value, channel):
	rows = value.get("user_id_update") or []
	if isinstance(rows, dict):
		rows = [rows]
	contacts = value.get("contacts") or []
	results = []
	for row in rows:
		if not isinstance(row, dict):
			continue
		user_ids = row.get("user_id") or {}
		parent_ids = row.get("parent_user_id") or {}
		if not isinstance(user_ids, dict) or not isinstance(parent_ids, dict):
			results.append({
				"kind": "user_id_update", "status": "ignored", "reason": "invalid_identity_update",
			})
			continue
		old_user_id = user_ids.get("previous")
		new_user_id = user_ids.get("current")
		if not old_user_id or not new_user_id:
			results.append({
				"kind": "user_id_update", "status": "ignored", "reason": "missing_remote_identity",
			})
			continue
		contact = _matching_identity_update_contact(new_user_id, row.get("wa_id"), contacts)
		identity = link_business_scoped_user_id_change(
			old_user_id,
			new_user_id,
			scope=channel.name,
			aliases=_identity_aliases(
				contact,
				phone=row.get("wa_id") or contact.get("wa_id"),
				user_id=new_user_id,
				parent_user_id=parent_ids.get("current") or contact.get("parent_user_id"),
			) | {"previous_parent_user_id": parent_ids.get("previous")},
		)
		results.append({"kind": "user_id_update", "status": "resolved", "name": identity.name})
	return results


def _matching_identity_update_contact(user_id, wa_id, contacts):
	for contact in contacts:
		if not isinstance(contact, dict):
			continue
		if user_id and user_id in {contact.get("user_id"), contact.get("parent_user_id")}:
			return contact
		if wa_id and wa_id == contact.get("wa_id"):
			return contact
	return {}


def get_or_create_group_identity(group_id):
	"""Keep a group thread separate from each participant's direct conversation."""
	group_id = str(group_id or "").strip()
	if not group_id:
		frappe.throw("A group ID is required")
	identity_key = hashlib.sha256(f"whatsapp-group:{group_id}".encode()).hexdigest()
	if existing_name := name_by_key("WhatsApp Core Identity", identity_key):
		return frappe.get_doc("WhatsApp Core Identity", existing_name)
	doc = frappe.get_doc({
		"doctype": "WhatsApp Core Identity", "identity_key": identity_key,
		"identity_type": "External", "normalized_value": f"group:{group_id}",
		"display_value": group_id, "provider": "meta", "status": "Active",
		"resolution_status": "Unresolved", "attributes": {"group_id": group_id},
	})
	try:
		doc.insert(ignore_permissions=True)
	except (frappe.DuplicateEntryError, frappe.UniqueValidationError):
		return frappe.get_doc(
			"WhatsApp Core Identity",
			name_by_key("WhatsApp Core Identity", identity_key),
		)
	return doc


def sync_group_identity(group):
	"""Keep the shared-inbox thread readable as Meta group details change."""
	identity = get_or_create_group_identity(group.group_id)
	attributes = identity.attributes or {}
	if isinstance(attributes, str):
		attributes = frappe.parse_json(attributes)
	if not isinstance(attributes, dict):
		attributes = {}
	attributes.update({
		"group_id": group.group_id,
		"subject": group.subject or "",
		"description": group.description or "",
		"status": group.status or "",
	})
	display_value = str(group.subject or group.group_id).strip()[:140]
	if identity.display_value != display_value or identity.attributes != attributes:
		identity.display_value = display_value
		identity.attributes = attributes
		identity.save(ignore_permissions=True)
	return identity


def materialize_call(event, channel, provider_call, contact=None):
	call_id = str(provider_call.get("id") or provider_call.get("call_id") or "").strip()
	if not call_id:
		return {"kind": "call", "status": "ignored", "reason": "missing_call_id"}
	existing = name_by_key("WhatsApp Core Call", call_id)
	status = str(provider_call.get("event") or provider_call.get("status") or "received")
	values = {
		"doctype": "WhatsApp Core Call", "call_id": call_id, "relay_event": event.name,
		"channel": channel.name,
		"status": status, "last_event": provider_call,
	}
	remote_user_id = provider_call.get("from_user_id") or provider_call.get("to_user_id")
	remote_parent_user_id = provider_call.get("from_parent_user_id") or provider_call.get("to_parent_user_id")
	remote_number = provider_call.get("from") or provider_call.get("to") or provider_call.get("recipient")
	if remote_user_id or remote_parent_user_id or remote_number:
		get_or_create_identity(
			remote_user_id or remote_parent_user_id or remote_number,
			scope=channel.name if remote_user_id or remote_parent_user_id else None,
			aliases=_identity_aliases(
				contact,
				phone=remote_number,
				user_id=remote_user_id,
				parent_user_id=remote_parent_user_id,
			),
		)
	direction = provider_call.get("direction")
	if direction or not existing:
		direction = str(
			direction
			or ("Outbound" if provider_call.get("to") or provider_call.get("recipient") else "Inbound")
		).title()
		values["direction"] = direction if direction in {"Inbound", "Outbound"} else "Inbound"
	for fieldname, value in {
		"remote_number": remote_number,
		"remote_user_id": remote_user_id,
		"remote_parent_user_id": remote_parent_user_id,
		"remote_username": provider_call.get("from_username") or provider_call.get("to_username"),
		"callback_data": provider_call.get("biz_opaque_callback_data"),
		"cta_payload": provider_call.get("cta_payload"),
		"deeplink_payload": provider_call.get("deeplink_payload"),
	}.items():
		if value not in (None, ""):
			values[fieldname] = value
	if provider_call.get("session"):
		values["session"] = provider_call["session"]
	recording = (provider_call.get("call_recording") or {}).get("audio") or {}
	transcript = (provider_call.get("call_transcript") or {}).get("document") or {}
	if recording:
		values.update({
			"recording_media_id": recording.get("id") or "",
			"recording_url": recording.get("url") or "",
			"recording_mime_type": recording.get("mime_type") or "",
			"recording_sha256": recording.get("sha256") or "",
		})
	if transcript:
		values.update({
			"transcript_media_id": transcript.get("id") or "",
			"transcript_url": transcript.get("url") or "",
			"transcript_mime_type": transcript.get("mime_type") or "",
			"transcript_sha256": transcript.get("sha256") or "",
		})
	if status in {"connect", "connected", "ringing"}:
		values["started_at"] = parse_provider_timestamp(provider_call.get("timestamp"))
	if status in {"terminate", "terminated", "rejected", "failed"}:
		values["ended_at"] = parse_provider_timestamp(provider_call.get("timestamp"))
	if existing:
		doc = frappe.get_doc("WhatsApp Core Call", existing)
		doc.update(values)
		doc.save(ignore_permissions=True)
		return {"kind": "call", "status": "updated", "name": doc.name}
	doc = frappe.get_doc(values).insert(ignore_permissions=True)
	return {"kind": "call", "status": "created", "name": doc.name}


def materialize_group_event(event, channel, provider_group, webhook_field="groups"):
	"""Project Meta group lifecycle, settings, status and membership webhooks."""
	group_id = str(provider_group.get("group_id") or "").strip()
	if not group_id:
		return {"kind": "group", "status": "ignored", "reason": "missing_group_id"}
	event_type = str(provider_group.get("type") or webhook_field or "group_update")
	values = {
		"doctype": "WhatsApp Core Group",
		"group_id": group_id,
		"relay_event": event.name,
		"channel": channel.name,
		"last_event_type": event_type,
		"last_event": provider_group,
		"last_synced": now_datetime(),
	}
	existing_group = name_by_key("WhatsApp Core Group", group_id)
	if not existing_group:
		values["status"] = "Active"
	if event_type == "group_create":
		values.update({
			"subject": provider_group.get("subject") or "",
			"description": provider_group.get("description") or "",
			"invite_link": provider_group.get("invite_link") or "",
			"join_approval_mode": provider_group.get("join_approval_mode") or "",
			"created_at": parse_provider_timestamp(provider_group.get("timestamp")),
			"status": "Failed" if provider_group.get("errors") else "Active",
		})
	elif event_type == "group_delete":
		values["status"] = "Failed" if provider_group.get("errors") else "Deleted"
	elif event_type == "group_suspend":
		values["status"] = "Suspended"
	elif event_type == "group_suspend_cleared":
		values["status"] = "Active"
	elif event_type == "group_settings_update":
		subject = provider_group.get("group_subject") or {}
		description = provider_group.get("group_description") or {}
		if subject.get("update_successful") is not False and subject.get("text") is not None:
			values["subject"] = subject["text"]
		if description.get("update_successful") is not False and description.get("text") is not None:
			values["description"] = description["text"]

	if existing_group:
		group = frappe.get_doc("WhatsApp Core Group", existing_group)
		group.update(values)
		group.save(ignore_permissions=True)
		projection_status = "updated"
	else:
		group = frappe.get_doc(values).insert(ignore_permissions=True)
		projection_status = "created"
	sync_group_identity(group)

	member_results = _materialize_group_members(event, group, provider_group)
	if member_results:
		group.participant_count = frappe.db.count(
			"WhatsApp Core Group Member",
			{"group": group.name, "status": "Active"},
		)
		group.save(ignore_permissions=True)
	return {
		"kind": "group",
		"status": projection_status,
		"name": group.name,
		"members": member_results,
	}


def _materialize_group_members(event, group, provider_group):
	results = []
	event_type = str(provider_group.get("type") or "")
	if event_type in {"group_join_request_created", "group_join_request_revoked"}:
		participant = (
			provider_group.get("user_id")
			or provider_group.get("parent_user_id")
			or provider_group.get("wa_id")
		)
		if participant:
			results.append(_upsert_group_member(
				event,
				group,
				participant,
				"Pending" if event_type.endswith("created") else "Revoked",
				provider_group,
				provider_group,
			))
	for item in provider_group.get("added_participants") or []:
		participant = item.get("user_id") or item.get("parent_user_id") or item.get("wa_id") or item.get("input")
		if participant:
			results.append(_upsert_group_member(event, group, participant, "Active", provider_group, item))
	for item in provider_group.get("removed_participants") or []:
		participant = item.get("user_id") or item.get("parent_user_id") or item.get("wa_id") or item.get("input")
		if participant:
			results.append(_upsert_group_member(event, group, participant, "Removed", provider_group, item))
	for item in provider_group.get("failed_participants") or []:
		participant = item.get("user_id") or item.get("parent_user_id") or item.get("wa_id") or item.get("input")
		if participant:
			results.append(_upsert_group_member(event, group, participant, "Failed", provider_group, item))
	return results


def _upsert_group_member(event, group, participant, status, provider_group, participant_data=None):
	participant = str(participant).strip()
	participant_data = participant_data if isinstance(participant_data, dict) else {}
	user_id = participant_data.get("user_id") or participant_data.get("parent_user_id")
	if user_id or participant_data.get("wa_id") or participant_data.get("input"):
		identity = get_or_create_identity(
			user_id or participant_data.get("wa_id") or participant_data.get("input"),
			scope=group.channel if user_id else None,
			aliases=_identity_aliases(
				participant_data,
				phone=participant_data.get("wa_id") or participant_data.get("input"),
				user_id=participant_data.get("user_id"),
				parent_user_id=participant_data.get("parent_user_id"),
			),
		)
		participant = str(identity.normalized_value or participant).strip()
	member_key = hashlib.sha256(f"{group.name}:{participant}".encode()).hexdigest()
	values = {
		"doctype": "WhatsApp Core Group Member",
		"member_key": member_key,
		"relay_event": event.name,
		"group": group.name,
		"participant_id": participant,
		"status": status,
		"join_request_id": provider_group.get("join_request_id") or "",
		"reason": provider_group.get("reason") or "",
		"last_event": provider_group,
		"last_synced": now_datetime(),
	}
	existing_name = frappe.db.get_value(
		"WhatsApp Core Group Member",
		{"group": group.name, "participant_id": participant},
		"name",
	) or name_by_key("WhatsApp Core Group Member", member_key)
	if existing_name:
		doc = frappe.get_doc("WhatsApp Core Group Member", existing_name)
		doc.update(values)
		doc.save(ignore_permissions=True)
		return {"status": "updated", "name": doc.name}
	doc = frappe.get_doc(values).insert(ignore_permissions=True)
	return {"status": "created", "name": doc.name}


def inbound_message_body(message_type: str, content) -> str:
	"""Create a searchable/operator-friendly summary without losing raw Meta data."""
	if message_type == "contacts" and isinstance(content, list):
		names = [((item.get("name") or {}).get("formatted_name")) for item in content if isinstance(item, dict)]
		return "Contacts: " + ", ".join(name for name in names if name)
	if not isinstance(content, dict):
		return ""
	if message_type == "text":
		return str(content.get("body") or "")
	if message_type in {"image", "video", "document", "audio"}:
		return str(content.get("caption") or f"[{message_type.title()}]")
	if message_type == "sticker":
		return "[Sticker]"
	if message_type == "reaction":
		return str(content.get("emoji") or "[Reaction removed]")
	if message_type == "button":
		return str(content.get("text") or content.get("payload") or "[Button reply]")
	if message_type == "interactive":
		reply = content.get("button_reply") or content.get("list_reply") or {}
		if reply:
			return str(reply.get("title") or reply.get("id") or "[Interactive reply]")
		flow_reply = content.get("nfm_reply") or {}
		if flow_reply:
			response = flow_reply.get("response_json")
			try:
				response = json.loads(response) if isinstance(response, str) else response
			except (TypeError, ValueError):
				pass
			return _flow_response_summary(response)
	if message_type == "location":
		return str(content.get("name") or content.get("address") or f"Location: {content.get('latitude')}, {content.get('longitude')}")
	if message_type == "system":
		system_type = str(content.get("type") or "").replace("_", " ").strip()
		return system_type.title() if system_type else "[System update]"
	return str(content.get("body") or f"[{message_type.replace('_', ' ').title()}]")


def _flow_response_summary(response) -> str:
	"""Keep inbox previews readable; the complete response stays in message content/ledger."""
	if not isinstance(response, dict):
		return "Flow response received"
	values = []
	for key, value in response.items():
		if key in {"flow_token", "screen", "_core_action"} or key.startswith("__"):
			continue
		if isinstance(value, (dict, list)):
			continue
		label = key.replace("_", " ").replace("-", " ").strip().title()
		if value not in (None, ""):
			values.append(f"{label}: {value}")
		if len(values) == 2:
			break
	return "Flow submitted" + (f" · {' · '.join(values)}" if values else "")


def materialize_status(channel, provider_status, event=None, contact=None):
	provider_id = provider_status.get("id")
	if not provider_id:
		return {"kind": "status", "status": "ignored", "reason": "missing_provider_id"}
	message_name = frappe.db.get_value(
		"WhatsApp Core Message",
		{"channel": channel.name, "provider_message_id": provider_id},
		"name",
	)
	participant_id = (
		provider_status.get("recipient_participant_user_id")
		or provider_status.get("recipient_participant_parent_user_id")
		or provider_status.get("recipient_participant_id")
		or provider_status.get("participant_recipient_id")
	)
	if provider_status.get("recipient_type") == "group" and participant_id:
		_materialize_status_identity(channel, provider_status, contact, group=True)
		return materialize_group_receipt(event, channel, provider_status, message_name)
	if not message_name:
		return {"kind": "status", "status": "orphan", "provider_message_id": provider_id}
	_materialize_status_identity(channel, provider_status, contact, message_name=message_name)
	status = str(provider_status.get("status") or "").strip().title()
	allowed = {"Queued", "Sent", "Delivered", "Read", "Failed", "Deleted"}
	if status not in allowed:
		return {
			"kind": "status",
			"status": "ignored",
			"reason": "unknown_provider_status",
			"provider_message_id": provider_id,
			"provider_status": status,
		}
	incoming = status
	current = frappe.db.get_value(
		"WhatsApp Core Message",
		message_name,
		"delivery_status",
	)
	next_status = advance_delivery_status(current, incoming)
	updates = {"delivery_status": next_status}
	provider_template_id = str(provider_status.get("template_id") or "").strip()
	if provider_template_id:
		updates["provider_template_id"] = provider_template_id[:140]
	frappe.db.set_value("WhatsApp Core Message", message_name, updates)
	if next_status != current:
		enqueue_delivery_status_handlers({
			"message_name": message_name,
			"delivery_status": next_status,
		})
	if frappe.flags.whatsapp_core_batch_processing:
		pending = getattr(
			frappe.flags,
			"whatsapp_core_campaign_message_names",
			None,
		)
		if pending is None:
			pending = set()
			frappe.flags.whatsapp_core_campaign_message_names = pending
		pending.add(message_name)
	else:
		refresh_campaigns_for_messages([message_name])
	return {"kind": "status", "status": "updated", "name": message_name}


def _materialize_status_identity(channel, provider_status, contact, *, message_name=None, group=False):
	user_id = (
		provider_status.get("recipient_participant_user_id")
		if group
		else provider_status.get("recipient_user_id")
	) or ""
	parent_user_id = (
		provider_status.get("recipient_participant_parent_user_id")
		if group
		else provider_status.get("recipient_parent_user_id")
	) or ("" if group else provider_status.get("parent_recipient_user_id"))
	phone = (
		(
			provider_status.get("recipient_participant_id")
			or provider_status.get("participant_recipient_id")
		)
		if group
		else provider_status.get("recipient_id")
	) or ""
	if contact:
		user_id = user_id or contact.get("user_id") or ""
		parent_user_id = parent_user_id or contact.get("parent_user_id") or ""
		phone = phone or contact.get("wa_id") or ""
	if not user_id and not parent_user_id:
		return None
	if message_name and not phone:
		conversation = frappe.db.get_value(
			"WhatsApp Core Message", message_name, "conversation"
		)
		identity_name = frappe.db.get_value(
			"WhatsApp Core Conversation", conversation, "remote_identity"
		)
		identity = frappe.get_doc("WhatsApp Core Identity", identity_name)
		if getattr(identity, "identifier_type", None) == "Phone":
			phone = identity.normalized_value
	resolved = get_or_create_identity(
		user_id or parent_user_id,
		scope=channel.name,
		aliases=_identity_aliases(
			contact,
			phone=phone,
			user_id=user_id,
			parent_user_id=parent_user_id,
		),
	)
	if message_name:
		conversation = frappe.db.get_value(
			"WhatsApp Core Message", message_name, "conversation"
		)
		remote_identity = frappe.db.get_value(
			"WhatsApp Core Conversation", conversation, "remote_identity"
		)
		if remote_identity != resolved.name:
			frappe.throw(
				"Status recipient does not match the outbound message conversation",
				frappe.ValidationError,
			)
	return resolved


def materialize_group_receipt(event, channel, provider_status, message_name=None):
	group_id = str(provider_status.get("recipient_id") or "").strip()
	participant = str(
		provider_status.get("recipient_participant_user_id")
		or provider_status.get("recipient_participant_parent_user_id")
		or provider_status.get("recipient_participant_id")
		or provider_status.get("participant_recipient_id")
		or ""
	).strip()
	if not group_id or not participant:
		return {"kind": "group_receipt", "status": "ignored", "reason": "missing_group_or_participant"}
	existing_group = name_by_key("WhatsApp Core Group", group_id)
	if not existing_group:
		group = frappe.get_doc({
			"doctype": "WhatsApp Core Group",
			"group_id": group_id,
			"relay_event": event.name if event else None,
			"channel": channel.name,
			"status": "Active",
			"last_event_type": "message_status",
			"last_event": provider_status,
			"last_synced": now_datetime(),
		}).insert(ignore_permissions=True)
	else:
		group = frappe.get_doc("WhatsApp Core Group", existing_group)
	receipt_key = hashlib.sha256(
		f"{provider_status.get('id')}:{group_id}:{participant}".encode()
	).hexdigest()
	values = {
		"doctype": "WhatsApp Core Group Receipt",
		"receipt_key": receipt_key,
		"relay_event": event.name if event else None,
		"message": message_name,
		"group": group.name,
		"participant_id": participant,
		"status": str(provider_status.get("status") or "sent").title(),
		"provider_timestamp": parse_provider_timestamp(provider_status.get("timestamp")),
		"error": json.dumps(provider_status.get("errors") or [], separators=(",", ":")),
		"last_event": provider_status,
	}
	if existing_name := name_by_key("WhatsApp Core Group Receipt", receipt_key):
		doc = frappe.get_doc("WhatsApp Core Group Receipt", existing_name)
		doc.update(values)
		doc.save(ignore_permissions=True)
		status = "updated"
	else:
		doc = frappe.get_doc(values).insert(ignore_permissions=True)
		status = "created"
	return {"kind": "group_receipt", "status": status, "name": doc.name}


def normalize_phone(value, *, assume_local: bool = False, country_code: str = "91"):
	from frappe_whatsapp_core.identity import normalize_phone as normalize_identity_phone

	return normalize_identity_phone(
		value,
		assume_local=assume_local,
		country_code=country_code,
	)


def parse_provider_timestamp(value):
	"""Convert provider timestamps to the naive system-timezone value Frappe stores.

	Meta sends Unix seconds in UTC, while Frappe's ``now_datetime`` and database
	Datetime fields use the site's system timezone.  Mixing the two makes a fresh
	inbound message sort behind locally-created outbound messages.
	"""
	if value in (None, ""):
		return now_datetime()
	if isinstance(value, (int, float)) or str(value).strip().isdigit():
		parsed = datetime.fromtimestamp(int(value), tz=timezone.utc)
	else:
		parsed = get_datetime(value)
		if parsed.tzinfo is None:
			# A timezone-less provider value is already in the site's storage format.
			return parsed
	return convert_utc_to_system_timezone(parsed).replace(tzinfo=None)
