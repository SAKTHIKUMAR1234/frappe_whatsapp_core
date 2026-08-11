import hashlib
import json
import random
import time

import frappe
from frappe.utils import add_to_date, now, now_datetime

from frappe_whatsapp_core.materializer import materialize_event
from frappe_whatsapp_core.message_media import add_media_url, enqueue_message_media_cache

MAX_ATTEMPTS = 6
MAX_REALTIME_BATCH_SIZE = 100
STATUS_BATCH_DEADLOCK_RETRIES = 10
ORPHAN_STATUS_RETRY_BASE_SECONDS = 0.25
ORPHAN_STATUS_RETRY_MAX_SECONDS = 2.0
MESSAGE_PROJECTION_KINDS = {"message", "status", "edit", "revoke"}


def enqueue_event(event_id, enqueue_after_commit=False):
	frappe.enqueue(
		"frappe_whatsapp_core.dispatcher.process_event",
		queue="short",
		enqueue_after_commit=enqueue_after_commit,
		event_id=event_id,
	)


def enqueue_event_batch(event_ids, enqueue_after_commit=False):
	if not event_ids:
		return
	unique_ids = list(dict.fromkeys(event_ids))
	for offset in range(0, len(unique_ids), MAX_REALTIME_BATCH_SIZE):
		frappe.enqueue(
			"frappe_whatsapp_core.dispatcher.process_event_batch",
			queue="short",
			enqueue_after_commit=enqueue_after_commit,
			event_ids=unique_ids[offset : offset + MAX_REALTIME_BATCH_SIZE],
		)


def enqueue_orphan_status_retry(event_ids, attempt=1, enqueue_after_commit=True):
	"""Retry receipts that raced the provider-ID binding transaction.

	The outbound-result request and a status-webhook request are independent
	database transactions.  Querying for waiting events from the result request
	is not sufficient: under REPEATABLE READ that transaction can start before
	the status request commits and miss it permanently.  A bounded after-commit
	retry gives the receipt a fresh transaction and closes that lost-wakeup race.
	"""
	event_ids = list(dict.fromkeys(event_ids or []))
	if not event_ids:
		return
	delay_seconds = min(
		ORPHAN_STATUS_RETRY_MAX_SECONDS,
		ORPHAN_STATUS_RETRY_BASE_SECONDS * (2 ** max(0, int(attempt or 1) - 1)),
	)
	frappe.enqueue(
		"frappe_whatsapp_core.dispatcher.retry_orphan_status_events",
		queue="short",
		enqueue_after_commit=enqueue_after_commit,
		event_ids=event_ids,
		delay_seconds=delay_seconds,
	)


def retry_orphan_status_events(event_ids, delay_seconds=ORPHAN_STATUS_RETRY_BASE_SECONDS):
	"""Run a deferred receipt retry in a new database transaction."""
	time.sleep(max(0.0, min(float(delay_seconds or 0), ORPHAN_STATUS_RETRY_MAX_SECONDS)))
	return process_event_batch(event_ids)


def retry_stale_events(limit=1000):
	"""Requeue events abandoned by a worker crash or exhausted DB retry.

	Fresh events are left to their original after-commit job. The conditional
	update prevents a concurrently completed event from being regressed.
	"""
	limit = max(1, min(int(limit or 1000), 5000))
	cutoff = add_to_date(now_datetime(), minutes=-2)
	event_ids = frappe.get_all(
		"WhatsApp Core Event",
		filters={
			"status": ["in", ["Pending", "Queued"]],
			"modified": ["<", cutoff],
		},
		order_by="modified asc",
		pluck="name",
		limit_page_length=limit,
	)
	if not event_ids:
		return {"requeued": 0}
	frappe.db.sql(
		"""
		UPDATE `tabWhatsApp Core Event`
		SET status = 'Queued', modified = NOW(6)
		WHERE name IN %(event_ids)s
		  AND status IN ('Pending', 'Queued')
		""",
		{"event_ids": event_ids},
	)
	enqueue_event_batch(event_ids, enqueue_after_commit=True)
	return {"requeued": len(event_ids)}


def enqueue_waiting_status_events(provider_ids, enqueue_after_commit=True):
	"""Wake receipts that arrived before their outbound provider ID was bound."""
	provider_ids = list(dict.fromkeys(
		str(provider_id).strip()
		for provider_id in provider_ids or []
		if str(provider_id or "").strip()
	))
	if not provider_ids:
		return 0
	# Under load the outbound-result queue can legitimately take longer than the
	# bounded orphan backoff.  A receipt may therefore exhaust MAX_ATTEMPTS before
	# the provider id is bound.  Binding the id is the authoritative wake-up: reset
	# only that recoverable orphan failure and retry it in a fresh transaction.
	event_ids = frappe.get_all(
		"WhatsApp Core Event",
		filters={
			"external_id": ["in", provider_ids],
			"event_type": ["like", "status:%"],
			"status": ["in", ["Pending", "Queued", "Failed"]],
			"error": ["in", ["", "Awaiting matching outbound provider result"]],
		},
		pluck="name",
		limit_page_length=min(len(provider_ids) * 4, 5000),
	)
	if event_ids:
		frappe.db.sql(
			"""
			UPDATE `tabWhatsApp Core Event`
			SET status = 'Queued', attempts = 0, error = '', modified = NOW(6)
			WHERE name IN %(event_ids)s
			  AND status IN ('Pending', 'Queued', 'Failed')
			  AND error IN ('', 'Awaiting matching outbound provider result')
			""",
			{"event_ids": event_ids},
		)
	enqueue_event_batch(event_ids, enqueue_after_commit=enqueue_after_commit)
	return len(event_ids)


def replay_orphaned_status_events(limit=5000, since=None, start=0):
	"""Repair status events completed by older releases before ID binding.

	This migration-safe helper is intentionally not scheduled. New events are
	deferred by ``_has_orphan_status`` and woken by the outbound-result handler.
	"""
	limit = max(1, min(int(limit or 5000), 5000))
	start = max(0, int(start or 0))
	filters = {
		"event_type": "status:read",
		"status": "Completed",
	}
	if since:
		filters["creation"] = [">=", since]
	events = frappe.get_all(
		"WhatsApp Core Event",
		filters=filters,
		fields=["name", "external_id"],
		order_by="modified asc",
		limit_start=start,
		limit_page_length=limit,
	)
	provider_ids = list(dict.fromkeys(row.external_id for row in events if row.external_id))
	message_states = {
		row.provider_message_id: row.delivery_status
		for row in frappe.get_all(
			"WhatsApp Core Message",
			filters={"provider_message_id": ["in", provider_ids]},
			fields=["provider_message_id", "delivery_status"],
			limit_page_length=len(provider_ids),
		)
	}
	event_ids = [
		row.name
		for row in events
		if message_states.get(row.external_id) not in {None, "Read", "Failed", "Deleted"}
	]
	if not event_ids:
		return {"requeued": 0}
	frappe.db.sql(
		"""
		UPDATE `tabWhatsApp Core Event`
		SET status = 'Queued', attempts = 0, error = '', modified = NOW(6)
		WHERE name IN %(event_ids)s
		  AND status = 'Completed'
		""",
		{"event_ids": event_ids},
	)
	enqueue_event_batch(event_ids, enqueue_after_commit=True)
	return {"requeued": len(event_ids)}


def process_event_batch(event_ids):
	"""Process one committed relay window and notify clients once per batch."""
	if len(event_ids) > MAX_REALTIME_BATCH_SIZE:
		frappe.throw(
			f"Core event batches cannot exceed {MAX_REALTIME_BATCH_SIZE} events",
			frappe.ValidationError,
		)
	event_ids = list(dict.fromkeys(event_ids))
	if _is_pure_status_batch(event_ids):
		return _process_status_event_batch_with_retry(event_ids)
	results = []
	frappe.flags.whatsapp_core_batch_processing = True
	frappe.flags.whatsapp_core_campaign_message_names = set()
	try:
		for event_id in event_ids:
			try:
				results.append({"event_id": event_id, **process_event(event_id)})
			except Exception:
				results.append({"event_id": event_id, "status": "failed"})
	finally:
		frappe.flags.whatsapp_core_batch_processing = False
	message_names = list(frappe.flags.whatsapp_core_campaign_message_names or [])
	frappe.flags.whatsapp_core_campaign_message_names = set()
	if message_names:
		from frappe_whatsapp_core.campaigns import refresh_campaigns_for_messages

		refresh_campaigns_for_messages(message_names)
	_publish_batch_refresh(event_ids, results)
	return results


def _process_status_event_batch_with_retry(event_ids):
	"""Retry the whole status transaction after a database deadlock.

	MariaDB rolls back the complete transaction on a deadlock, including every
	savepoint. Retrying an individual row would therefore mark earlier rows as
	completed even though their projections were rolled back.
	"""
	for attempt in range(STATUS_BATCH_DEADLOCK_RETRIES):
		try:
			return _process_status_event_batch(event_ids)
		except frappe.QueryDeadlockError:
			frappe.db.rollback()
			if attempt == STATUS_BATCH_DEADLOCK_RETRIES - 1:
				raise
		time.sleep(min(2.0, 0.1 * (2**attempt)) + random.uniform(0, 0.05))


def _is_pure_status_batch(event_ids) -> bool:
	if not event_ids:
		return False
	status_ids = frappe.get_all(
		"WhatsApp Core Event",
		filters={
			"name": ["in", event_ids],
			"event_type": ["like", "status:%"],
		},
		pluck="name",
		limit_page_length=len(event_ids),
	)
	if any(not isinstance(event_id, str) for event_id in status_ids):
		return False
	return len(set(status_ids)) == len(event_ids)


def _process_status_event_batch(event_ids):
	"""Materialize status telemetry in bulk without invoking message handlers."""
	events = frappe.get_all(
		"WhatsApp Core Event",
		filters={"name": ["in", event_ids]},
		fields=["name", "payload", "status", "attempts"],
		limit_page_length=len(event_ids),
	)
	by_name = {row.name: row for row in events}
	_lock_status_projection_rows(events)
	results = []
	completed = []
	deferred = []
	failed = []
	channel_cache = {}
	frappe.flags.whatsapp_core_batch_processing = True
	frappe.flags.whatsapp_core_campaign_message_names = set()
	try:
		for event_id in event_ids:
			row = by_name.get(event_id)
			if not row:
				results.append({"event_id": event_id, "status": "missing"})
				continue
			if row.status == "Completed":
				results.append({"event_id": event_id, "status": "completed"})
				continue
			savepoint = "wa_status_" + hashlib.sha256(event_id.encode()).hexdigest()[:16]
			frappe.db.savepoint(savepoint)
			try:
				projections = materialize_event(
					frappe._dict(name=event_id),
					json.loads(row.payload),
					channel_cache=channel_cache,
				)
				if _has_orphan_status(projections):
					deferred.append(event_id)
					results.append({
						"event_id": event_id,
						"status": "deferred",
						"projections": projections,
					})
					continue
				completed.append(event_id)
				results.append({
					"event_id": event_id,
					"status": "completed",
					"projections": projections,
				})
			except frappe.QueryDeadlockError:
				# A deadlock invalidates every savepoint in the transaction. Let the
				# outer retry restart the entire batch from committed state.
				raise
			except Exception:
				frappe.db.rollback(save_point=savepoint)
				failed.append((event_id, frappe.get_traceback()))
				results.append({"event_id": event_id, "status": "failed"})
	finally:
		frappe.flags.whatsapp_core_batch_processing = False

	if completed:
		frappe.db.sql(
			"""
			UPDATE `tabWhatsApp Core Event`
			SET
				status = 'Completed',
				attempts = attempts + 1,
				processed_on = NOW(6),
				error = '',
				modified = NOW(6)
			WHERE name IN %(event_ids)s
			""",
			{"event_ids": completed},
		)
	if deferred:
		frappe.db.sql(
			"""
			UPDATE `tabWhatsApp Core Event`
			SET
				status = CASE WHEN attempts + 1 >= %(max_attempts)s THEN 'Failed' ELSE 'Pending' END,
				attempts = attempts + 1,
				error = 'Awaiting matching outbound provider result',
				modified = NOW(6)
			WHERE name IN %(event_ids)s
			""",
			{"event_ids": deferred, "max_attempts": MAX_ATTEMPTS},
		)
		retry_ids = [
			event_id
			for event_id in deferred
			if int(by_name[event_id].attempts or 0) + 1 < MAX_ATTEMPTS
		]
		if retry_ids:
			attempt = max(int(by_name[event_id].attempts or 0) + 1 for event_id in retry_ids)
			enqueue_orphan_status_retry(retry_ids, attempt=attempt)
	for event_id, error in failed:
		frappe.db.set_value(
			"WhatsApp Core Event",
			event_id,
			{"status": "Failed", "error": error, "attempts": 1},
			update_modified=False,
		)

	message_names = list(frappe.flags.whatsapp_core_campaign_message_names or [])
	frappe.flags.whatsapp_core_campaign_message_names = set()
	if message_names:
		from frappe_whatsapp_core.campaigns import reconcile_campaign_status_batch

		reconcile_campaign_status_batch(message_names)
	_publish_batch_refresh(event_ids, results)
	return results


def _lock_status_projection_rows(events):
	"""Serialize overlapping provider receipts in one deterministic lock order."""
	provider_ids = []
	for row in events:
		try:
			payload = json.loads(row.payload)
		except (TypeError, ValueError):
			continue
		for entry in payload.get("entry") or []:
			for change in entry.get("changes") or []:
				for status in (change.get("value") or {}).get("statuses") or []:
					provider_id = str(status.get("id") or "").strip()
					if provider_id:
						provider_ids.append(provider_id)
	provider_ids = list(dict.fromkeys(provider_ids))
	if not provider_ids:
		return []
	message_names = sorted(frappe.get_all(
		"WhatsApp Core Message",
		filters={"provider_message_id": ["in", provider_ids]},
		pluck="name",
		limit_page_length=len(provider_ids),
	))
	if message_names:
		frappe.db.sql(
			"""
			SELECT name
			FROM `tabWhatsApp Core Message`
			WHERE name IN %(message_names)s
			ORDER BY name
			FOR UPDATE
			""",
			{"message_names": message_names},
		)
	return message_names


def _has_orphan_status(projections):
	return any(
		projection.get("kind") == "status" and projection.get("status") == "orphan"
		for projection in projections or []
	)


def process_event(event_id):
	event = frappe.get_doc("WhatsApp Core Event", event_id)
	if event.status == "Completed":
		return {"status": "completed"}

	event.status = "Processing"
	event.attempts = (event.attempts or 0) + 1
	event.error = ""
	event.save(ignore_permissions=True)

	payload = json.loads(event.payload)
	try:
		projections = materialize_event(event, payload)
		if _has_orphan_status(projections):
			event.status = "Pending" if event.attempts < MAX_ATTEMPTS else "Failed"
			event.error = "Awaiting matching outbound provider result"
			event.save(ignore_permissions=True)
			if event.status == "Pending":
				enqueue_orphan_status_retry([event.name], attempt=event.attempts)
			return {"status": "deferred", "projections": projections, "results": []}
		created_messages = [
			projection["name"]
			for projection in projections
			if projection.get("kind") == "message"
			and projection.get("status") == "created"
			and projection.get("name")
		]
		new_media_messages = (
			frappe.get_all(
				"WhatsApp Core Message",
				filters={
					"name": ["in", created_messages],
					"message_type": ["in", ["audio", "document", "image", "sticker", "video"]],
				},
				pluck="name",
				limit_page_length=len(created_messages),
			)
			if created_messages
			else []
		)
		if new_media_messages:
			enqueue_message_media_cache(new_media_messages, enqueue_after_commit=True)
		handlers = [
			"frappe_whatsapp_core.core_event_handler.handle_core_event",
			*(frappe.get_hooks("whatsapp_core_event_handlers") or []),
		]

		results = []
		for handler_path in handlers:
			run_key = hashlib.sha256(f"{event.name}:{handler_path}:v1".encode()).hexdigest()
			if frappe.db.exists(
				"WhatsApp Core Handler Run",
				{"name": run_key, "status": "Completed"},
			):
				results.append({"handler": handler_path, "status": "duplicate"})
				continue
			run = _start_handler_run(run_key, event.name, handler_path)
			handler = frappe.get_attr(handler_path)
			try:
				result = handler(payload=payload, event=event)
				run.status = "Completed"
				run.completed_at = now()
				run.result = json.dumps(result, default=str)
				run.error = ""
				run.save(ignore_permissions=True)
				results.append(result)
			except Exception:
				run.status = "Failed"
				run.completed_at = now()
				run.error = frappe.get_traceback()
				run.save(ignore_permissions=True)
				raise
		event.status = "Completed"
		event.processed_on = now()
		event.error = ""
		event.save(ignore_permissions=True)
		return {"status": "completed", "projections": projections, "results": results}
	except Exception:
		event.status = "Failed"
		event.error = frappe.get_traceback()
		event.save(ignore_permissions=True)
		frappe.log_error(
			title=f"WhatsApp Core Event failed: {event.name}",
			message=event.error,
		)
		raise


def _publish_batch_refresh(event_ids, results):
	"""Emit one compact refresh only after the worker transaction commits."""
	changes_by_message = {}
	changed_kinds = set()
	for result in results:
		for projection in result.get("projections") or []:
			kind = projection.get("kind")
			status = projection.get("status")
			if status not in {"created", "updated"}:
				continue
			if kind:
				changed_kinds.add(kind)
			if kind in MESSAGE_PROJECTION_KINDS and projection.get("name"):
				previous = changes_by_message.get(projection["name"]) or {}
				changes_by_message[projection["name"]] = {
					"kind": kind,
					"status": (
						"created"
						if previous.get("status") == "created" or status == "created"
						else status
					),
				}

	message_changes = []
	if changes_by_message:
		message_rows = frappe.get_all(
			"WhatsApp Core Message",
			filters={"name": ["in", list(changes_by_message)]},
			fields=[
				"name",
				"conversation",
				"provider_message_id",
				"direction",
				"message_type",
				"body",
				"content",
				"provider_timestamp",
				"delivery_status",
				"failure",
				"owner",
				"creation",
			],
			limit_page_length=MAX_REALTIME_BATCH_SIZE,
		)
		owners = {
			row.get("owner")
			for row in message_rows
			if row.get("direction") == "Outbound" and row.get("owner")
		}
		owner_names = {
			row.name: row.full_name or row.name
			for row in frappe.get_all(
				"User",
				filters={"name": ["in", list(owners)]},
				fields=["name", "full_name"],
				limit_page_length=max(1, len(owners)),
			)
		} if owners else {}
		for row in message_rows:
			row["sender_name"] = (
				owner_names.get(row.get("owner"), row.get("owner"))
				if row.get("direction") == "Outbound"
				else ""
			)
			# Realtime message deltas must have the same media projection as a
			# normal inbox reload; otherwise an inbound image initially renders as
			# caption-only until the user refreshes the conversation.
			add_media_url(row)
		rows_by_name = {row["name"]: row for row in message_rows}
		message_changes = [
			{
				**change,
				"message": rows_by_name[name],
			}
			for name, change in changes_by_message.items()
			if name in rows_by_name
		]
	conversations = list(dict.fromkeys(
		change["message"]["conversation"] for change in message_changes
	))
	frappe.publish_realtime(
		"whatsapp_core_batch_committed",
		{
			"event_count": len(event_ids),
			"completed": sum(result.get("status") == "completed" for result in results),
			"failed": sum(result.get("status") == "failed" for result in results),
			"kinds": sorted(changed_kinds),
			"conversations": conversations,
			"message_changes": message_changes,
		},
		after_commit=True,
	)


def _start_handler_run(run_key, event_id, handler_path):
	if frappe.db.exists("WhatsApp Core Handler Run", run_key):
		run = frappe.get_doc("WhatsApp Core Handler Run", run_key)
		run.status = "Processing"
		run.started_at = now()
		run.completed_at = None
		run.error = ""
		run.save(ignore_permissions=True)
		return run
	return frappe.get_doc({
		"doctype": "WhatsApp Core Handler Run",
		"run_key": run_key,
		"relay_event": event_id,
		"handler": handler_path,
		"status": "Processing",
		"started_at": now(),
	}).insert(ignore_permissions=True)


def retry_failed_events():
	# Exhausted orphan receipts are recoverable once the outbound provider id is
	# present.  This periodic repair also covers worker crashes between binding
	# the id and enqueueing the immediate wake-up job.
	recoverable = frappe.db.sql(
		"""
		SELECT event.name
		FROM `tabWhatsApp Core Event` event
		INNER JOIN `tabWhatsApp Core Message` message
			ON message.provider_message_id = event.external_id
		WHERE event.status = 'Failed'
		  AND event.event_type LIKE 'status:%'
		  AND event.error = 'Awaiting matching outbound provider result'
		ORDER BY event.modified ASC
		LIMIT 1000
		""",
		pluck=True,
	)
	if recoverable:
		frappe.db.sql(
			"""
			UPDATE `tabWhatsApp Core Event`
			SET status = 'Queued', attempts = 0, error = '', modified = NOW(6)
			WHERE name IN %(event_ids)s
			""",
			{"event_ids": recoverable},
		)
		enqueue_event_batch(recoverable, enqueue_after_commit=True)

	events = frappe.get_all(
		"WhatsApp Core Event",
		filters={
			"status": ["in", ["Pending", "Failed"]],
			"attempts": ["<", MAX_ATTEMPTS],
		},
		pluck="name",
		limit_page_length=200,
	)
	for event_id in events:
		enqueue_event(event_id)
	return len(recoverable) + len(events)
