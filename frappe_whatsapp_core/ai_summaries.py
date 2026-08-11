"""Incremental, auditable multimodal summaries for WhatsApp contacts.

Core owns message cursors and summary records. Frappe Tools owns model
credentials, provider transport, cost accounting, and I2A Action prompts.
Company apps may aggregate these summaries but never need raw message history.
"""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

import frappe
from frappe.utils import cint, now_datetime
from redis.exceptions import LockError

from frappe_whatsapp_core.message_categories import (
	categories_for_messages,
	ensure_message_category,
	normalize_message_categories,
	set_message_categories,
)
from frappe_whatsapp_core.message_media import cache_message_media, media_descriptor
from frappe_whatsapp_core.permissions import assert_identity_team_access

MEDIA_TYPES = {"audio", "document", "image", "sticker", "video"}
DEFAULT_BATCH_SIZE = 100
MAX_BATCHES_PER_JOB = 20


def get_identity_summary(identity: str) -> dict:
	identity = _valid_identity(identity)
	assert_identity_team_access(identity)
	name = _summary_name("Identity", identity)
	return _summary_dict(frappe.get_doc("WhatsApp Core Contact Summary", name)) if frappe.db.exists(
		"WhatsApp Core Contact Summary", name
	) else {}


def get_group_summary(scope_key: str, identities: list[str]) -> dict:
	"""Read a cached aggregate after validating access to every source contact."""
	scope_key = str(scope_key or "").strip()
	if not scope_key:
		frappe.throw("Summary scope is required", frappe.ValidationError)
	identities = list(dict.fromkeys(_valid_identity(value) for value in identities or []))
	if not identities:
		frappe.throw("Select at least one contact", frappe.ValidationError)
	for identity in identities:
		assert_identity_team_access(identity)
	name = _summary_name("Group", scope_key)
	if not frappe.db.exists("WhatsApp Core Contact Summary", name):
		return {}
	summary = frappe.get_doc("WhatsApp Core Contact Summary", name)
	stored_identities = set(_json_list(summary.source_identities))
	if stored_identities and stored_identities != set(identities):
		return {}
	return _summary_dict(summary)


def attach_message_insights(messages) -> None:
	"""Attach compact, permission-neutral insights to already scoped messages."""
	names = [str(row.get("name") or "") for row in messages or [] if row.get("name")]
	if not names:
		return
	rows = frappe.get_all(
		"WhatsApp Core Message Insight",
		filters={"message": ["in", names]},
		fields=[
			"message", "status", "category", "primary_intent", "confidence",
			"transcript", "media_summary", "message_summary", "intents",
			"action_items", "risks", "language", "analyzed_at",
		],
		limit_page_length=len(names),
	)
	by_message = {row.message: row for row in rows}
	category_map = categories_for_messages(names)
	for message in messages:
		insight = by_message.get(message.get("name"))
		if not insight:
			continue
		# ``frappe._dict`` returns ``None`` for any missing attribute, so
		# ``hasattr(row, "as_dict")`` is true even though it is not callable.
		# Query rows are mapping-like; only call ``as_dict`` when an actual
		# document/row implementation provides a callable serializer.
		serializer = getattr(insight, "as_dict", None)
		payload = serializer() if callable(serializer) else dict(insight)
		for key in ("intents", "action_items", "risks"):
			payload[key] = _json_list(payload.get(key))
		payload["categories"] = category_map.get(message.get("name")) or normalize_message_categories(
			payload.get("category")
		)
		message["ai_insight"] = payload


def summarize_identity(identity: str, force: bool = False) -> dict:
	identity = _valid_identity(identity)
	assert_identity_team_access(identity)
	settings = _settings()
	_action_or_throw(settings)
	try:
		with frappe.cache.lock(
			f"whatsapp_core_summary:{identity}", timeout=300, blocking_timeout=2
		):
			summary = _get_or_create_summary("Identity", identity, [identity])
			if force:
				_reset_summary(summary)
			batch_size = _batch_size(settings)
			for _batch_number in range(MAX_BATCHES_PER_JOB):
				messages = _identity_messages(identity, summary, batch_size)
				if not messages:
					break
				try:
					model_result = _run_i2a(
						settings,
						_build_identity_prompt(summary, messages),
						_media_parts(messages, settings),
					)
					data = _model_data(model_result)
					_upsert_message_insights(identity, messages, data, settings, model_result)
					_update_summary(summary, messages, data, settings, model_result)
				except Exception as exc:
					summary.status = "Failed"
					summary.error = str(exc)[:500]
					summary.last_generated_at = now_datetime()
					summary.save(ignore_permissions=True)
					raise
				if len(messages) < batch_size:
					break
		from frappe_whatsapp_core.summary_rollups import enqueue_summary_rollup

		enqueue_summary_rollup(identity, enqueue_after_commit=True)
		return _summary_dict(summary)
	except LockError:
		# A webhook-triggered worker may already be updating this contact. The
		# operator overview must remain readable instead of exposing Redis lock
		# internals. Its next refresh will see the worker's committed cursor.
		return _identity_summary_in_progress(identity)


def summarize_identities(
	identities: list[str], scope_key: str | None = None, force: bool = False
) -> dict:
	identities = list(dict.fromkeys(_valid_identity(value) for value in identities or []))
	if not identities:
		frappe.throw("Select at least one contact", frappe.ValidationError)
	for identity in identities:
		assert_identity_team_access(identity)
	settings = _settings()
	_action_or_throw(settings)
	# Bring each source summary to its current cursor before aggregating it.
	# A current contact is a cheap no-op; a stale one consumes only new messages.
	scope_key = str(scope_key or _group_scope_key(identities)).strip()
	source_results = [summarize_identity(identity, force=force) for identity in identities]
	if any(row.get("refresh_in_progress") for row in source_results):
		return _group_summary_in_progress(scope_key, identities)
	contact_summaries = [get_identity_summary(identity) for identity in identities]
	contact_summaries = [row for row in contact_summaries if row.get("summary")]
	if not contact_summaries:
		frappe.throw("No contact summaries are available", frappe.ValidationError)
	summary = _get_or_create_summary("Group", scope_key, identities)
	if force:
		_reset_summary(summary)
	latest_source = max(str(row.get("last_generated_at") or "") for row in contact_summaries)
	if not force and summary.last_generated_at and str(summary.last_generated_at) >= latest_source:
		return _summary_dict(summary)
	prompt = {
		"task": "Merge contact summaries into one evidence-bound management overview.",
		"previous_group_summary": summary.summary or "",
		"contacts": [
			{
				"contact_ref": f"C{index}",
				"summary": row.get("summary") or "",
				"primary_intent": row.get("primary_intent") or "",
				"categories": _json_list(row.get("categories")),
				"action_items": _json_list(row.get("action_items")),
				"risks": _json_list(row.get("risks")),
				"confidence": row.get("confidence") or 0,
			}
			for index, row in enumerate(contact_summaries, 1)
		],
		"required_output": _required_output(include_message_insights=False),
	}
	model_result = _run_i2a(settings, json.dumps(prompt, ensure_ascii=False), [])
	data = _model_data(model_result)
	# Group categories are a deterministic union of the scoped contact
	# categories. The model may add a useful roll-up category but cannot erase
	# source evidence while compressing the management summary.
	data["categories"] = _merge_unique(
		[
			category
			for row in contact_summaries
			for category in _json_list(row.get("categories"))
		],
		data.get("categories"),
	)
	summary.source_identities = json.dumps(identities, separators=(",", ":"))
	summary.identity_count = len(identities)
	summary.message_count = sum(cint(row.get("message_count")) for row in contact_summaries)
	summary.processed_message_count = sum(
		cint(row.get("processed_message_count")) for row in contact_summaries
	)
	_apply_summary_result(summary, data, settings, model_result)
	summary.save(ignore_permissions=True)
	return _summary_dict(summary)


def enqueue_summary_for_messages(message_names, *, enqueue_after_commit=True) -> None:
	settings = _settings()
	if not cint(settings.enable_ai_summaries) or not settings.summary_i2a_action:
		return
	names = list(dict.fromkeys(str(name) for name in (message_names or []) if name))
	if not names:
		return
	identities = frappe.db.sql(
		"""
		SELECT DISTINCT conversation.remote_identity
		FROM `tabWhatsApp Core Message` AS message
		JOIN `tabWhatsApp Core Conversation` AS conversation
			ON conversation.name = message.conversation
		WHERE message.name IN %(messages)s
		""",
		{"messages": tuple(names)},
		pluck=True,
	)
	for identity in identities:
		frappe.enqueue(
			"frappe_whatsapp_core.ai_summaries.summarize_identity",
			queue="long",
			enqueue_after_commit=enqueue_after_commit,
			job_id=_summary_job_id(identity),
			deduplicate=True,
			identity=identity,
		)


def queue_pending_summaries(limit: int = 100) -> dict:
	settings = _settings()
	if not cint(settings.enable_ai_summaries) or not settings.summary_i2a_action:
		return {"queued": 0, "disabled": True}
	identities = frappe.db.sql(
		"""
		SELECT conversation.remote_identity
		FROM `tabWhatsApp Core Conversation` AS conversation
		JOIN `tabWhatsApp Core Message` AS message ON message.conversation = conversation.name
		LEFT JOIN `tabWhatsApp Core Contact Summary` AS summary
			ON summary.scope_type = 'Identity' AND summary.identity = conversation.remote_identity
		GROUP BY conversation.remote_identity, summary.last_message_at, summary.last_message_creation
		HAVING MAX(message.provider_timestamp) > COALESCE(summary.last_message_at, '1900-01-01')
			OR (
				MAX(message.provider_timestamp) = COALESCE(summary.last_message_at, '1900-01-01')
				AND MAX(message.creation) > COALESCE(summary.last_message_creation, '1900-01-01')
			)
		LIMIT %(limit)s
		""",
		{"limit": max(1, min(cint(limit) or 100, 500))},
		pluck=True,
	)
	for identity in identities:
		frappe.enqueue(
			"frappe_whatsapp_core.ai_summaries.summarize_identity",
			queue="long",
			job_id=_summary_job_id(identity),
			deduplicate=True,
			identity=identity,
		)
	return {"queued": len(identities), "disabled": False}


def _identity_messages(identity: str, summary, limit: int) -> list[dict]:
	values = {"identity": identity, "limit": limit}
	cursor = ""
	if summary.last_message_at and summary.last_message_creation:
		values.update({
			"last_at": summary.last_message_at,
			"last_creation": summary.last_message_creation,
		})
		cursor = """
			AND (
				message.provider_timestamp > %(last_at)s
				OR (
					message.provider_timestamp = %(last_at)s
					AND message.creation > %(last_creation)s
				)
			)
		"""
	return frappe.db.sql(
		f"""
		SELECT
			message.name, message.conversation, message.direction,
			message.message_type, message.body, message.content,
			message.provider_timestamp, message.creation
		FROM `tabWhatsApp Core Message` AS message
		JOIN `tabWhatsApp Core Conversation` AS conversation
			ON conversation.name = message.conversation
		WHERE conversation.remote_identity = %(identity)s
			AND message.delivery_status != 'Deleted'
			AND message.message_type != 'reaction'
			{cursor}
		ORDER BY message.provider_timestamp ASC, message.creation ASC
		LIMIT %(limit)s
		""",
		values,
		as_dict=True,
	)


def _build_identity_prompt(summary, messages: list[dict]) -> str:
	return json.dumps({
		"task": (
			"Classify every new WhatsApp message and update the contact overview only "
			"when the evidence is operationally actionable. Ordinary two-way or social "
			"chat must keep summary empty. "
			"Transcribe voice notes, describe relevant image/document evidence, "
			"classify each message, preserve who alleged what, and return cumulative "
			"categories for the complete contact history represented by previous_state "
			"plus these new messages."
		),
		"previous_state": {
			"summary": summary.summary or "",
			"primary_intent": summary.primary_intent or "",
			"categories": _json_list(summary.categories),
			"action_items": _json_list(summary.action_items),
			"risks": _json_list(summary.risks),
			"language": summary.language or "",
		},
		"available_categories": frappe.get_all(
			"WhatsApp Core Message Category",
			filters={"enabled": 1},
			pluck="name",
			order_by="name asc",
			limit_page_length=250,
		),
		"new_messages": [
			{
				"message_ref": f"M{index}",
				"direction": row.direction,
				"type": row.message_type,
				"time": str(row.provider_timestamp),
				"text": row.body or "",
			}
			for index, row in enumerate(messages, 1)
		],
		"required_output": _required_output(include_message_insights=True),
	}, ensure_ascii=False)


def _required_output(*, include_message_insights: bool) -> dict:
	result = {
		"summary": (
			"fact-based cumulative operational overview, or an empty string for "
			"ordinary non-actionable chat"
		),
		"primary_intent": "short intent",
		"categories": ["category"],
		"action_items": ["specific follow-up"],
		"risks": ["uncertainty, disagreement, or escalation"],
		"confidence": "number from 0 to 100",
		"language": "primary language",
	}
	if include_message_insights:
		result["message_insights"] = [{
			"message_ref": "M1",
			"transcript": "voice transcript or empty",
			"media_summary": "image/document/voice evidence or empty",
			"message_summary": "one-line meaning",
			"category": "the single most important category (backward-compatible primary)",
			"categories": (
				"one or more short reusable business categories; include every independently "
				"useful intent evidenced by this message, reuse available_categories when it "
				"fits, and use Other only when no useful reusable category applies"
			),
			"primary_intent": "short intent",
			"intents": ["intent"],
			"action_items": ["action"],
			"risks": ["risk"],
			"confidence": "0 to 100",
			"language": "language",
		}]
	return result


def _media_parts(messages: list[dict], settings) -> list[dict]:
	parts = []
	maximum = max(1, cint(settings.summary_max_media_mb) or 15) * 1024 * 1024
	for index, message in enumerate(messages, 1):
		if str(message.message_type).lower() not in MEDIA_TYPES:
			continue
		descriptor = media_descriptor(message.message_type, message.content)
		if not descriptor:
			continue
		try:
			file_doc = cache_message_media(message.name)
			content = file_doc.get_content()
		except Exception:
			# An expired provider URL must not block text or the other media in
			# this incremental batch. The model can flag this item for review.
			parts.append({
				"type": "text",
				"text": f"Attachment for message M{index} is unavailable for analysis.",
			})
			continue
		if isinstance(content, str):
			content = content.encode()
		if len(content) > maximum:
			continue
		mime_type = str(file_doc.get("content_type") or descriptor.get("mime_type") or "")
		encoded = base64.b64encode(content).decode()
		parts.append({"type": "text", "text": f"Attachment for message M{index}:"})
		if message.message_type in {"image", "sticker"}:
			parts.append({
				"type": "image_url",
				"image_url": {"url": f"data:{mime_type or 'image/jpeg'};base64,{encoded}"},
			})
		elif message.message_type == "audio":
			parts.append({
				"type": "input_audio",
				"input_audio": {"data": encoded, "format": _media_format(file_doc.file_name, mime_type)},
			})
		elif message.message_type == "document" and mime_type == "application/pdf":
			parts.append({
				"type": "file",
				"file": {
					"filename": file_doc.file_name or f"message-M{index}.pdf",
					"file_data": f"data:application/pdf;base64,{encoded}",
				},
			})
	return parts


def _run_i2a(settings, prompt: str, content_parts: list[dict]) -> dict:
	if "frappe_tools" not in frappe.get_installed_apps():
		frappe.throw("Frappe Tools is required for AI summaries", frappe.ValidationError)
	from frappe_tools.i2a.intents import run_intent
	from frappe_tools.i2a.providers import ProviderError

	try:
		return run_intent(
			settings.summary_i2a_action,
			prompt,
			content_parts=content_parts,
		)
	except ProviderError as exc:
		# Provider-side decoders can reject a single corrupt or unsupported
		# attachment even when the surrounding conversation is perfectly valid.
		# Keep the text/category pipeline available and make the loss explicit in
		# the evidence prompt instead of failing the contact's whole batch forever.
		if not content_parts or not _is_media_decode_error(exc):
			raise
		return run_intent(
			settings.summary_i2a_action,
			prompt
			+ "\n\nMedia note: one or more attachments could not be decoded by the model. "
			"Categorize the supplied text and metadata only; do not infer attachment contents.",
			content_parts=[],
		)


def _is_media_decode_error(exc: Exception) -> bool:
	message = str(exc or "").lower()
	return any(
		marker in message
		for marker in (
			"unable to process input image",
			"invalid image",
			"unsupported image",
			"invalid audio",
			"unsupported audio",
			"media could not be decoded",
			"failed to decode media",
			# Gemini/OpenRouter can collapse the same media decoder failure into
			# this generic provider message. Limit this fallback to calls that
			# actually contained media so credential or billing errors are not hidden.
			"provider returned error",
		)
	)


def _upsert_message_insights(identity, messages, data, settings, model_result) -> None:
	by_ref = {
		str(row.get("message_ref") or ""): row
		for row in (data.get("message_insights") or [])
		if isinstance(row, dict)
	}
	for index, message in enumerate(messages, 1):
		result = by_ref.get(f"M{index}") or {}
		name = hashlib.sha256(f"message-insight:{message.name}".encode()).hexdigest()
		doc = frappe.get_doc("WhatsApp Core Message Insight", name) if frappe.db.exists(
			"WhatsApp Core Message Insight", name
		) else frappe.get_doc({
			"doctype": "WhatsApp Core Message Insight",
			"insight_key": name,
			"message": message.name,
			"conversation": message.conversation,
			"identity": identity,
		})
		doc.status = "Ready" if result else "Needs Review"
		categories = normalize_message_categories(result.get("categories"), result.get("category"))
		doc.category = ensure_message_category(categories[0], source="AI")
		doc.primary_intent = str(result.get("primary_intent") or "")[:140]
		doc.confidence = _confidence(result.get("confidence"))
		doc.transcript = str(result.get("transcript") or "")
		doc.media_summary = str(result.get("media_summary") or "")
		doc.message_summary = str(result.get("message_summary") or message.body or "")
		doc.intents = _json_value(result.get("intents"))
		doc.action_items = _json_value(result.get("action_items"))
		doc.risks = _json_value(result.get("risks"))
		doc.language = str(result.get("language") or "")[:140]
		doc.ai_action = settings.summary_i2a_action
		doc.ai_model = model_result.get("model") or ""
		doc.analyzed_at = now_datetime()
		doc.error = "" if result else "Model omitted this message from message_insights"
		if doc.is_new():
			doc.insert(ignore_permissions=True)
		else:
			doc.save(ignore_permissions=True)
		set_message_categories(
			message.name,
			message.conversation,
			identity,
			categories,
			source="AI",
			confidence=doc.confidence,
		)


def _update_summary(summary, messages, data, settings, model_result) -> None:
	last = messages[-1]
	_complete_model_rollup(data, messages, summary.summary)
	processed_count = cint(summary.processed_message_count) + len(messages)
	summary.message_count = processed_count
	summary.processed_message_count = processed_count
	summary.last_message = last.name
	summary.last_message_at = last.provider_timestamp
	summary.last_message_creation = last.creation
	_apply_summary_result(summary, data, settings, model_result)
	summary.save(ignore_permissions=True)


def _complete_model_rollup(data: dict, messages: list[dict], previous_summary: str) -> None:
	"""Keep the management overview useful when a model omits roll-up fields."""
	insights = [row for row in (data.get("message_insights") or []) if isinstance(row, dict)]
	data["categories"] = _merge_unique(
		data.get("categories"),
		[row.get("category") for row in insights if row.get("category")],
	)
	if str(data.get("summary") or "").strip():
		return
	message_bodies = [str(row.get("body") or "").strip() for row in messages]
	snippets = [str(row.get("message_summary") or "").strip() for row in insights]
	snippets = [value for value in snippets or message_bodies if value]
	if not snippets:
		snippets = [value for value in message_bodies if value]
	parts = _merge_unique(
		[str(previous_summary or "").strip()] if previous_summary else [],
		snippets,
	)
	data["summary"] = " ".join(parts)[:4000]


def _reset_summary(summary) -> None:
	summary.last_message = None
	summary.last_message_at = None
	summary.last_message_creation = None
	summary.message_count = 0
	summary.processed_message_count = 0
	summary.summary = ""
	summary.primary_intent = ""
	summary.categories = "[]"
	summary.action_items = "[]"
	summary.risks = "[]"
	summary.confidence = 0
	summary.language = ""
	summary.error = ""
	summary.status = "Needs Review"


def _apply_summary_result(summary, data, settings, model_result) -> None:
	valid_result = bool(
		data.get("summary")
		or data.get("message_insights")
		or data.get("categories")
		or data.get("primary_intent")
	)
	summary.status = "Ready" if valid_result else "Needs Review"
	summary.summary = str(data.get("summary") or summary.summary or "")
	summary.primary_intent = str(data.get("primary_intent") or "")[:140]
	# An incremental provider response can focus only on the newest message even
	# while returning a cumulative prose summary. Keep every previously observed
	# category so management rollups do not silently lose Payment, Complaint or
	# Opt-out history when a later Catalogue/Other message arrives. A forced
	# rebuild clears the stored state first and therefore remains authoritative.
	categories = _merge_unique(_json_list(summary.categories), data.get("categories"))
	summary.categories = _json_value([
		ensure_message_category(category, source="AI") for category in categories
	])
	summary.action_items = _json_value(data.get("action_items"))
	summary.risks = _json_value(data.get("risks"))
	summary.confidence = _confidence(data.get("confidence"))
	summary.language = str(data.get("language") or "")[:140]
	summary.last_generated_at = now_datetime()
	summary.ai_action = settings.summary_i2a_action
	summary.ai_model = model_result.get("model") or ""
	summary.error = "" if valid_result else "Model returned no usable result"


def _get_or_create_summary(scope_type: str, scope_key: str, identities: list[str]):
	name = _summary_name(scope_type, scope_key)
	if frappe.db.exists("WhatsApp Core Contact Summary", name):
		return frappe.get_doc("WhatsApp Core Contact Summary", name)
	doc = frappe.get_doc({
		"doctype": "WhatsApp Core Contact Summary",
		"summary_key": name,
		"scope_type": scope_type,
		"scope_key": scope_key,
		"identity": identities[0] if scope_type == "Identity" else None,
		"source_identities": json.dumps(identities, separators=(",", ":")),
		"identity_count": len(identities),
		"status": "Needs Review",
	})
	doc.insert(ignore_permissions=True)
	return doc


def _identity_summary_in_progress(identity: str) -> dict:
	name = _summary_name("Identity", identity)
	if frappe.db.exists("WhatsApp Core Contact Summary", name):
		result = _summary_dict(frappe.get_doc("WhatsApp Core Contact Summary", name))
	else:
		result = {
			"scope_type": "Identity",
			"scope_key": identity,
			"identity": identity,
			"status": "Needs Review",
			"summary": "",
			"categories": [],
			"action_items": [],
			"risks": [],
		}
	result["refresh_in_progress"] = True
	return result


def _group_summary_in_progress(scope_key: str, identities: list[str]) -> dict:
	name = _summary_name("Group", scope_key)
	if frappe.db.exists("WhatsApp Core Contact Summary", name):
		result = _summary_dict(frappe.get_doc("WhatsApp Core Contact Summary", name))
	else:
		result = {
			"scope_type": "Group",
			"scope_key": scope_key,
			"source_identities": identities,
			"identity_count": len(identities),
			"status": "Needs Review",
			"summary": "",
			"categories": [],
			"action_items": [],
			"risks": [],
		}
	result["refresh_in_progress"] = True
	return result


def _model_data(model_result) -> dict:
	"""Normalize provider JSON without assuming every model returns an object."""
	if not isinstance(model_result, dict):
		return {}
	data = model_result.get("data")
	if isinstance(data, dict):
		return _normalize_model_data(dict(data))
	if not isinstance(data, list):
		return {}
	dictionaries = [row for row in data if isinstance(row, dict)]
	for row in dictionaries:
		if "summary" in row or "message_insights" in row:
			return _normalize_model_data(dict(row))
	if dictionaries and all("message_ref" in row for row in dictionaries):
		return _normalize_model_data({"message_insights": dictionaries})
	if len(dictionaries) == 1:
		return _normalize_model_data(dict(dictionaries[0]))
	# A bare list is occasionally produced for the requested per-message rows.
	# Retain those insights and let the summary remain Needs Review.
	return _normalize_model_data({"message_insights": dictionaries})


def _normalize_model_data(data: dict) -> dict:
	"""Make model output deterministic before it reaches DocType upserts."""
	insights = data.get("message_insights")
	if not isinstance(insights, list):
		return data
	by_ref = {}
	order = []
	for row in insights:
		if not isinstance(row, dict):
			continue
		message_ref = str(row.get("message_ref") or "").strip()
		if not message_ref:
			continue
		if message_ref not in by_ref:
			order.append(message_ref)
		# Prefer the last row: models commonly correct or enrich the repeated row.
		by_ref[message_ref] = row
	data["message_insights"] = [by_ref[message_ref] for message_ref in order]
	return data


def _summary_dict(summary) -> dict:
	result = summary.as_dict()
	for key in ("source_identities", "categories", "action_items", "risks"):
		result[key] = _json_list(result.get(key))
	return result


def _valid_identity(identity) -> str:
	identity = str(identity or "").strip()
	if not identity or not frappe.db.exists("WhatsApp Core Identity", identity):
		frappe.throw("Contact not found", frappe.DoesNotExistError)
	return identity


def _settings():
	return frappe.get_single("WhatsApp Core Settings")


def _action_or_throw(settings) -> None:
	if not cint(settings.enable_ai_summaries):
		frappe.throw("AI summaries are disabled", frappe.ValidationError)
	if not str(settings.summary_i2a_action or "").strip():
		frappe.throw("Configure the Summary I2A Action", frappe.ValidationError)


def _batch_size(settings) -> int:
	return max(1, min(cint(settings.summary_batch_size) or DEFAULT_BATCH_SIZE, 250))


def _summary_name(scope_type: str, scope_key: str) -> str:
	return hashlib.sha256(f"{scope_type}:{scope_key}".encode()).hexdigest()


def _group_scope_key(identities: list[str]) -> str:
	return "group:" + hashlib.sha256("|".join(sorted(identities)).encode()).hexdigest()


def _summary_job_id(identity: str) -> str:
	return "whatsapp-summary-" + hashlib.sha256(str(identity).encode()).hexdigest()[:24]


def _media_format(filename: str | None, mime_type: str) -> str:
	extension = Path(str(filename or "")).suffix.lower().lstrip(".")
	if extension in {"aac", "aiff", "flac", "m4a", "mp3", "ogg", "wav", "webm"}:
		return extension
	return {
		"audio/aac": "aac",
		"audio/flac": "flac",
		"audio/mp4": "m4a",
		"audio/mpeg": "mp3",
		"audio/ogg": "ogg",
		"audio/wav": "wav",
		"audio/webm": "webm",
	}.get(str(mime_type or "").split(";", 1)[0].lower(), "ogg")


def _confidence(value) -> float:
	try:
		return max(0, min(float(value or 0), 100))
	except (TypeError, ValueError):
		return 0


def _json_value(value) -> str:
	return json.dumps(value if isinstance(value, list) else [], ensure_ascii=False, separators=(",", ":"))


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


def _merge_unique(previous, current) -> list:
	return list(dict.fromkeys(
		str(value).strip()
		for value in [*_json_list(previous), *_json_list(current)]
		if str(value or "").strip()
	))
