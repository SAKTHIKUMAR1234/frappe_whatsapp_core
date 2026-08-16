"""Generic, site-isolated campaign preparation and safe dispatch."""

from __future__ import annotations

import hashlib
import json
import random
import time
from collections.abc import Iterable

import frappe
from frappe.utils import get_datetime, now_datetime

from frappe_whatsapp_core.delivery import enqueue_delivery_status_handlers
from frappe_whatsapp_core.realtime import publish_invalidation

MAX_PREPARE_RECIPIENTS = 10_000
DEFAULT_BATCH_SIZE = 40
DIRTY_CAMPAIGNS_CACHE_KEY = "whatsapp_core_dirty_campaigns"
CAMPAIGN_COUNTER_FIELDS = {
	"Queued": "queued_count",
	"Sent": "sent_count",
	"Delivered": "delivered_count",
	"Read": "read_count",
	"Failed": "failed_count",
	"Skipped": "skipped_count",
}


def create_campaign(
	*,
	campaign_key: str,
	title: str,
	channel: str,
	template: str = "",
	content_type: str = "Template",
	message_text: str = "",
	description: str = "",
	audience_source: dict | None = None,
):
	content_type = str(content_type or "Template").strip().title()
	if content_type not in {"Template", "Text"}:
		frappe.throw("Campaign content type must be Template or Text", frappe.ValidationError)
	campaign = frappe.get_doc({
		"doctype": "WhatsApp Core Campaign",
		"campaign_key": campaign_key,
		"title": title,
		"description": description,
		"channel": channel,
		"content_type": content_type,
		"template": template if content_type == "Template" else None,
		"message_text": str(message_text or "").strip() if content_type == "Text" else None,
		"audience_source": json.dumps(
			audience_source or {},
			separators=(",", ":"),
			ensure_ascii=False,
		),
		"status": "Draft",
	}).insert()
	_publish_campaign(campaign)
	return campaign


def prepare_campaign(campaign_name: str, recipients) -> dict:
	"""Replace only this draft's audience with exact Core identity references."""
	campaign = frappe.get_doc("WhatsApp Core Campaign", campaign_name)
	frappe.has_permission(
		"WhatsApp Core Campaign",
		"write",
		doc=campaign,
		throw=True,
	)
	if campaign.status not in {"Draft", "Prepared"} or campaign.send_authorized:
		frappe.throw(
			"Only an unauthorized draft or prepared campaign can be prepared",
			frappe.ValidationError,
		)

	normalized = _normalize_recipients(recipients)
	if not normalized:
		frappe.throw("At least one recipient is required", frappe.ValidationError)
	if len(normalized) > MAX_PREPARE_RECIPIENTS:
		frappe.throw(
			f"A campaign can prepare at most {MAX_PREPARE_RECIPIENTS} recipients at once",
			frappe.ValidationError,
		)
	_assert_active_identities(item["identity"] for item in normalized)

	frappe.db.delete(
		"WhatsApp Core Campaign Recipient",
		{"campaign": campaign.name},
	)
	now = now_datetime()
	fields = [
		"name",
		"recipient_key",
		"campaign",
		"identity",
		"status",
		"personalization",
		"attempts",
		"owner",
		"creation",
		"modified",
		"modified_by",
	]
	values = []
	for item in normalized:
		recipient_key = _recipient_key(campaign.name, item["identity"])
		values.append([
			recipient_key,
			recipient_key,
			campaign.name,
			item["identity"],
			"Prepared",
			json.dumps(
				item["personalization"],
				separators=(",", ":"),
				ensure_ascii=False,
			),
			0,
			frappe.session.user,
			now,
			now,
			frappe.session.user,
		])
	frappe.db.bulk_insert(
		"WhatsApp Core Campaign Recipient",
		fields=fields,
		values=values,
	)
	campaign.status = "Prepared"
	campaign.prepared_at = now
	campaign.recipient_count = len(values)
	_reset_delivery_counts(campaign)
	campaign.save()
	_publish_campaign(campaign)
	return campaign_summary(campaign.name)


def authorize_campaign(campaign_name: str, confirmation: str) -> dict:
	"""Record the distinct human SEND authorization gate."""
	campaign = frappe.get_doc("WhatsApp Core Campaign", campaign_name)
	frappe.has_permission(
		"WhatsApp Core Campaign",
		"write",
		doc=campaign,
		throw=True,
	)
	expected = f"AUTHORIZE {campaign.campaign_key}"
	if confirmation != expected:
		frappe.throw(
			f"Type exactly: {expected}",
			frappe.ValidationError,
		)
	_validate_campaign_definition(campaign)
	if campaign.status != "Prepared":
		frappe.throw("Prepare the campaign before authorizing it", frappe.ValidationError)

	campaign.send_authorized = 1
	campaign.authorized_by = frappe.session.user
	campaign.authorized_at = now_datetime()
	campaign.save()
	_publish_campaign(campaign)
	return campaign_summary(campaign.name)


def revoke_campaign_authorization(campaign_name: str) -> dict:
	campaign = frappe.get_doc("WhatsApp Core Campaign", campaign_name)
	frappe.has_permission(
		"WhatsApp Core Campaign",
		"write",
		doc=campaign,
		throw=True,
	)
	if campaign.status in {"Running", "Completed", "Cancelled"}:
		frappe.throw(
			f"Authorization cannot be revoked while campaign is {campaign.status}",
			frappe.ValidationError,
		)
	campaign.send_authorized = 0
	campaign.authorized_by = None
	campaign.authorized_at = None
	campaign.save()
	_publish_campaign(campaign)
	return campaign_summary(campaign.name)


def schedule_campaign(campaign_name: str, scheduled_for) -> dict:
	campaign = frappe.get_doc("WhatsApp Core Campaign", campaign_name)
	frappe.has_permission(
		"WhatsApp Core Campaign",
		"write",
		doc=campaign,
		throw=True,
	)
	_validate_launch(campaign)
	scheduled_at = get_datetime(scheduled_for)
	if scheduled_at <= now_datetime():
		frappe.throw("Schedule time must be in the future", frappe.ValidationError)
	campaign.status = "Scheduled"
	campaign.scheduled_for = scheduled_at
	campaign.save()
	_publish_campaign(campaign)
	return campaign_summary(campaign.name)


def launch_campaign(campaign_name: str) -> dict:
	"""Start a prepared campaign only after all Core and business gates pass."""
	campaign = frappe.get_doc("WhatsApp Core Campaign", campaign_name)
	frappe.has_permission(
		"WhatsApp Core Campaign",
		"write",
		doc=campaign,
		throw=True,
	)
	_validate_launch(campaign)
	if (campaign.content_type or "Template") == "Template" and not campaign.template_snapshot:
		from frappe_whatsapp_core.outbound import freeze_campaign_template

		campaign.template_snapshot = json.dumps(
			freeze_campaign_template(campaign.template, channel=campaign.channel),
			separators=(",", ":"),
			ensure_ascii=False,
		)
	campaign.status = "Running"
	campaign.started_at = campaign.started_at or now_datetime()
	campaign.save()
	_publish_campaign(campaign)
	frappe.enqueue(
		"frappe_whatsapp_core.campaigns.process_campaign_batch",
		queue="short",
		enqueue_after_commit=True,
		campaign_name=campaign.name,
	)
	return campaign_summary(campaign.name)


def cancel_campaign(campaign_name: str) -> dict:
	"""Cancel safely while independent transport workers are still committing."""
	for attempt in range(6):
		try:
			return _cancel_campaign_once(campaign_name)
		except frappe.QueryDeadlockError:
			frappe.db.rollback()
			if attempt == 5:
				raise
			time.sleep(min(1.5, 0.08 * (2**attempt)) + random.uniform(0, 0.04))


def _cancel_campaign_once(campaign_name: str) -> dict:
	# Serialize cancellation with campaign batch preparation and counter refreshes.
	# Loading the document before taking this row lock lets a concurrent worker
	# update ``modified`` and makes ``campaign.save()`` fail with MariaDB error
	# 1020 (document changed since it was read).
	_lock_campaign_rows([campaign_name])
	campaign = frappe.get_doc("WhatsApp Core Campaign", campaign_name)
	frappe.has_permission(
		"WhatsApp Core Campaign",
		"write",
		doc=campaign,
		throw=True,
	)
	if campaign.status == "Completed":
		frappe.throw("A completed campaign cannot be cancelled", frappe.ValidationError)
	# Messages are created optimistically before the durable relay submission.  A
	# campaign can therefore be cancelled while those messages are still Queued.
	# Make them terminal in the same transaction so the global retry scheduler
	# cannot resurrect a cancelled campaign.
	queued_messages = frappe.get_all(
		"WhatsApp Core Campaign Recipient",
		filters={
			"campaign": campaign.name,
			"status": "Queued",
			"core_message": ["is", "set"],
		},
		pluck="core_message",
		limit_page_length=MAX_PREPARE_RECIPIENTS,
	)
	if queued_messages:
		message_names = sorted(set(queued_messages))
		frappe.db.sql(
			"""
			SELECT name
			FROM `tabWhatsApp Core Message`
			WHERE name IN %(message_names)s
			  AND delivery_status = 'Queued'
			ORDER BY name
			FOR UPDATE
			""",
			{"message_names": message_names},
		)
		frappe.db.sql(
			"""
			UPDATE `tabWhatsApp Core Message`
			SET
				delivery_status = 'Failed',
				failure = %(failure)s
			WHERE name IN %(message_names)s
				AND delivery_status = 'Queued'
			""",
			{
				"message_names": message_names,
				"failure": json.dumps({
					"error": "Campaign cancelled before relay submission",
					"code": "campaign_cancelled",
					"retryable": False,
				}, separators=(",", ":")),
			},
		)
		enqueue_delivery_status_handlers([
			{"message_name": name, "delivery_status": "Failed"}
			for name in message_names
		])
	frappe.db.set_value(
		"WhatsApp Core Campaign Recipient",
		{"campaign": campaign.name, "status": ["in", ["Prepared", "Queued"]]},
		{"status": "Skipped", "completed_at": now_datetime()},
		update_modified=False,
	)
	campaign.status = "Cancelled"
	campaign.completed_at = now_datetime()
	campaign.save()
	refresh_campaign_counts(campaign.name)
	_publish_campaign(campaign)
	return campaign_summary(campaign.name)


def run_due_campaigns() -> None:
	for campaign_name in frappe.get_all(
		"WhatsApp Core Campaign",
		filters={
			"status": "Scheduled",
			"scheduled_for": ["<=", now_datetime()],
		},
		pluck="name",
		limit_page_length=100,
	):
		savepoint = "whatsapp_campaign_" + hashlib.sha256(campaign_name.encode()).hexdigest()[:16]
		frappe.db.savepoint(savepoint)
		try:
			launch_campaign(campaign_name)
		except Exception:
			frappe.db.rollback(save_point=savepoint)
			frappe.log_error(
				title=f"WhatsApp campaign launch failed: {campaign_name}",
				message=frappe.get_traceback(),
			)


def process_campaign_batch(
	campaign_name: str,
	batch_size: int = DEFAULT_BATCH_SIZE,
) -> None:
	"""Advance one campaign batch, retrying the complete transaction on deadlock.

	MariaDB/MyRocks invalidates the whole transaction after a deadlock. Catching
	the exception inside one recipient loop leaves Python objects referring to
	message inserts that the database has already rolled back. Always rebuild the
	full bounded batch from committed state instead.
	"""
	for attempt in range(6):
		try:
			return _process_campaign_batch_once(campaign_name, batch_size)
		except frappe.QueryDeadlockError:
			frappe.db.rollback()
			if attempt == 5:
				raise
			time.sleep(min(1.5, 0.08 * (2**attempt)) + random.uniform(0, 0.04))


def _process_campaign_batch_once(
	campaign_name: str,
	batch_size: int = DEFAULT_BATCH_SIZE,
) -> None:
	# Every path that mutates campaign recipients/counters takes the campaign
	# row first.  This gives concurrent campaign and callback workers one
	# deterministic lock order: Campaign -> Campaign Recipient.  Without it,
	# MariaDB can raise error 1020 when a callback changes the aggregate row
	# after this transaction has read it.
	_lock_campaign_rows([campaign_name])
	campaign = frappe.get_doc("WhatsApp Core Campaign", campaign_name)
	if campaign.status != "Running":
		return
	batch_sender = _campaign_batch_sender()
	sender = None if batch_sender else _campaign_sender()
	recipients = frappe.get_all(
		"WhatsApp Core Campaign Recipient",
		filters={"campaign": campaign.name, "status": "Prepared"},
		fields=["name", "identity", "personalization", "attempts"],
		order_by="creation asc",
		# The Integration relay deliberately accepts at most 40 independent
		# messages in one HTTP request. Never let an internal caller override
		# that transport invariant with a larger worker batch.
		limit_page_length=max(1, min(int(batch_size), DEFAULT_BATCH_SIZE)),
	)
	if not recipients:
		_complete_campaign(campaign)
		return

	if batch_sender:
		batch_counts = _queue_recipient_batch(campaign, recipients, batch_sender)
	else:
		batch_counts = {}
		for row in recipients:
			if frappe.db.get_value(
				"WhatsApp Core Campaign",
				campaign.name,
				"status",
			) != "Running":
				return
			status = _queue_recipient(campaign, row, sender)
			batch_counts[status] = batch_counts.get(status, 0) + 1
	_apply_campaign_count_deltas(campaign.name, batch_counts)

	if frappe.db.exists(
		"WhatsApp Core Campaign Recipient",
		{"campaign": campaign.name, "status": "Prepared"},
	):
		frappe.enqueue(
			"frappe_whatsapp_core.campaigns.process_campaign_batch",
			queue="short",
			enqueue_after_commit=True,
			campaign_name=campaign.name,
			batch_size=batch_size,
		)
	else:
		_complete_campaign(campaign)


def refresh_active_campaigns() -> None:
	for campaign_name in frappe.get_all(
		"WhatsApp Core Campaign",
		filters={"status": ["in", ["Running", "Completed"]]},
		pluck="name",
		limit_page_length=500,
	):
		refresh_campaign_counts(campaign_name)


def refresh_campaign_counts(campaign_name: str) -> dict:
	_lock_campaign_rows([campaign_name])
	frappe.db.sql(
		"""
		UPDATE `tabWhatsApp Core Campaign Recipient` recipient
		INNER JOIN `tabWhatsApp Core Message` message
			ON message.name = recipient.core_message
		SET
			recipient.status = CASE
				WHEN recipient.status = 'Skipped' THEN 'Skipped'
				WHEN message.delivery_status = 'Read' THEN 'Read'
				WHEN message.delivery_status = 'Delivered' THEN 'Delivered'
				WHEN message.delivery_status = 'Sent' THEN 'Sent'
				WHEN message.delivery_status = 'Failed' THEN 'Failed'
				ELSE recipient.status
			END,
			recipient.completed_at = CASE
				WHEN message.delivery_status IN ('Read', 'Delivered', 'Failed')
					THEN COALESCE(recipient.completed_at, NOW())
				ELSE recipient.completed_at
			END
		WHERE recipient.campaign = %s
		""",
		campaign_name,
	)
	counts = {
		row.status: row.count
		for row in frappe.db.sql(
			"""
			SELECT status, COUNT(*) AS count
			FROM `tabWhatsApp Core Campaign Recipient`
			WHERE campaign = %s
			GROUP BY status
			""",
			campaign_name,
			as_dict=True,
		)
	}
	values = {
		"recipient_count": sum(counts.values()),
		"queued_count": counts.get("Queued", 0),
		"sent_count": counts.get("Sent", 0),
		"delivered_count": counts.get("Delivered", 0),
		"read_count": counts.get("Read", 0),
		"failed_count": counts.get("Failed", 0),
		"skipped_count": counts.get("Skipped", 0),
	}
	current = frappe.db.get_value(
		"WhatsApp Core Campaign",
		campaign_name,
		list(values),
		as_dict=True,
	) or {}
	changed = any(int(current.get(fieldname) or 0) != int(value or 0) for fieldname, value in values.items())
	frappe.db.set_value(
		"WhatsApp Core Campaign",
		campaign_name,
		values,
		update_modified=False,
	)
	if changed:
		_publish_campaign(campaign_name, counts=values)
	return values


def refresh_campaigns_for_messages(message_names) -> None:
	"""Reconcile only recipients linked to the changed messages.

	Delivery callbacks are intentionally concurrent.  Updating every recipient in a
	10,000-row campaign for each callback both serialized the hot path and created a
	lock-order cycle with the campaign sender.  Lock and transition only the affected
	recipient rows, then maintain the summary counters with one atomic campaign update.
	``refresh_campaign_counts`` remains the periodic/final full repair pass.
	"""
	message_names = list(dict.fromkeys(message_names or []))
	if not message_names:
		return
	campaign_names = [
		row.campaign
		for row in frappe.db.sql(
			"""
			SELECT DISTINCT recipient.campaign
			FROM `tabWhatsApp Core Campaign Recipient` recipient
			WHERE recipient.core_message IN %(message_names)s
			ORDER BY recipient.campaign
			""",
			{"message_names": message_names},
			as_dict=True,
		)
	]
	_lock_campaign_rows(campaign_names)
	rows = frappe.db.sql(
		"""
		SELECT
			recipient.name,
			recipient.campaign,
			recipient.status,
			message.delivery_status
		FROM `tabWhatsApp Core Campaign Recipient` recipient
		INNER JOIN `tabWhatsApp Core Message` message
			ON message.name = recipient.core_message
		WHERE recipient.core_message IN %(message_names)s
		FOR UPDATE
		""",
		{"message_names": message_names},
		as_dict=True,
	)
	deltas_by_campaign = {}
	for row in rows:
		# Cancellation intentionally makes the recipient terminal even though its
		# optimistic message is recorded as Failed to suppress transport retries.
		if row.status == "Skipped":
			continue
		target_status = (
			row.delivery_status
			if row.delivery_status in {"Queued", "Sent", "Delivered", "Read", "Failed"}
			else None
		)
		if not target_status or target_status == row.status:
			continue
		values = {"status": target_status}
		if target_status in {"Delivered", "Read", "Failed"}:
			values["completed_at"] = now_datetime()
		frappe.db.set_value(
			"WhatsApp Core Campaign Recipient",
			row.name,
			values,
			update_modified=False,
		)
		deltas = deltas_by_campaign.setdefault(row.campaign, {})
		if row.status in CAMPAIGN_COUNTER_FIELDS:
			deltas[row.status] = deltas.get(row.status, 0) - 1
		if target_status in CAMPAIGN_COUNTER_FIELDS:
			deltas[target_status] = deltas.get(target_status, 0) + 1

	for campaign_name, deltas in deltas_by_campaign.items():
		_apply_campaign_count_deltas(campaign_name, deltas)


def reconcile_campaign_status_batch(message_names) -> list[str]:
	"""Mark affected campaigns for serialized minute-level projection.

	Provider sent/delivered/read callbacks are operational telemetry, not new
	human-visible messages. Concurrent callback workers only identify affected
	campaigns; the scheduler performs the recipient join update once per campaign.
	This removes a hot multi-table update from the callback transaction.
	"""
	message_names = list(dict.fromkeys(message_names or []))
	if not message_names:
		return []
	campaign_names = [
		row.campaign
		for row in frappe.db.sql(
			"""
			SELECT DISTINCT recipient.campaign
			FROM `tabWhatsApp Core Campaign Recipient` recipient
			WHERE recipient.core_message IN %(message_names)s
			ORDER BY recipient.campaign
			""",
			{"message_names": message_names},
			as_dict=True,
		)
	]
	if not campaign_names:
		return []
	_mark_campaigns_dirty(campaign_names)
	return campaign_names


def refresh_dirty_campaign_counts(limit: int = 100) -> int:
	"""Repair aggregate counters for campaigns touched by status fast lanes."""
	members = sorted(frappe.cache.smembers(DIRTY_CAMPAIGNS_CACHE_KEY))
	refreshed = 0
	for member in members[: max(1, int(limit))]:
		campaign_name = member.decode() if isinstance(member, bytes) else str(member)
		if not frappe.db.exists("WhatsApp Core Campaign", campaign_name):
			frappe.cache.srem(DIRTY_CAMPAIGNS_CACHE_KEY, member)
			continue
		_sync_campaign_recipient_statuses(campaign_name)
		refresh_campaign_counts(campaign_name)
		frappe.cache.srem(DIRTY_CAMPAIGNS_CACHE_KEY, member)
		refreshed += 1
	return refreshed


def _sync_campaign_recipient_statuses(campaign_name: str) -> None:
	"""Apply all provider states for one campaign under one stable row lock."""
	_lock_campaign_rows([campaign_name])
	frappe.db.sql(
		"""
		UPDATE `tabWhatsApp Core Campaign Recipient` recipient
		INNER JOIN `tabWhatsApp Core Message` message
			ON message.name = recipient.core_message
		SET
			recipient.status = CASE
				WHEN recipient.status = 'Skipped' THEN 'Skipped'
				WHEN message.delivery_status = 'Read' THEN 'Read'
				WHEN message.delivery_status = 'Delivered' THEN 'Delivered'
				WHEN message.delivery_status = 'Sent' THEN 'Sent'
				WHEN message.delivery_status = 'Failed' THEN 'Failed'
				ELSE recipient.status
			END,
			recipient.completed_at = CASE
				WHEN message.delivery_status IN ('Read', 'Delivered', 'Failed')
					THEN COALESCE(recipient.completed_at, NOW())
				ELSE recipient.completed_at
			END
		WHERE recipient.campaign = %(campaign_name)s
			AND recipient.status != 'Skipped'
		""",
		{"campaign_name": campaign_name},
	)


def _mark_campaigns_dirty(campaign_names) -> None:
	names = sorted({str(name) for name in (campaign_names or []) if name})
	if names:
		frappe.cache.sadd(DIRTY_CAMPAIGNS_CACHE_KEY, *names)


def _lock_campaign_rows(campaign_names) -> None:
	"""Lock campaign aggregates in a stable order before recipient rows."""
	names = sorted({str(name) for name in (campaign_names or []) if name})
	if not names:
		return
	frappe.db.sql(
		"""
		SELECT name
		FROM `tabWhatsApp Core Campaign`
		WHERE name IN %(campaign_names)s
		ORDER BY name
		FOR UPDATE
		""",
		{"campaign_names": names},
	)


def enqueue_campaign_refresh_for_messages(message_names) -> None:
	"""Serialize campaign projection changes behind the Core short worker.

	Relay result callbacks are deliberately concurrent.  They may update independent
	message rows in parallel, but they must not all contend for the campaign's one
	aggregate row.  Queue one bounded reconciliation unit after the callback commits;
	the same short worker that advances campaign batches applies the recipient/status
	deltas in a deterministic order.
	"""
	message_names = list(dict.fromkeys(message_names or []))
	if not message_names:
		return
	if frappe.flags.in_test:
		refresh_campaigns_for_messages(message_names)
		return
	frappe.enqueue(
		"frappe_whatsapp_core.campaigns.reconcile_campaign_status_batch",
		queue="short",
		enqueue_after_commit=True,
		message_names=message_names,
	)


def campaign_summary(campaign_name: str) -> dict:
	campaign = frappe.get_doc("WhatsApp Core Campaign", campaign_name)
	content_type = campaign.content_type or "Template"
	template_snapshot = _json_object(campaign.template_snapshot)
	template = None
	if content_type == "Template" and campaign.template and not template_snapshot:
		template = frappe.get_cached_doc("WhatsApp Core Template", campaign.template)
	return {
		"name": campaign.name,
		"campaign_key": campaign.campaign_key,
		"title": campaign.title,
		"description": campaign.description,
		"channel": campaign.channel,
		"content_type": content_type,
		"template": campaign.template,
		"message_text": campaign.message_text if content_type == "Text" else "",
		"template_name": template_snapshot.get("template_name") or (template.template_name if template else ""),
		"language_code": template_snapshot.get("language_code") or (template.language_code if template else ""),
		"template_approval_status": template_snapshot.get("approval_status") or (template.approval_status if template else "NOT_REQUIRED"),
		"template_enabled": bool(template_snapshot.get("enabled")) if template_snapshot else bool(template.enabled) if template else False,
		"status": campaign.status,
		"send_authorized": bool(campaign.send_authorized),
		"authorized_by": campaign.authorized_by,
		"authorized_at": campaign.authorized_at,
		"scheduled_for": campaign.scheduled_for,
		"recipient_count": campaign.recipient_count,
		"queued_count": campaign.queued_count,
		"sent_count": campaign.sent_count,
		"delivered_count": campaign.delivered_count,
		"read_count": campaign.read_count,
		"failed_count": campaign.failed_count,
		"skipped_count": campaign.skipped_count,
		"modified": campaign.modified,
	}


def _normalize_recipients(recipients) -> list[dict]:
	if isinstance(recipients, str):
		recipients = frappe.parse_json(recipients)
	if not isinstance(recipients, list):
		frappe.throw("Recipients must be a list", frappe.ValidationError)

	result = {}
	for raw in recipients:
		item = {"identity": raw} if isinstance(raw, str) else dict(raw or {})
		identity = (item.get("identity") or "").strip()
		if not identity:
			frappe.throw("Every recipient requires an identity", frappe.ValidationError)
		personalization = item.get("personalization") or {}
		if isinstance(personalization, str):
			personalization = frappe.parse_json(personalization)
		if not isinstance(personalization, dict):
			frappe.throw(
				"Recipient personalization must be an object",
				frappe.ValidationError,
			)
		result[identity] = {
			"identity": identity,
			"personalization": personalization,
		}
	return list(result.values())


def _assert_active_identities(identity_names: Iterable[str]) -> None:
	requested = set(identity_names)
	rows = frappe.get_all(
		"WhatsApp Core Identity",
		filters={"name": ["in", list(requested)]},
		fields=["name", "status"],
		limit_page_length=MAX_PREPARE_RECIPIENTS,
	)
	active = {row.name for row in rows if row.status == "Active"}
	missing = sorted(requested - active)
	if missing:
		preview = ", ".join(missing[:5])
		suffix = "…" if len(missing) > 5 else ""
		frappe.throw(
			f"Recipients must reference active Core identities: {preview}{suffix}",
			frappe.ValidationError,
		)


def _recipient_key(campaign_name: str, identity_name: str) -> str:
	return hashlib.sha256(f"{campaign_name}:{identity_name}".encode()).hexdigest()


def _validate_campaign_definition(campaign) -> None:
	content_type = campaign.content_type or "Template"
	if content_type == "Template":
		if not campaign.template:
			frappe.throw("Select an approved template", frappe.ValidationError)
		snapshot = (
			_json_object(campaign.template_snapshot)
			if campaign.status in {"Running", "Paused"}
			else {}
		)
		template = (
			None
			if snapshot
			else frappe.get_cached_doc("WhatsApp Core Template", campaign.template)
		)
		enabled = bool(snapshot.get("enabled")) if snapshot else bool(template.enabled)
		approval_status = snapshot.get("approval_status") if snapshot else template.approval_status
		template_channel = snapshot.get("channel") if snapshot else template.channel
		if not template_channel or template_channel != campaign.channel:
			frappe.throw(
				"Template is assigned to a different WhatsApp account",
				frappe.ValidationError,
			)
		if not enabled:
			frappe.throw(
				"Template is disabled for this site in the Integration application",
				frappe.ValidationError,
			)
		if approval_status != "APPROVED":
			frappe.throw(
				"Meta template approval is required before SEND authorization",
				frappe.ValidationError,
			)
	elif content_type == "Text":
		body = str(campaign.message_text or "").strip()
		if not body:
			frappe.throw("Enter a campaign message", frappe.ValidationError)
		if len(body) > 4096:
			frappe.throw("Campaign message cannot exceed 4096 characters", frappe.ValidationError)
	else:
		frappe.throw("Campaign content type must be Template or Text", frappe.ValidationError)
	channel = frappe.get_cached_doc("WhatsApp Core Channel", campaign.channel)
	if not channel.enabled:
		frappe.throw("Campaign channel is disabled", frappe.ValidationError)
	if not campaign.recipient_count:
		frappe.throw("Campaign has no prepared recipients", frappe.ValidationError)


def _json_object(value) -> dict:
	if not value:
		return {}
	if isinstance(value, dict):
		return value
	try:
		parsed = json.loads(value)
	except (TypeError, ValueError):
		return {}
	return parsed if isinstance(parsed, dict) else {}


def _validate_launch(campaign) -> None:
	_validate_campaign_definition(campaign)
	if campaign.status not in {"Prepared", "Scheduled", "Paused"}:
		frappe.throw(
			f"Campaign cannot launch while status is {campaign.status}",
			frappe.ValidationError,
		)
	if not campaign.send_authorized:
		frappe.throw(
			"Explicit SEND authorization is required",
			frappe.ValidationError,
		)
	_run_preflight_hooks(campaign)
	if not _campaign_batch_sender():
		_campaign_sender()


def _run_preflight_hooks(campaign) -> None:
	for path in frappe.get_hooks("whatsapp_core_campaign_preflight"):
		result = frappe.get_attr(path)(campaign)
		if result is False:
			frappe.throw("Campaign business preflight failed", frappe.ValidationError)
		if isinstance(result, dict) and not result.get("ready", False):
			reasons = result.get("reasons") or ["Campaign business preflight failed"]
			frappe.throw("; ".join(reasons), frappe.ValidationError)


def _campaign_sender():
	paths = frappe.get_hooks("whatsapp_core_campaign_sender")
	if not paths:
		from frappe_whatsapp_core.outbound import queue_campaign_recipient

		return queue_campaign_recipient
	if len(paths) > 1:
		frappe.throw(
			"At most one business campaign sender can be configured",
			frappe.ValidationError,
		)
	return frappe.get_attr(paths[0])


def _campaign_batch_sender():
	paths = frappe.get_hooks("whatsapp_core_campaign_batch_sender")
	if len(paths) > 1:
		frappe.throw(
			"At most one business campaign batch sender may be configured",
			frappe.ValidationError,
		)
	if paths:
		return frappe.get_attr(paths[0])
	from frappe_whatsapp_core.outbound import queue_campaign_batch

	return queue_campaign_batch


def _queue_recipient_batch(campaign, recipients, sender) -> dict[str, int]:
	counts = {}
	try:
		results = sender(campaign, recipients)
	except frappe.QueryDeadlockError:
		# A deadlock rolls back every earlier message insert in this batch. The
		# outer campaign retry must reconstruct the batch from committed state.
		raise
	except Exception as exception:
		for recipient in recipients:
			_mark_recipient_failed(recipient, exception)
		return {"Failed": len(recipients)}
	if not isinstance(results, dict):
		results = {}
	for recipient in recipients:
		result = results.get(recipient.name) or {}
		message_name = result.get("message") if isinstance(result, dict) else None
		if isinstance(result, dict) and result.get("success") and message_name:
			frappe.db.set_value(
				"WhatsApp Core Campaign Recipient",
				recipient.name,
				{
					"status": "Queued",
					"core_message": message_name,
					"attempts": (recipient.attempts or 0) + 1,
					"queued_at": now_datetime(),
					"last_error": None,
				},
				update_modified=False,
			)
			counts["Queued"] = counts.get("Queued", 0) + 1
			continue
		_mark_recipient_failed(
			recipient,
			result.get("error", "Campaign batch sender returned no result")
			if isinstance(result, dict)
			else "Campaign batch sender returned an invalid result",
			message_name=message_name,
		)
		counts["Failed"] = counts.get("Failed", 0) + 1
	return counts


def _queue_recipient(campaign, recipient, sender) -> str:
	try:
		result = sender(campaign, recipient)
		message_name = result.get("message") if isinstance(result, dict) else result
		if not message_name:
			frappe.throw("Campaign sender did not return a Core message")
		frappe.db.set_value(
			"WhatsApp Core Campaign Recipient",
			recipient.name,
			{
				"status": "Queued",
				"core_message": message_name,
				"attempts": (recipient.attempts or 0) + 1,
				"queued_at": now_datetime(),
				"last_error": None,
			},
			update_modified=False,
		)
		return "Queued"
	except frappe.QueryDeadlockError:
		raise
	except Exception as exception:
		_mark_recipient_failed(recipient, exception)
		frappe.log_error(
			title=f"WhatsApp campaign recipient failed: {recipient.name}",
			message=frappe.get_traceback(),
		)
		return "Failed"


def _mark_recipient_failed(recipient, exception, message_name=None) -> None:
	values = {
		"status": "Failed",
		"attempts": (recipient.attempts or 0) + 1,
		"last_error": str(exception)[:500],
		"completed_at": now_datetime(),
	}
	if message_name:
		values["core_message"] = message_name
	frappe.db.set_value(
		"WhatsApp Core Campaign Recipient",
		recipient.name,
		values,
		update_modified=False,
	)


def _complete_campaign(campaign) -> None:
	"""Close dispatch without scanning message rows on the callback hot path.

	``process_campaign_batch`` has already applied the recipient deltas for the
	last batch.  Provider callbacks may concurrently update those same message
	rows, so running the full ``UPDATE .. JOIN`` reconciliation here can fail
	with MariaDB error 1020 (record changed since last read) and roll back the
	last prepared batch.  Callback-driven incremental reconciliation and the
	periodic repair job keep the delivery counters current after dispatch closes.
	"""
	campaign.reload()
	if campaign.status != "Running":
		return
	campaign.status = "Completed"
	campaign.completed_at = now_datetime()
	campaign.save(ignore_permissions=True)
	_publish_campaign(campaign)


def _publish_campaign(campaign, *, counts: dict | None = None) -> None:
	"""Notify every open Core tab after the surrounding transaction commits."""
	if isinstance(campaign, str):
		name = campaign
		status = frappe.db.get_value("WhatsApp Core Campaign", name, "status")
	else:
		name = campaign.name
		status = campaign.status
	publish_invalidation("whatsapp_core_campaign")


def _apply_campaign_count_deltas(campaign_name: str, deltas: dict[str, int]) -> None:
	"""Apply status transitions without scanning or locking the audience table."""
	assignments = []
	values = []
	for status, counter_field in CAMPAIGN_COUNTER_FIELDS.items():
		delta = int(deltas.get(status) or 0)
		if not delta:
			continue
		assignments.append(
			f"`{counter_field}` = GREATEST(0, `{counter_field}` + %s)"
		)
		values.append(delta)
	if not assignments:
		return
	values.append(campaign_name)
	frappe.db.sql(
		f"""
		UPDATE `tabWhatsApp Core Campaign`
		SET {', '.join(assignments)}
		WHERE name = %s
		""",
		values,
	)
	counts = frappe.db.get_value(
		"WhatsApp Core Campaign",
		campaign_name,
		list(CAMPAIGN_COUNTER_FIELDS.values()),
		as_dict=True,
	) or {}
	_publish_campaign(campaign_name, counts=counts)


def _reset_delivery_counts(campaign) -> None:
	for fieldname in (
		"queued_count",
		"sent_count",
		"delivered_count",
		"read_count",
		"failed_count",
		"skipped_count",
	):
		campaign.set(fieldname, 0)
