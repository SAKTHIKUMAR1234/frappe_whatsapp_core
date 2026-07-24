import hashlib
import json

import frappe
from frappe.utils import now
from frappe_whatsapp_core.materializer import materialize_event


MAX_ATTEMPTS = 6


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
	frappe.enqueue(
		"frappe_whatsapp_core.dispatcher.process_event_batch",
		queue="short",
		enqueue_after_commit=enqueue_after_commit,
		event_ids=event_ids,
	)


def process_event_batch(event_ids):
	"""Process one persisted relay window sequentially after its DB commit."""
	results = []
	for event_id in event_ids:
		try:
			results.append({"event_id": event_id, **process_event(event_id)})
		except Exception:
			results.append({"event_id": event_id, "status": "failed"})
	return results


def process_event(event_id):
	event = frappe.get_doc("WhatsApp Core Event", event_id)
	if event.status == "Completed":
		return {"status": "completed"}

	event.status = "Processing"
	event.attempts = (event.attempts or 0) + 1
	event.error = ""
	event.save(ignore_permissions=True)
	frappe.db.commit()

	payload = json.loads(event.payload)
	try:
		projections = materialize_event(event, payload)
		handlers = frappe.get_hooks("whatsapp_core_event_handlers") or []
		if not handlers:
			event.status = "Unhandled"
			event.processed_on = now()
			event.save(ignore_permissions=True)
			return {"status": "unhandled", "projections": projections}

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
