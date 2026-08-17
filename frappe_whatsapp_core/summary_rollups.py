"""Bounded daily → weekly → monthly → yearly WhatsApp context summaries."""

from __future__ import annotations

from datetime import date, timedelta
import hashlib
import json

import frappe
from frappe.utils import cint, getdate, now_datetime, nowdate
from redis.exceptions import LockError

from frappe_whatsapp_core.message_categories import categories_for_messages
from frappe_whatsapp_core.naming import name_by_key
from frappe_whatsapp_core.permissions import assert_identity_team_access

PERIODS = ("Daily", "Weekly", "Monthly", "Yearly")
RETENTION_DAYS = {"Daily": 7, "Weekly": 31, "Monthly": 366}


def enqueue_summary_rollup(identity: str, *, enqueue_after_commit: bool = True) -> None:
	if not _enabled():
		return
	frappe.enqueue(
		"frappe_whatsapp_core.summary_rollups.refresh_identity_rollups",
		queue="long",
		enqueue_after_commit=enqueue_after_commit,
		job_id=_job_id(identity),
		deduplicate=True,
		identity=identity,
	)


def queue_summary_rollups(limit: int = 100) -> dict:
	"""Queue active contacts; deduplication makes this safe every thirty minutes."""
	if not _enabled():
		return {"queued": 0, "disabled": True}
	identities = frappe.get_all(
		"WhatsApp Core Message Insight",
		filters={"status": "Ready"},
		pluck="identity",
		distinct=True,
		order_by="modified desc",
		limit_page_length=max(1, min(cint(limit) or 100, 500)),
	)
	for identity in identities:
		enqueue_summary_rollup(identity, enqueue_after_commit=False)
	return {"queued": len(identities), "disabled": False}


def refresh_identity_rollups(identity: str, reference_date: str | date | None = None) -> dict:
	if not frappe.db.exists("WhatsApp Core Identity", identity):
		frappe.throw("Contact not found", frappe.DoesNotExistError)
	if not _enabled():
		return {"identity": identity, "disabled": True, "periods": []}
	day = getdate(reference_date or nowdate())
	try:
		with frappe.cache.lock(
			f"whatsapp_core_summary_rollup:{identity}", timeout=300, blocking_timeout=2
		):
			results = []
			for period_type in PERIODS:
				start, end = _period_bounds(period_type, day)
				result = _refresh_period(identity, period_type, start, end)
				if result:
					results.append(result)
			prune_summary_rollups(day)
			return {"identity": identity, "disabled": False, "periods": results}
	except LockError:
		return {"identity": identity, "refresh_in_progress": True, "periods": []}


def get_summary_context(identity: str, reference_date: str | date | None = None) -> dict:
	"""Return small retained context instead of rescanning a contact's raw history."""
	if not frappe.db.exists("WhatsApp Core Identity", identity):
		frappe.throw("Contact not found", frappe.DoesNotExistError)
	assert_identity_team_access(identity)
	day = getdate(reference_date or nowdate())
	rows = frappe.get_all(
		"WhatsApp Core Summary Period",
		filters={
			"identity": identity,
			"status": "Ready",
			"period_end": [">=", day - timedelta(days=366)],
		},
		fields=[
			"name", "period_type", "period_start", "period_end", "summary",
			"categories", "action_items", "risks", "language", "confidence",
			"source_count", "message_count", "generated_at",
		],
		order_by="period_start desc",
		limit_page_length=430,
	)
	for row in rows:
		for key in ("categories", "action_items", "risks"):
			row[key] = _json_list(row.get(key))
	return {"identity": identity, "layers": rows}


def prune_summary_rollups(reference_date: str | date | None = None) -> dict:
	day = getdate(reference_date or nowdate())
	removed = {}
	for period_type, days in RETENTION_DAYS.items():
		cutoff = day - timedelta(days=days)
		rows = frappe.get_all(
			"WhatsApp Core Summary Period",
			filters={"period_type": period_type, "period_end": ["<", cutoff]},
			pluck="name",
			limit_page_length=10000,
		)
		for name in rows:
			frappe.delete_doc(
				"WhatsApp Core Summary Period",
				name,
				ignore_permissions=True,
				delete_permanently=True,
			)
		removed[period_type] = len(rows)
	return removed


def _refresh_period(identity: str, period_type: str, start: date, end: date) -> dict | None:
	sources = _period_sources(identity, period_type, start, end)
	if not sources:
		return None
	key = hashlib.sha256(f"{identity}:{period_type}:{start.isoformat()}".encode()).hexdigest()
	record_name = frappe.db.get_value(
		"WhatsApp Core Summary Period",
		{"identity": identity, "period_type": period_type, "period_start": start},
		"name",
	) or name_by_key("WhatsApp Core Summary Period", key)
	doc = (
		frappe.get_doc("WhatsApp Core Summary Period", record_name)
		if record_name
		else frappe.get_doc({
			"doctype": "WhatsApp Core Summary Period",
			"summary_key": key,
			"identity": identity,
			"period_type": period_type,
			"period_start": start,
			"period_end": end - timedelta(days=1),
		})
	)
	latest_source = max(str(row.get("source_modified") or "") for row in sources)
	if doc.generated_at and str(doc.generated_at) >= latest_source and doc.status == "Ready":
		return _doc_dict(doc)
	settings = frappe.get_single("WhatsApp Core Settings")
	action = settings.summary_rollup_i2a_action
	try:
		model_result = _run_i2a(action, period_type, start, end, sources)
		data = _model_data(model_result)
		categories = _merge_unique(
			[row for source in sources for row in _json_list(source.get("categories"))],
			data.get("categories"),
		)
		doc.status = "Ready" if str(data.get("summary") or "").strip() else "Needs Review"
		doc.summary = str(data.get("summary") or "")[:12000]
		doc.categories = _json_value(categories)
		doc.action_items = _json_value(data.get("action_items"))
		doc.risks = _json_value(data.get("risks"))
		doc.language = str(data.get("language") or "")[:140]
		doc.confidence = _confidence(data.get("confidence"))
		doc.source_count = len(sources)
		doc.message_count = sum(cint(row.get("message_count")) for row in sources)
		doc.ai_action = action
		doc.ai_model = str(model_result.get("model") or "")[:140]
		doc.generated_at = now_datetime()
		doc.error = "" if doc.status == "Ready" else "Model returned no period summary"
	except Exception as exc:
		doc.status = "Failed"
		doc.generated_at = now_datetime()
		doc.error = str(exc)[:500]
		if doc.is_new():
			doc.insert(ignore_permissions=True)
		else:
			doc.save(ignore_permissions=True)
		raise
	if doc.is_new():
		doc.insert(ignore_permissions=True)
	else:
		doc.save(ignore_permissions=True)
	return _doc_dict(doc)


def _period_sources(identity: str, period_type: str, start: date, end: date) -> list[dict]:
	if period_type == "Daily":
		rows = frappe.db.sql(
			"""
			SELECT insight.message, insight.message_summary AS summary, insight.action_items,
				insight.risks, insight.language, insight.confidence,
				message.provider_timestamp, insight.modified AS source_modified
			FROM `tabWhatsApp Core Message Insight` insight
			JOIN `tabWhatsApp Core Message` message ON message.name = insight.message
			WHERE insight.identity = %(identity)s AND insight.status = 'Ready'
				AND message.provider_timestamp >= %(start)s
				AND message.provider_timestamp < %(end)s
			ORDER BY message.provider_timestamp ASC, message.creation ASC
			""",
			{"identity": identity, "start": start, "end": end},
			as_dict=True,
		)
		category_map = categories_for_messages([row.message for row in rows])
		for row in rows:
			row.categories = category_map.get(row.message, [])
			row.message_count = 1
		return rows
	source_type = {"Weekly": "Daily", "Monthly": "Weekly", "Yearly": "Monthly"}[period_type]
	return frappe.db.sql(
		"""
		SELECT summary, categories, action_items, risks, language, confidence,
			message_count, modified AS source_modified
		FROM `tabWhatsApp Core Summary Period`
		WHERE identity = %(identity)s AND period_type = %(source_type)s
			AND status = 'Ready' AND period_start >= %(start)s AND period_start < %(end)s
		ORDER BY period_start ASC
		LIMIT 400
		""",
		{"identity": identity, "source_type": source_type, "start": start, "end": end},
		as_dict=True,
	)


def _run_i2a(action: str, period_type: str, start: date, end: date, sources: list[dict]) -> dict:
	from frappe_tools.i2a.intents import run_intent

	prompt = json.dumps({
		"task": f"Build the {period_type.lower()} WhatsApp context summary.",
		"period_start": start.isoformat(),
		"period_end_exclusive": end.isoformat(),
		"sources": [
			{
				"summary": row.get("summary") or "",
				"categories": _json_list(row.get("categories")),
				"action_items": _json_list(row.get("action_items")),
				"risks": _json_list(row.get("risks")),
				"language": row.get("language") or "",
				"confidence": row.get("confidence") or 0,
				"message_count": cint(row.get("message_count")),
			}
			for row in sources
		],
		"required_output": {
			"summary": "concise evidence-bound period summary",
			"categories": ["category"],
			"action_items": ["still-open action"],
			"risks": ["risk or uncertainty"],
			"confidence": "0 to 100",
			"language": "primary language",
		},
	}, ensure_ascii=False)
	return run_intent(action, prompt)


def _period_bounds(period_type: str, day: date) -> tuple[date, date]:
	if period_type == "Daily":
		return day, day + timedelta(days=1)
	if period_type == "Weekly":
		start = day - timedelta(days=day.weekday())
		return start, start + timedelta(days=7)
	if period_type == "Monthly":
		start = day.replace(day=1)
		end = date(start.year + (start.month == 12), 1 if start.month == 12 else start.month + 1, 1)
		return start, end
	if period_type == "Yearly":
		return date(day.year, 1, 1), date(day.year + 1, 1, 1)
	frappe.throw("Unsupported summary period", frappe.ValidationError)


def _enabled() -> bool:
	settings = frappe.get_single("WhatsApp Core Settings")
	return bool(
		cint(settings.enable_ai_summaries)
		and str(settings.summary_rollup_i2a_action or "").strip()
		and "frappe_tools" in frappe.get_installed_apps()
	)


def _model_data(result) -> dict:
	if not isinstance(result, dict):
		return {}
	data = result.get("data")
	if isinstance(data, dict):
		return data
	if isinstance(data, list):
		return next((row for row in data if isinstance(row, dict)), {})
	return {}


def _doc_dict(doc) -> dict:
	result = doc.as_dict()
	for key in ("categories", "action_items", "risks"):
		result[key] = _json_list(result.get(key))
	return result


def _json_list(value) -> list:
	if isinstance(value, list):
		return value
	if not value:
		return []
	try:
		parsed = json.loads(value)
		return parsed if isinstance(parsed, list) else []
	except (TypeError, ValueError):
		return []


def _json_value(value) -> str:
	return json.dumps(value if isinstance(value, list) else [], ensure_ascii=False, separators=(",", ":"))


def _merge_unique(*values) -> list:
	result = []
	for value in values:
		for item in _json_list(value) if not isinstance(value, list) else value:
			text = str(item or "").strip()
			if text and text not in result:
				result.append(text)
	return result


def _confidence(value) -> float:
	try:
		return max(0, min(float(value or 0), 100))
	except (TypeError, ValueError):
		return 0


def _job_id(identity: str) -> str:
	return "whatsapp-summary-rollup-" + hashlib.sha256(identity.encode()).hexdigest()[:20]
