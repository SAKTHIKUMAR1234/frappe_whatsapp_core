import hashlib
import json
import random
import time

import frappe
from frappe.utils import add_to_date, now, now_datetime

from frappe_whatsapp_core.materializer import materialize_event
from frappe_whatsapp_core.message_media import enqueue_message_media_cache
from frappe_whatsapp_core.naming import name_by_key
from frappe_whatsapp_core.realtime import (
	publish_batch_notice,
	publish_call_changes,
	publish_message_changes,
)

MAX_ATTEMPTS = 6
MAX_REALTIME_BATCH_SIZE = 100
STATUS_BATCH_DEADLOCK_RETRIES = 10
GENERIC_BATCH_DEADLOCK_RETRIES = 6
WAITING_STATUS_DEADLOCK_RETRIES = 6
ORPHAN_STATUS_RETRY_BASE_SECONDS = 0.25
ORPHAN_STATUS_RETRY_MAX_SECONDS = 2.0
MAX_IMMEDIATE_PROJECTION_BATCH_SIZE = 8


def enqueue_event(event_id, enqueue_after_commit=False, serialization_key=None):
	frappe.enqueue(
		"frappe_whatsapp_core.dispatcher.process_event_batch",
		queue="short",
		enqueue_after_commit=enqueue_after_commit,
		event_ids=[event_id],
		serialization_key=serialization_key,
	)


def enqueue_event_batch(
	event_ids,
	enqueue_after_commit=False,
	serialization_key=None,
):
	if not event_ids:
		return
	unique_ids = list(dict.fromkeys(event_ids))
	for offset in range(0, len(unique_ids), MAX_REALTIME_BATCH_SIZE):
		frappe.enqueue(
			"frappe_whatsapp_core.dispatcher.process_event_batch",
			queue="short",
			enqueue_after_commit=enqueue_after_commit,
			event_ids=unique_ids[offset : offset + MAX_REALTIME_BATCH_SIZE],
			serialization_key=serialization_key,
		)


def enqueue_event_rows_by_lane(event_rows, enqueue_after_commit=False):
	"""Queue events without losing per-conversation ordering on repair paths."""
	status_ids = []
	human_lanes = {}
	for row in event_rows or []:
		event_id = row.get("name")
		if not event_id:
			continue
		if str(row.get("event_type") or "").startswith("status:"):
			status_ids.append(event_id)
			continue
		lane = row.get("conversation_key") or event_id
		human_lanes.setdefault(lane, []).append(event_id)

	for lane, event_ids in human_lanes.items():
		enqueue_event_batch(
			event_ids,
			enqueue_after_commit=enqueue_after_commit,
			serialization_key=lane,
		)
	if status_ids:
		enqueue_event_batch(status_ids, enqueue_after_commit=enqueue_after_commit)


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
	# Frappe job bootstrap may have opened a REPEATABLE READ snapshot before the
	# delay. Reset it after sleeping so the retry can observe a provider-id binding
	# committed by the independent outbound-result callback during that window.
	frappe.db.commit()
	return process_event_batch(event_ids)


def retry_stale_events(limit=1000):
	"""Requeue events abandoned by a worker crash or exhausted DB retry.

	Fresh events are left to their original after-commit job. The conditional
	update prevents a concurrently completed event from being regressed.
	"""
	limit = max(1, min(int(limit or 1000), 5000))
	cutoff = add_to_date(now_datetime(), minutes=-2)
	events = frappe.get_all(
		"WhatsApp Core Event",
		filters={
			"status": ["in", ["Pending", "Queued"]],
			"modified": ["<", cutoff],
		},
		order_by="modified asc",
		fields=["name", "event_type", "conversation_key"],
		limit_page_length=limit,
	)
	if not events:
		return {"requeued": 0}
	event_ids = [row.name for row in events]
	frappe.db.sql(
		"""
		UPDATE `tabWhatsApp Core Event`
		SET status = 'Queued', modified = NOW(6)
		WHERE name IN %(event_ids)s
		  AND status IN ('Pending', 'Queued')
		""",
		{"event_ids": event_ids},
	)
	enqueue_event_rows_by_lane(events, enqueue_after_commit=True)
	return {"requeued": len(event_ids)}


def enqueue_waiting_status_events(provider_ids, enqueue_after_commit=True):
	"""Wake receipts that arrived before their outbound provider ID was bound."""
	provider_ids = _normalized_provider_ids(provider_ids)
	if not provider_ids:
		return 0
	if enqueue_after_commit:
		# A status worker may be updating the orphan event while this request is
		# binding the outbound provider ID. Keeping both writes in the request
		# transaction can trigger MyRocks CHECKREAD (1020) and roll back an
		# otherwise valid provider result. Wake the event in a fresh transaction.
		frappe.enqueue(
			"frappe_whatsapp_core.dispatcher.wake_waiting_status_events",
			queue="short",
			enqueue_after_commit=True,
			provider_ids=provider_ids,
		)
		return 0
	return wake_waiting_status_events(provider_ids)


def wake_waiting_status_events(provider_ids):
	"""Wake orphan receipts in their own retryable database transaction."""
	provider_ids = _normalized_provider_ids(provider_ids)
	if not provider_ids:
		return 0
	for attempt in range(WAITING_STATUS_DEADLOCK_RETRIES):
		try:
			return _wake_waiting_status_events(provider_ids)
		except frappe.QueryDeadlockError:
			frappe.db.rollback()
			if attempt == WAITING_STATUS_DEADLOCK_RETRIES - 1:
				raise
			time.sleep(min(1.0, 0.05 * (2**attempt)) + random.uniform(0, 0.03))


def _wake_waiting_status_events(provider_ids):
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
	# Do not mutate the event in this wake-up transaction. The status batch owns
	# the event row and can process a recoverable Failed event directly. Writing
	# here races that batch, causes MyRocks CHECKREAD retries, and needlessly holds
	# a short-queue worker for several seconds under campaign load.
	enqueue_event_batch(event_ids, enqueue_after_commit=True)
	return len(event_ids)


def _normalized_provider_ids(provider_ids):
	return list(
		dict.fromkeys(
			str(provider_id).strip() for provider_id in provider_ids or [] if str(provider_id or "").strip()
		)
	)


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


def process_event_batch(event_ids, retry_deadlocks=True, serialization_key=None):
	"""Process one committed relay window and notify clients once per batch."""
	if serialization_key:
		lock_key = hashlib.sha256(str(serialization_key).encode()).hexdigest()
		with frappe.cache.lock(
			f"whatsapp_core_projection:{lock_key}",
			timeout=600,
			blocking_timeout=240,
		):
			# Job bootstrap may already have opened a REPEATABLE READ snapshot.
			# Reset it only after owning the conversation lane so rows committed by
			# the previous batch are visible before create-or-reuse projection.
			frappe.db.commit()
			return _process_event_batch(event_ids, retry_deadlocks)
	return _process_event_batch(event_ids, retry_deadlocks)


def project_realtime_event_batch(event_ids):
	"""Materialize a small human-visible ingress window before worker dispatch.

	This deliberately leaves Core Events pending.  The ordered worker still owns
	automation, business hooks, retries and terminal event state; this fast path
	only makes the durable inbox projection available to Socket.IO clients without
	waiting behind those comparatively expensive handlers.
	"""
	event_ids = list(dict.fromkeys(event_ids or []))
	if not event_ids:
		return []
	if len(event_ids) > MAX_IMMEDIATE_PROJECTION_BATCH_SIZE:
		frappe.throw(
			f"Immediate projection cannot exceed {MAX_IMMEDIATE_PROJECTION_BATCH_SIZE} events",
			frappe.ValidationError,
		)
	events = frappe.get_all(
		"WhatsApp Core Event",
		filters={"name": ["in", event_ids]},
		fields=["name", "event_id", "event_type", "channel_key", "external_id", "conversation_key", "payload"],
		limit_page_length=len(event_ids),
	)
	event_map = {event.name: event for event in events}
	results = []
	projection_cache = {}
	for event_id in event_ids:
		event = event_map.get(event_id)
		if not event:
			results.append({"event_id": event_id, "status": "missing", "projections": []})
			continue
		projections = materialize_event(
			event,
			json.loads(event.payload),
			projection_cache=projection_cache,
		)
		results.append({"event_id": event_id, "status": "projected", "projections": projections})

	created_message_names = list(dict.fromkeys(
		projection.get("name")
		for result in results
		for projection in result.get("projections") or []
		if projection.get("kind") == "message"
		and projection.get("status") == "created"
		and projection.get("name")
	))
	if created_message_names:
		from frappe_whatsapp_core.ai_summaries import enqueue_summary_for_messages

		enqueue_summary_for_messages(created_message_names, enqueue_after_commit=True)
		media_messages = frappe.get_all(
			"WhatsApp Core Message",
			filters={
				"name": ["in", created_message_names],
				"message_type": ["in", ["audio", "document", "image", "sticker", "template", "video"]],
			},
			pluck="name",
			limit_page_length=len(created_message_names),
		)
		if media_messages:
			enqueue_message_media_cache(media_messages, enqueue_after_commit=True)
	_publish_batch_refresh(event_ids, results)
	return results


def _process_event_batch(event_ids, retry_deadlocks=True):
	if len(event_ids) > MAX_REALTIME_BATCH_SIZE:
		frappe.throw(
			f"Core event batches cannot exceed {MAX_REALTIME_BATCH_SIZE} events",
			frappe.ValidationError,
		)
	event_ids = list(dict.fromkeys(event_ids))
	if _is_pure_status_batch(event_ids):
		return _process_status_event_batch_with_retry(event_ids)
	if not retry_deadlocks:
		return _process_generic_event_batch(event_ids)
	for attempt in range(GENERIC_BATCH_DEADLOCK_RETRIES):
		try:
			return _process_generic_event_batch(event_ids)
		except frappe.QueryDeadlockError:
			frappe.db.rollback()
			if attempt == GENERIC_BATCH_DEADLOCK_RETRIES - 1:
				raise
			time.sleep(min(1.5, 0.08 * (2**attempt)) + random.uniform(0, 0.04))


def _process_generic_event_batch(event_ids):
	"""Process non-status work as one retryable database transaction."""
	results = []
	projection_cache = {}
	frappe.flags.whatsapp_core_batch_processing = True
	frappe.flags.whatsapp_core_campaign_message_names = set()
	try:
		for event_id in event_ids:
			try:
				results.append(
					{
						"event_id": event_id,
						**process_event(event_id, projection_cache=projection_cache),
					}
				)
			except frappe.QueryDeadlockError:
				# A deadlock invalidates every earlier savepoint/write in this
				# transaction, so the complete committed batch must be replayed.
				raise
			except Exception:
				results.append({"event_id": event_id, "status": "failed"})
	finally:
		frappe.flags.whatsapp_core_batch_processing = False
	message_names = list(frappe.flags.whatsapp_core_campaign_message_names or [])
	frappe.flags.whatsapp_core_campaign_message_names = set()
	if message_names:
		from frappe_whatsapp_core.campaigns import refresh_campaigns_for_messages

		refresh_campaigns_for_messages(message_names)
	created_message_names = list(
		dict.fromkeys(
			projection["name"]
			for result in results
			for projection in result.get("projections") or []
			if projection.get("kind") == "message"
			and projection.get("status") == "created"
			and projection.get("name")
		)
	)
	if created_message_names:
		# Classification/summarization is intentionally off the webhook
		# transaction. One deduplicated long-queue job is scheduled per affected
		# contact after the complete event batch commits; the periodic scan remains
		# a repair path for crashed workers or temporarily disabled AI.
		from frappe_whatsapp_core.ai_summaries import enqueue_summary_for_messages

		enqueue_summary_for_messages(
			created_message_names,
			enqueue_after_commit=True,
		)
	_publish_batch_refresh(event_ids, results)
	return results


def _process_status_event_batch_with_retry(event_ids):
	"""Retry the whole status transaction after a transient DB conflict.

	MariaDB rolls back the complete transaction on a deadlock, including every
	savepoint. A concurrent identity enrichment can likewise invalidate Frappe's
	optimistic Document timestamp. Retrying an individual row would therefore
	mark earlier rows as completed even though their projections were rolled back.
	"""
	for attempt in range(STATUS_BATCH_DEADLOCK_RETRIES):
		try:
			return _process_status_event_batch(event_ids)
		except (frappe.QueryDeadlockError, frappe.TimestampMismatchError):
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
	events = _get_locked_core_event_rows(event_ids)
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
					results.append(
						{
							"event_id": event_id,
							"status": "deferred",
							"projections": projections,
						}
					)
					continue
				completed.append(event_id)
				results.append(
					{
						"event_id": event_id,
						"status": "completed",
						"projections": projections,
					}
				)
			except (frappe.QueryDeadlockError, frappe.TimestampMismatchError):
				# A deadlock invalidates every savepoint in the transaction. A stale
				# identity Document also needs a fresh committed snapshot. Let the
				# outer retry restart the complete batch in both cases.
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
			event_id for event_id in deferred if int(by_name[event_id].attempts or 0) + 1 < MAX_ATTEMPTS
		]
		if retry_ids:
			attempt = max(int(by_name[event_id].attempts or 0) + 1 for event_id in retry_ids)
			enqueue_orphan_status_retry(retry_ids, attempt=attempt)
	for event_id, error in failed:
		next_attempt = int(by_name[event_id].attempts or 0) + 1
		frappe.db.set_value(
			"WhatsApp Core Event",
			event_id,
			{"status": "Failed", "error": error, "attempts": next_attempt},
			update_modified=False,
		)

	message_names = list(frappe.flags.whatsapp_core_campaign_message_names or [])
	frappe.flags.whatsapp_core_campaign_message_names = set()
	if message_names:
		from frappe_whatsapp_core.campaigns import reconcile_campaign_status_batch

		reconcile_campaign_status_batch(message_names)
	_publish_batch_refresh(event_ids, results)
	return results


def _get_locked_core_event_rows(event_ids):
	"""Load current event state while serializing duplicate status batches."""
	event_ids = sorted(set(event_ids or []))
	if not event_ids:
		return []
	return frappe.db.sql(
		"""
		SELECT name, payload, status, attempts
		FROM `tabWhatsApp Core Event`
		WHERE name IN %(event_ids)s
		ORDER BY name
		FOR UPDATE
		""",
		{"event_ids": event_ids},
		as_dict=True,
	)


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
	message_names = sorted(
		frappe.get_all(
			"WhatsApp Core Message",
			filters={"provider_message_id": ["in", provider_ids]},
			pluck="name",
			limit_page_length=len(provider_ids),
		)
	)
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


def process_event(event_id, projection_cache=None):
	event = frappe.get_doc("WhatsApp Core Event", event_id)
	if event.status == "Completed":
		return {"status": "completed"}

	event.status = "Processing"
	event.attempts = (event.attempts or 0) + 1
	event.error = ""
	event.save(ignore_permissions=True)

	payload = json.loads(event.payload)
	try:
		projections = materialize_event(
			event,
			payload,
			projection_cache=projection_cache,
		)
		if _has_orphan_status(projections):
			event.status = "Pending" if event.attempts < MAX_ATTEMPTS else "Failed"
			event.error = "Awaiting matching outbound provider result"
			event.save(ignore_permissions=True)
			if event.status == "Pending":
				enqueue_orphan_status_retry([event.name], attempt=event.attempts)
			return {"status": "deferred", "projections": projections, "results": []}
		projected_messages = [
			projection["name"]
			for projection in projections
			if projection.get("kind") == "message" and projection.get("name")
		]
		media_messages = (
			frappe.get_all(
				"WhatsApp Core Message",
				filters={
					"name": ["in", projected_messages],
					"message_type": ["in", ["audio", "document", "image", "sticker", "template", "video"]],
				},
				pluck="name",
				limit_page_length=len(projected_messages),
			)
			if projected_messages
			else []
		)
		if media_messages:
			enqueue_message_media_cache(media_messages, enqueue_after_commit=True)
		handlers = [
			"frappe_whatsapp_core.core_event_handler.handle_core_event",
			*(frappe.get_hooks("whatsapp_core_event_handlers") or []),
		]

		results = []
		for handler_path in handlers:
			run_key = hashlib.sha256(f"{event.name}:{handler_path}:v1".encode()).hexdigest()
			if frappe.db.get_value(
				"WhatsApp Core Handler Run",
				{"relay_event": event.name, "handler": handler_path, "status": "Completed"},
				"name",
			) or name_by_key("WhatsApp Core Handler Run", run_key, filters={"status": "Completed"}):
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
	except frappe.QueryDeadlockError:
		# Do not attempt another stale Document save after MariaDB has rolled
		# back the transaction. The batch owner handles the bounded retry.
		raise
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
	"""Publish one permission-scoped delta per affected operator after commit."""
	projections = [
		projection
		for result in results or []
		for projection in result.get("projections") or []
		if isinstance(projection, dict) and projection.get("status") != "duplicate"
	]
	publish_message_changes(projections)
	publish_call_changes(
		[projection.get("name") for projection in projections if projection.get("kind") == "call"]
	)
	publish_batch_notice([projection.get("kind") for projection in projections])


def _start_handler_run(run_key, event_id, handler_path):
	run_name = frappe.db.get_value(
		"WhatsApp Core Handler Run",
		{"relay_event": event_id, "handler": handler_path},
		"name",
	) or name_by_key("WhatsApp Core Handler Run", run_key)
	if run_name:
		run = frappe.get_doc("WhatsApp Core Handler Run", run_name)
		run.status = "Processing"
		run.started_at = now()
		run.completed_at = None
		run.error = ""
		run.save(ignore_permissions=True)
		return run
	return frappe.get_doc(
		{
			"doctype": "WhatsApp Core Handler Run",
			"run_key": run_key,
			"relay_event": event_id,
			"handler": handler_path,
			"status": "Processing",
			"started_at": now(),
		}
	).insert(ignore_permissions=True)


def retry_failed_events():
	# Exhausted orphan receipts are recoverable once the outbound provider id is
	# present. Status projections that exhausted their attempts on a transient
	# optimistic-lock collision are recoverable as well. This periodic repair
	# covers deployments made after either failure was already persisted.
	recoverable = frappe.db.sql(
		"""
		SELECT event.name
		FROM `tabWhatsApp Core Event` event
		INNER JOIN `tabWhatsApp Core Message` message
			ON message.provider_message_id = event.external_id
		WHERE event.status = 'Failed'
		  AND event.event_type LIKE 'status:%'
		  AND (
			event.error = 'Awaiting matching outbound provider result'
			OR event.error LIKE '%TimestampMismatchError%'
			OR event.error LIKE '%Document has been modified after you have opened it%'
		  )
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
			# Pending/Queued rows still belong to their original batch or the
			# two-minute stale-event repair. Re-enqueueing them here creates a
			# second owner and races the first worker on MyRocks.
			"status": "Failed",
			"attempts": ["<", MAX_ATTEMPTS],
		},
		fields=["name", "event_type", "conversation_key"],
		limit_page_length=200,
	)
	recoverable_set = set(recoverable)
	failed_rows = [row for row in events if row.name not in recoverable_set]
	failed = [row.name for row in failed_rows]
	if failed:
		enqueue_event_rows_by_lane(failed_rows, enqueue_after_commit=True)
	return len(set(recoverable) | set(failed))
