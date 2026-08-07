import hashlib
import json

import frappe
from frappe.utils import now

from frappe_whatsapp_core.materializer import materialize_event

MAX_ATTEMPTS = 6
MAX_REALTIME_BATCH_SIZE = 100


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


def process_event_batch(event_ids):
	"""Process one committed relay window and notify clients once per batch."""
	if len(event_ids) > MAX_REALTIME_BATCH_SIZE:
		frappe.throw(
			f"Core event batches cannot exceed {MAX_REALTIME_BATCH_SIZE} events",
			frappe.ValidationError,
		)
	results = []
	frappe.flags.whatsapp_core_batch_processing = True
	try:
		for event_id in event_ids:
			try:
				results.append({"event_id": event_id, **process_event(event_id)})
			except Exception:
				results.append({"event_id": event_id, "status": "failed"})
	finally:
		frappe.flags.whatsapp_core_batch_processing = False
	_publish_batch_refresh(event_ids, results)
	return results


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
	message_names = []
	for result in results:
		for projection in result.get("projections") or []:
			if projection.get("kind") in {"message", "status"} and projection.get("name"):
				message_names.append(projection["name"])
	conversations = []
	if message_names:
		conversations = frappe.get_all(
			"WhatsApp Core Message",
			filters={"name": ["in", list(dict.fromkeys(message_names))]},
			pluck="conversation",
		)
	frappe.publish_realtime(
		"whatsapp_core_batch_committed",
		{
			"event_count": len(event_ids),
			"completed": sum(result.get("status") == "completed" for result in results),
			"failed": sum(result.get("status") == "failed" for result in results),
			"conversations": list(dict.fromkeys(conversations)),
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
	return len(events)
