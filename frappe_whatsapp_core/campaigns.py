"""Generic, site-isolated campaign preparation and safe dispatch."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable

import frappe
from frappe.utils import get_datetime, now_datetime

MAX_PREPARE_RECIPIENTS = 10_000
DEFAULT_BATCH_SIZE = 40


def create_campaign(
	*,
	campaign_key: str,
	title: str,
	channel: str,
	template: str,
	description: str = "",
	audience_source: dict | None = None,
):
	return frappe.get_doc({
		"doctype": "WhatsApp Core Campaign",
		"campaign_key": campaign_key,
		"title": title,
		"description": description,
		"channel": channel,
		"template": template,
		"audience_source": json.dumps(
			audience_source or {},
			separators=(",", ":"),
			ensure_ascii=False,
		),
		"status": "Draft",
	}).insert()


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
	campaign.status = "Running"
	campaign.started_at = campaign.started_at or now_datetime()
	campaign.save()
	frappe.enqueue(
		"frappe_whatsapp_core.campaigns.process_campaign_batch",
		queue="short",
		enqueue_after_commit=True,
		campaign_name=campaign.name,
	)
	return campaign_summary(campaign.name)


def cancel_campaign(campaign_name: str) -> dict:
	campaign = frappe.get_doc("WhatsApp Core Campaign", campaign_name)
	frappe.has_permission(
		"WhatsApp Core Campaign",
		"write",
		doc=campaign,
		throw=True,
	)
	if campaign.status == "Completed":
		frappe.throw("A completed campaign cannot be cancelled", frappe.ValidationError)
	frappe.db.set_value(
		"WhatsApp Core Campaign Recipient",
		{"campaign": campaign.name, "status": "Prepared"},
		{"status": "Skipped", "completed_at": now_datetime()},
		update_modified=False,
	)
	campaign.status = "Cancelled"
	campaign.completed_at = now_datetime()
	campaign.save()
	refresh_campaign_counts(campaign.name)
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
		try:
			launch_campaign(campaign_name)
			frappe.db.commit()
		except Exception:
			frappe.db.rollback()
			frappe.log_error(
				title=f"WhatsApp campaign launch failed: {campaign_name}",
				message=frappe.get_traceback(),
			)


def process_campaign_batch(
	campaign_name: str,
	batch_size: int = DEFAULT_BATCH_SIZE,
) -> None:
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
		limit_page_length=max(1, min(int(batch_size), 500)),
	)
	if not recipients:
		_complete_campaign(campaign)
		return

	if batch_sender:
		_queue_recipient_batch(campaign, recipients, batch_sender)
	else:
		for row in recipients:
			if frappe.db.get_value(
				"WhatsApp Core Campaign",
				campaign.name,
				"status",
			) != "Running":
				return
			_queue_recipient(campaign, row, sender)
	frappe.db.commit()
	refresh_campaign_counts(campaign.name)

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
	frappe.db.sql(
		"""
		UPDATE `tabWhatsApp Core Campaign Recipient` recipient
		INNER JOIN `tabWhatsApp Core Message` message
			ON message.name = recipient.core_message
		SET
			recipient.status = CASE
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
	frappe.db.set_value(
		"WhatsApp Core Campaign",
		campaign_name,
		values,
		update_modified=False,
	)
	return values


def campaign_summary(campaign_name: str) -> dict:
	campaign = frappe.get_doc("WhatsApp Core Campaign", campaign_name)
	template = frappe.get_cached_doc("WhatsApp Core Template", campaign.template)
	return {
		"name": campaign.name,
		"campaign_key": campaign.campaign_key,
		"title": campaign.title,
		"description": campaign.description,
		"channel": campaign.channel,
		"template": campaign.template,
		"template_name": template.template_name,
		"language_code": template.language_code,
		"template_approval_status": template.approval_status,
		"template_enabled": bool(template.enabled),
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
	template = frappe.get_cached_doc("WhatsApp Core Template", campaign.template)
	if not template.enabled:
		frappe.throw(
			"Template is disabled for this site in the Integration application",
			frappe.ValidationError,
		)
	if template.approval_status != "APPROVED":
		frappe.throw(
			"Meta template approval is required before SEND authorization",
			frappe.ValidationError,
		)
	channel = frappe.get_cached_doc("WhatsApp Core Channel", campaign.channel)
	if not channel.enabled:
		frappe.throw("Campaign channel is disabled", frappe.ValidationError)
	if not campaign.recipient_count:
		frappe.throw("Campaign has no prepared recipients", frappe.ValidationError)


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
	return frappe.get_attr(paths[0]) if paths else None


def _queue_recipient_batch(campaign, recipients, sender) -> None:
	try:
		results = sender(campaign, recipients)
	except Exception as exception:
		for recipient in recipients:
			_mark_recipient_failed(recipient, exception)
		return
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
			continue
		_mark_recipient_failed(
			recipient,
			result.get("error", "Campaign batch sender returned no result")
			if isinstance(result, dict)
			else "Campaign batch sender returned an invalid result",
			message_name=message_name,
		)


def _queue_recipient(campaign, recipient, sender) -> None:
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
	except Exception as exception:
		_mark_recipient_failed(recipient, exception)
		frappe.log_error(
			title=f"WhatsApp campaign recipient failed: {recipient.name}",
			message=frappe.get_traceback(),
		)


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
	refresh_campaign_counts(campaign.name)
	campaign.reload()
	if campaign.status != "Running":
		return
	campaign.status = "Completed"
	campaign.completed_at = now_datetime()
	campaign.save(ignore_permissions=True)


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
