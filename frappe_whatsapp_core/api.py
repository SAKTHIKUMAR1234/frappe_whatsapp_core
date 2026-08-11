import hashlib
import json

import frappe
from frappe.utils import now_datetime

from frappe_whatsapp_core.campaigns import enqueue_campaign_refresh_for_messages
from frappe_whatsapp_core.delivery import advance_delivery_status
from frappe_whatsapp_core.dispatcher import (
	enqueue_waiting_status_events,
	enqueue_event,
	enqueue_event_batch,
	process_event_batch,
)
from frappe_whatsapp_core.permissions import require_core_access

MAX_RECEIVE_BATCH_SIZE = 1000
CONTROL_RESULT_PREFIXES = ("read:", "typing:")


def _provider_message_id_owner(provider_message_id, message_name):
	"""Return another message already bound to a provider id, if any.

	Provider ids are unique.  A provider or relay defect must not turn a valid
	result callback into a 417 response which JetStream retries until it is
	dead-lettered.  Treat the collision as a terminal failure for the newer
	local message while preserving the message which already owns the id.
	"""
	provider_message_id = str(provider_message_id or "").strip()
	if not provider_message_id:
		return None
	return frappe.db.get_value(
		"WhatsApp Core Message",
		{
			"provider_message_id": provider_message_id,
			"name": ["!=", message_name],
		},
		"name",
	)


def _provider_id_collision_failure(provider_message_id, owner, result):
	return json.dumps(
		{
			"error": "Provider returned a message id already assigned to another message",
			"code": "provider_message_id_collision",
			"provider_message_id": provider_message_id,
			"existing_message": owner,
			"status_code": result.get("status_code"),
			"attempt": int(result.get("attempt") or 0),
			"relay_event": result.get("event_id"),
		},
		separators=(",", ":"),
	)


@frappe.whitelist()
@require_core_access(manage=True)
def receive():
	"""Persist one event or a relay-provided batch before business processing."""
	payload = frappe.request.get_json()
	if not payload:
		frappe.throw("No payload received")
	if isinstance(payload, list):
		return receive_batch(payload)
	return receive_one(payload)


@frappe.whitelist()
@require_core_access(manage=True)
def receive_outbound_result(
	idempotency_key,
	status,
	success=0,
	event_id=None,
	meta_message_id=None,
	status_code=None,
	error=None,
	attempt=0,
	**_kwargs,
):
	result = _apply_outbound_result(
		idempotency_key=idempotency_key,
		status=status,
		success=success,
		event_id=event_id,
		meta_message_id=meta_message_id,
		status_code=status_code,
		error=error,
		attempt=attempt,
	)
	if meta_message_id:
		enqueue_waiting_status_events([meta_message_id], enqueue_after_commit=True)
	return result


def _apply_outbound_result(
	idempotency_key,
	status,
	success=0,
	event_id=None,
	meta_message_id=None,
	status_code=None,
	error=None,
	attempt=0,
	**_provider_metadata,
):
	"""Idempotently apply the relay's final provider result to a local message."""
	idempotency_key = str(idempotency_key or "").strip()
	if not idempotency_key:
		frappe.throw("idempotency_key is required")
	status = str(status or "").strip().lower()
	if status not in {"sent", "failed"}:
		frappe.throw("Only final sent/failed relay results are accepted")
	# Read receipts and typing indicators travel through the durable relay, but
	# they do not create chat-message rows in Core. Acknowledge their provider
	# result so the relay does not retry and dead-letter a successful control
	# operation while looking for a message that intentionally does not exist.
	if idempotency_key.startswith(CONTROL_RESULT_PREFIXES):
		return {"status": "ignored", "reason": "control_operation"}

	message_name = frappe.db.get_value(
		"WhatsApp Core Message",
		{"idempotency_key": idempotency_key},
		"name",
	)
	if not message_name and frappe.db.exists(
		"WhatsApp Core Message",
		idempotency_key,
	):
		message_name = idempotency_key
	if not message_name:
		frappe.throw(
			f"Outbound message not found for idempotency key {idempotency_key}",
			frappe.DoesNotExistError,
		)

	message = frappe.get_doc("WhatsApp Core Message", message_name)
	incoming = "Sent" if status == "sent" and _as_bool(success) else "Failed"
	provider_owner = _provider_message_id_owner(meta_message_id, message.name)
	if provider_owner:
		incoming = "Failed"
	message.delivery_status = advance_delivery_status(
		message.delivery_status,
		incoming,
	)
	if meta_message_id and not provider_owner:
		message.provider_message_id = meta_message_id
	if provider_owner:
		message.failure = _provider_id_collision_failure(
			meta_message_id,
			provider_owner,
			{
				"status_code": status_code,
				"attempt": attempt,
				"event_id": event_id,
			},
		)
	elif incoming == "Failed":
		message.failure = json.dumps(
			{
				"error": error or "Provider send failed",
				"status_code": status_code,
				"attempt": int(attempt or 0),
				"relay_event": event_id,
			},
			separators=(",", ":"),
		)
	else:
		message.failure = None
	message.save(ignore_permissions=True)
	if not frappe.flags.whatsapp_core_result_batch:
		enqueue_campaign_refresh_for_messages([message.name])
	if not frappe.flags.whatsapp_core_result_batch:
		frappe.publish_realtime(
			"whatsapp_core_message_status",
			{
				"conversation": message.conversation,
				"message": message.name,
				"delivery_status": message.delivery_status,
				"provider_message_id": message.provider_message_id,
			},
			after_commit=True,
		)
	return {
		"status": "applied",
		"message": message.name,
		"delivery_status": message.delivery_status,
	}


@frappe.whitelist()
@require_core_access(manage=True)
def receive_outbound_results(results):
	"""Apply up to 100 durable relay results and notify the UI once."""
	if isinstance(results, str):
		results = frappe.parse_json(results)
	if not isinstance(results, list) or not 1 <= len(results) <= 100:
		frappe.throw("results must contain between 1 and 100 items", frappe.ValidationError)
	if any(not isinstance(result, dict) for result in results):
		frappe.throw("Every outbound result must be an object", frappe.ValidationError)

	# Relay workers deliberately coalesce provider results.  Loading and saving
	# one Document at a time makes a 100-result callback hold the web worker for
	# several seconds and lets WA_CALLBACKS grow without bound under a campaign.
	# Keep the single-result path (and its exact API contract) for interactive
	# calls, while applying real relay batches with one locked read and one bulk
	# update.  The row locks make the Python monotonic-state calculation safe
	# against a concurrent delivered/read webhook.
	applied = (
		_apply_outbound_result_batch(results)
		if len(results) > 1
		else [_apply_outbound_result(**results[0])]
	)
	enqueue_waiting_status_events(
		[result.get("meta_message_id") for result in results],
		enqueue_after_commit=True,
	)
	message_names = [row["message"] for row in applied if row.get("message")]
	message_rows = (
		frappe.get_all(
			"WhatsApp Core Message",
			filters={"name": ["in", message_names]},
			fields=[
				"name",
				"conversation",
				"delivery_status",
				"provider_message_id",
			],
			limit_page_length=len(message_names),
		)
		if message_names
		else []
	)
	conversations = list(dict.fromkeys(row.conversation for row in message_rows))
	if message_names:
		enqueue_campaign_refresh_for_messages(message_names)
		frappe.publish_realtime(
			"whatsapp_core_batch_committed",
			{
				"event_count": len(message_names),
				"completed": len(message_names),
				"failed": 0,
				"kinds": ["status"],
				"conversations": conversations,
				# Supplying bounded deltas lets every open inbox tab patch its
				# selected thread in memory.  Omitting them invokes the rolling-
				# deploy compatibility path, which reloads the whole inbox once per
				# relay result batch and creates a large browser/server fan-out during
				# campaigns.
				"message_changes": [
					{"status": "updated", "message": row}
					for row in message_rows
				],
			},
			after_commit=True,
		)
	ignored = len(applied) - len(message_names)
	return {
		"status": "applied",
		"count": len(message_names),
		"ignored": ignored,
		"results": applied,
	}


def _apply_outbound_result_batch(results: list[dict]) -> list[dict]:
	controls = {}
	provider_results = []
	for index, result in enumerate(results):
		idempotency_key = str(result.get("idempotency_key") or "").strip()
		if not idempotency_key:
			frappe.throw("idempotency_key is required")
		status = str(result.get("status") or "").strip().lower()
		if status not in {"sent", "failed"}:
			frappe.throw("Only final sent/failed relay results are accepted")
		if idempotency_key.startswith(CONTROL_RESULT_PREFIXES):
			controls[index] = {"status": "ignored", "reason": "control_operation"}
			continue
		provider_results.append((index, idempotency_key, status, result))

	if not provider_results:
		return [controls[index] for index in range(len(results))]

	keys = list(dict.fromkeys(item[1] for item in provider_results))
	placeholders = ", ".join(["%s"] * len(keys))
	rows = frappe.db.sql(
		f"""
		SELECT name, idempotency_key, delivery_status, conversation, provider_message_id
			FROM `tabWhatsApp Core Message`
			WHERE idempotency_key IN ({placeholders}) OR name IN ({placeholders})
			ORDER BY name
			FOR UPDATE
		""",  # nosec B608 -- placeholders are generated, never user supplied
		keys + keys,
		as_dict=True,
	)
	by_key = {}
	for row in rows:
		by_key[row.name] = row
		if row.idempotency_key:
			by_key[row.idempotency_key] = row

	provider_ids = list(dict.fromkeys(
		str(item[3].get("meta_message_id") or "").strip()
		for item in provider_results
		if item[3].get("meta_message_id")
	))
	provider_owners = {
		row.provider_message_id: row.name
		for row in frappe.get_all(
			"WhatsApp Core Message",
			filters={"provider_message_id": ["in", provider_ids]},
			fields=["name", "provider_message_id"],
			limit_page_length=len(provider_ids),
		)
	} if provider_ids else {}

	updates = {}
	applied = dict(controls)
	for index, idempotency_key, status, result in provider_results:
		row = by_key.get(idempotency_key)
		if not row:
			frappe.throw(
				f"Outbound message not found for idempotency key {idempotency_key}",
				frappe.DoesNotExistError,
			)
		incoming = "Sent" if status == "sent" and _as_bool(result.get("success")) else "Failed"
		provider_id = str(result.get("meta_message_id") or "").strip()
		provider_owner = provider_owners.get(provider_id) if provider_id else None
		if provider_owner and provider_owner != row.name:
			incoming = "Failed"
		next_status = advance_delivery_status(row.delivery_status, incoming)
		values = {"delivery_status": next_status}
		if provider_id and not provider_owner:
			values["provider_message_id"] = provider_id
			provider_owners[provider_id] = row.name
		if provider_owner and provider_owner != row.name:
			values["failure"] = _provider_id_collision_failure(
				provider_id,
				provider_owner,
				result,
			)
		elif incoming == "Failed":
			values["failure"] = json.dumps(
				{
					"error": result.get("error") or "Provider send failed",
					"status_code": result.get("status_code"),
					"attempt": int(result.get("attempt") or 0),
					"relay_event": result.get("event_id"),
				},
				separators=(",", ":"),
			)
		else:
			values["failure"] = None
		updates[row.name] = values
		row.delivery_status = next_status
		applied[index] = {
			"status": "applied",
			"message": row.name,
			"delivery_status": next_status,
		}

	frappe.db.bulk_update(
		"WhatsApp Core Message",
		updates,
		chunk_size=100,
		update_modified=False,
	)
	for message_name in updates:
		frappe.clear_document_cache("WhatsApp Core Message", message_name)
	return [applied[index] for index in range(len(results))]


def receive_one(payload):
	event = describe_payload(payload)
	event_id = payload_fingerprint(payload)
	if frappe.db.exists("WhatsApp Core Event", event_id):
		return {"status": "duplicate", "event_id": event_id}

	try:
		doc = frappe.get_doc({
			"doctype": "WhatsApp Core Event",
			"event_id": event_id,
			"status": "Pending",
			"event_type": event["event_type"],
			"direction": "Inbound",
			"channel_key": event["channel_key"],
			"external_id": event["external_id"],
			"conversation_key": event["conversation_key"],
			"payload": canonical_json(payload),
		})
		doc.insert(ignore_permissions=True)
	except frappe.DuplicateEntryError:
		return {"status": "duplicate", "event_id": event_id}

	if _requires_immediate_projection(event):
		result = process_event_batch([event_id])[0]
		if result.get("status") != "completed":
			frappe.throw(
				"Inbound WhatsApp message could not be projected",
				frappe.ValidationError,
			)
		return {
			"status": "processed",
			"event_id": event_id,
			"immediate": True,
		}
	enqueue_event(event_id, enqueue_after_commit=True)
	return {"status": "queued", "event_id": event_id, "immediate": False}


def receive_batch(payloads):
	"""Insert a relay window with one SQL operation and enqueue one background job."""
	if not payloads:
		frappe.throw("No events received")
	if len(payloads) > MAX_RECEIVE_BATCH_SIZE:
		frappe.throw(f"Batch exceeds the {MAX_RECEIVE_BATCH_SIZE} event safety limit")
	if any(not isinstance(payload, dict) for payload in payloads):
		frappe.throw("Every batch item must be a JSON object")

	described = []
	for payload in payloads:
		event_id = payload_fingerprint(payload)
		described.append((event_id, describe_payload(payload), canonical_json(payload)))

	event_ids = list(dict.fromkeys(item[0] for item in described))
	existing = set(frappe.get_all(
		"WhatsApp Core Event",
		filters={"name": ["in", event_ids]},
		pluck="name",
	))
	new_items = []
	seen = set(existing)
	for event_id, event, canonical_payload in described:
		if event_id in seen:
			continue
		seen.add(event_id)
		new_items.append((event_id, event, canonical_payload))

	immediate_ids = []
	deferred_ids = []
	if new_items:
		timestamp = now_datetime()
		user = frappe.session.user or "Administrator"
		fields = [
			"name", "creation", "modified", "modified_by", "owner", "docstatus", "idx",
			"event_id", "status", "event_type", "direction", "channel_key",
			"external_id", "conversation_key", "payload", "attempts",
		]
		values = [
			(
				event_id, timestamp, timestamp, user, user, 0, 0,
				event_id, "Pending", event["event_type"], "Inbound",
				event["channel_key"], event["external_id"], event["conversation_key"],
				canonical_payload, 0,
			)
			for event_id, event, canonical_payload in new_items
		]
		frappe.db.bulk_insert(
			"WhatsApp Core Event",
			fields=fields,
			values=values,
			ignore_duplicates=True,
		)
		for event_id, event, _canonical_payload in new_items:
			(
				immediate_ids
				if _requires_immediate_projection(event)
				else deferred_ids
			).append(event_id)

		# Customer messages, echoes, calls and group activity must be visible in
		# the operator UI in the same transaction that accepts the relay batch.
		# High-volume delivery/read receipts stay on the short queue so they can
		# be coalesced without delaying human-visible activity.
		immediate_results = []
		for offset in range(0, len(immediate_ids), 100):
			immediate_results.extend(
				process_event_batch(immediate_ids[offset : offset + 100])
			)
		if any(result.get("status") != "completed" for result in immediate_results):
			frappe.throw(
				"One or more inbound WhatsApp messages could not be projected",
				frappe.ValidationError,
			)
		if deferred_ids:
			enqueue_event_batch(deferred_ids, enqueue_after_commit=True)

	return {
		"status": "processed" if immediate_ids and not deferred_ids else "queued",
		"received": len(payloads),
		"inserted": len(new_items),
		"duplicates": len(payloads) - len(new_items),
		"event_ids": [item[0] for item in new_items],
		"immediate": len(immediate_ids),
		"deferred": len(deferred_ids),
	}


def _requires_immediate_projection(event: dict) -> bool:
	event_type = str(event.get("event_type") or "")
	return event_type.startswith(("message:", "message_echo:", "call:", "group:"))


def payload_fingerprint(payload):
	return hashlib.sha256(canonical_json(payload).encode()).hexdigest()


def canonical_json(payload):
	return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _as_bool(value):
	if isinstance(value, str):
		return value.lower() in {"1", "true", "yes"}
	return bool(value)


def describe_payload(payload):
	description = {
		"event_type": "unknown",
		"channel_key": "",
		"external_id": "",
		"conversation_key": "",
	}
	if payload.get("template_status_update"):
		value = payload["template_status_update"]
		description.update({
			"event_type": "template_status",
			"external_id": str(value.get("message_template_id") or value.get("message_template_name") or ""),
		})
		return description

	for entry in payload.get("entry", []):
		for change in entry.get("changes", []):
			value = change.get("value", {})
			description["channel_key"] = value.get("metadata", {}).get("phone_number_id", "")
			if change.get("field") == "message_template_status_update":
				description["event_type"] = "template_status"
				description["external_id"] = str(
					value.get("message_template_id") or value.get("message_template_name") or ""
				)
				return description
			messages = value.get("messages", [])
			if messages:
				message = messages[0]
				description.update({
					"event_type": f"message:{message.get('type', 'unknown')}",
					"external_id": message.get("id", ""),
					"conversation_key": message.get("from", ""),
				})
				return description
			statuses = value.get("statuses", [])
			if statuses:
				status = statuses[0]
				description.update({
					"event_type": f"status:{status.get('status', 'unknown')}",
					"external_id": status.get("id", ""),
					"conversation_key": status.get("recipient_id", ""),
				})
				return description
			calls = value.get("calls", [])
			if calls:
				call = calls[0]
				description.update({
					"event_type": f"call:{call.get('event') or call.get('status') or 'unknown'}",
					"external_id": call.get("id") or call.get("call_id") or "",
					"conversation_key": call.get("from") or call.get("to") or call.get("recipient") or "",
				})
				return description
			groups = value.get("groups", [])
			if groups:
				group = groups[0]
				description.update({
					"event_type": f"group:{group.get('type') or change.get('field') or 'unknown'}",
					"external_id": group.get("group_id") or group.get("request_id") or "",
					"conversation_key": group.get("group_id") or "",
				})
				return description
			message_echoes = value.get("message_echoes", [])
			if message_echoes:
				message = message_echoes[0]
				description.update({
					"event_type": f"message_echo:{message.get('type', 'unknown')}",
					"external_id": message.get("id", ""),
					"conversation_key": message.get("to") or message.get("recipient_id") or "",
				})
				return description
			history = value.get("history", [])
			if history:
				batch = history[0] if isinstance(history, list) else history
				threads = batch.get("threads", []) if isinstance(batch, dict) else []
				thread = threads[0] if threads else {}
				message = (thread.get("messages") or [{}])[0]
				description.update({
					"event_type": "coexistence:history",
					"channel_key": (batch.get("metadata") or {}).get("phone_number_id", ""),
					"external_id": message.get("id", ""),
					"conversation_key": thread.get("id") or thread.get("wa_id") or "",
				})
				return description
			if value.get("state_sync"):
				description["event_type"] = "coexistence:state_sync"
				return description
	return description
