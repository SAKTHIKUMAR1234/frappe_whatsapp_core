import hashlib
import json
import random
import time

import frappe
from frappe.utils import now_datetime

from frappe_whatsapp_core.campaigns import enqueue_campaign_refresh_for_messages
from frappe_whatsapp_core.delivery import (
	advance_delivery_status,
	enqueue_delivery_status_handlers,
)
from frappe_whatsapp_core.dispatcher import (
	enqueue_waiting_status_events,
	enqueue_event,
	enqueue_event_batch,
	process_event_batch,
)
from frappe_whatsapp_core.permissions import require_transport_access
from frappe_whatsapp_core.realtime import publish_message_changes

MAX_RECEIVE_BATCH_SIZE = 1000
IMMEDIATE_STATUS_BATCH_SIZE = 10
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
@require_transport_access()
def receive():
	"""Persist one event or a relay-provided batch before business processing."""
	payload = frappe.request.get_json()
	if not payload:
		frappe.throw("No payload received")
	if isinstance(payload, list):
		return receive_batch(payload)
	return receive_one(payload)


@frappe.whitelist()
@require_transport_access()
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
	"""Apply one result through the same locked path used by relay batches."""
	result = _apply_outbound_result_batch([{
		"idempotency_key": idempotency_key,
		"status": status,
		"success": success,
		"event_id": event_id,
		"meta_message_id": meta_message_id,
		"status_code": status_code,
		"error": error,
		"attempt": attempt,
		**_provider_metadata,
	}])[0]
	if result.get("status") != "applied" or not result.get("message"):
		return result
	message = frappe.db.get_value(
		"WhatsApp Core Message",
		result["message"],
		["name", "conversation", "delivery_status", "provider_message_id"],
		as_dict=True,
	)
	if message:
		enqueue_campaign_refresh_for_messages([message.name])
		publish_message_changes([{
			"kind": "status",
			"status": "updated",
			"name": message.name,
		}])
	return result


@frappe.whitelist()
@require_transport_access()
def receive_outbound_results(results):
	"""Apply up to 100 durable relay results and notify the UI once."""
	if isinstance(results, str):
		results = frappe.parse_json(results)
	if not isinstance(results, list) or not 1 <= len(results) <= 100:
		frappe.throw("results must contain between 1 and 100 items", frappe.ValidationError)
	if any(not isinstance(result, dict) for result in results):
		frappe.throw("Every outbound result must be an object", frappe.ValidationError)
	for attempt in range(6):
		try:
			return _receive_outbound_results_once(results)
		except frappe.QueryDeadlockError:
			# MyRocks can reject a row after a concurrent status callback changes it,
			# even though the batch took ordered FOR UPDATE locks. Restart the entire
			# result window from committed state instead of returning 500 to JetStream.
			frappe.db.rollback()
			if attempt == 5:
				raise
			time.sleep(min(1.5, 0.04 * (2**attempt)) + random.uniform(0, 0.02))


def _receive_outbound_results_once(results):
	"""Apply one validated relay result window in a single transaction."""

	# One and many results intentionally use the same ordered lock/update path.
	# A special one-document save path races status callbacks and reintroduces the
	# timestamp mismatch that batching is intended to remove.
	applied = _apply_outbound_result_batch(results)
	enqueue_waiting_status_events(
		[result.get("meta_message_id") for result in results],
		enqueue_after_commit=True,
	)
	message_names = list(dict.fromkeys(
		row["message"]
		for row in applied
		if row.get("status") == "applied" and row.get("message")
	))
	if message_names:
		enqueue_campaign_refresh_for_messages(message_names)
		publish_message_changes([
			{"kind": "status", "status": "updated", "name": name}
			for name in message_names
		])
	ignored = sum(row.get("status") == "ignored" for row in applied)
	unchanged = sum(row.get("status") == "noop" for row in applied)
	return {
		"status": "applied",
		"count": len(message_names),
		"ignored": ignored,
		"unchanged": unchanged,
		"results": applied,
	}


def _apply_outbound_result_batch(results: list[dict]) -> list[dict]:
	controls = {}
	provider_candidates = []
	last_result_by_key = {}
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
		provider_candidates.append((index, idempotency_key, status, result))
		last_result_by_key[idempotency_key] = index

	# Relay retries can place the same idempotency key in one callback window.
	# Apply only the last observation so contradictory duplicates cannot overwrite
	# the same bulk-update entry in input-order-dependent ways.
	provider_results = []
	for item in provider_candidates:
		index, idempotency_key, _status, _result = item
		if last_result_by_key[idempotency_key] != index:
			controls[index] = {
				"status": "ignored",
				"reason": "superseded_in_batch",
			}
			continue
		provider_results.append(item)

	if not provider_results:
		return [controls[index] for index in range(len(results))]

	keys = list(dict.fromkeys(item[1] for item in provider_results))
	placeholders = ", ".join(["%s"] * len(keys))
	rows = frappe.db.sql(
		f"""
		SELECT
			name, idempotency_key, delivery_status, conversation,
			provider_message_id, failure
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
		desired_provider_id = row.provider_message_id
		if provider_id and not provider_owner:
			desired_provider_id = provider_id
			provider_owners[provider_id] = row.name
		desired_failure = row.failure
		if provider_owner and provider_owner != row.name and next_status == "Failed":
			desired_failure = _provider_id_collision_failure(
				provider_id,
				provider_owner,
				result,
			)
		elif incoming == "Failed" and next_status == "Failed":
			desired_failure = json.dumps(
				{
					"error": result.get("error") or "Provider send failed",
					"status_code": result.get("status_code"),
					"attempt": int(result.get("attempt") or 0),
					"relay_event": result.get("event_id"),
				},
				separators=(",", ":"),
			)
		elif incoming == "Sent" and next_status == "Sent":
			desired_failure = None
		values = {
			"delivery_status": next_status,
			"provider_message_id": desired_provider_id,
			"failure": desired_failure,
		}
		changed = any(
			(current or None) != (values[fieldname] or None)
			for fieldname, current in {
				"delivery_status": row.delivery_status,
				"provider_message_id": row.provider_message_id,
				"failure": row.failure,
			}.items()
		)
		if not changed:
			applied[index] = {
				"status": "noop",
				"message": row.name,
				"delivery_status": row.delivery_status,
			}
			continue
		updates[row.name] = values
		row.delivery_status = next_status
		row.provider_message_id = desired_provider_id
		row.failure = desired_failure
		applied[index] = {
			"status": "applied",
			"message": row.name,
			"delivery_status": next_status,
		}

	if updates:
		frappe.db.bulk_update(
			"WhatsApp Core Message",
			updates,
			chunk_size=100,
			update_modified=False,
		)
		enqueue_delivery_status_handlers([
			{
				"message_name": message_name,
				"delivery_status": values["delivery_status"],
			}
			for message_name, values in updates.items()
		])
	for message_name in updates:
		frappe.clear_document_cache("WhatsApp Core Message", message_name)
	return [applied[index] for index in range(len(results))]


def receive_one(payload):
	event = describe_payload(payload)
	event_id = payload_fingerprint(payload)
	if frappe.db.exists("WhatsApp Core Event", {"event_id": event_id}):
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
	except (frappe.DuplicateEntryError, frappe.UniqueValidationError):
		return {"status": "duplicate", "event_id": event_id}

	if _is_status_event(event):
		result = process_event_batch([doc.name], retry_deadlocks=False)[0]
		accepted_statuses = {"completed", "deferred", "missing"}
		if result.get("status") not in accepted_statuses:
			frappe.throw(
				"Inbound WhatsApp message could not be projected",
				frappe.ValidationError,
			)
		return {
			"status": "processed",
			"event_id": event_id,
			"immediate": True,
		}
	enqueue_event(
		doc.name,
		enqueue_after_commit=True,
		serialization_key=event.get("conversation_key") or doc.name,
	)
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
		filters={"event_id": ["in", event_ids]},
		pluck="event_id",
	))
	new_items = []
	seen = set(existing)
	for event_id, event, canonical_payload in described:
		if event_id in seen:
			continue
		seen.add(event_id)
		new_items.append((event_id, event, canonical_payload))

	status_ids = []
	deferred_ids = []
	deferred_groups = {}
	if new_items:
		named_new_items = [
			(frappe.generate_hash(length=10), event_id, event, canonical_payload)
			for event_id, event, canonical_payload in new_items
		]
		timestamp = now_datetime()
		user = frappe.session.user or "Administrator"
		fields = [
			"name", "creation", "modified", "modified_by", "owner", "docstatus", "idx",
			"event_id", "status", "event_type", "direction", "channel_key",
			"external_id", "conversation_key", "payload", "attempts",
		]
		values = [
			(
				record_name, timestamp, timestamp, user, user, 0, 0,
				event_id, "Pending", event["event_type"], "Inbound",
				event["channel_key"], event["external_id"], event["conversation_key"],
				canonical_payload, 0,
			)
			for record_name, event_id, event, canonical_payload in named_new_items
		]
		frappe.db.bulk_insert(
			"WhatsApp Core Event",
			fields=fields,
			values=values,
			ignore_duplicates=True,
		)
		for record_name, _event_id, event, _canonical_payload in named_new_items:
			if _is_status_event(event):
				status_ids.append(record_name)
			else:
				deferred_ids.append(record_name)
				serialization_key = event.get("conversation_key") or record_name
				deferred_groups.setdefault(serialization_key, []).append(record_name)

		# The Core Event table is the durable ingress boundary. Human-visible work
		# (messages, echoes, calls and groups) is projected on short workers only
		# after this request commits, so a burst cannot hold the relay callback open
		# until its HTTP timeout and create duplicate JetStream deliveries. Small
		# status windows stay synchronous because their projector is a bounded bulk
		# update and the UI benefits from immediate sent/delivered/read state.
		if status_ids and len(status_ids) <= IMMEDIATE_STATUS_BATCH_SIZE:
			status_results = process_event_batch(status_ids)
			if any(
				result.get("status") not in {"completed", "deferred", "missing"}
				for result in status_results
			):
				frappe.throw(
					"One or more WhatsApp status updates could not be projected",
					frappe.ValidationError,
				)
		else:
			deferred_ids.extend(status_ids)

		for serialization_key, group_ids in deferred_groups.items():
			enqueue_event_batch(
				group_ids,
				enqueue_after_commit=True,
				serialization_key=serialization_key,
			)
		if status_ids and len(status_ids) > IMMEDIATE_STATUS_BATCH_SIZE:
			enqueue_event_batch(status_ids, enqueue_after_commit=True)

	immediate_count = (
		len(status_ids) if len(status_ids) <= IMMEDIATE_STATUS_BATCH_SIZE else 0
	)

	return {
		"status": "processed" if immediate_count and not deferred_ids else "queued",
		"received": len(payloads),
		"inserted": len(new_items),
		"duplicates": len(payloads) - len(new_items),
		"event_ids": [item[0] for item in new_items],
		"immediate": immediate_count,
		"deferred": len(deferred_ids),
	}


def _is_status_event(event: dict) -> bool:
	return str(event.get("event_type") or "").startswith("status:")


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
