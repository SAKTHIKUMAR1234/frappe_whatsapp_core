"""Conversation topic projections owned by Core and populated externally."""

from __future__ import annotations

import hashlib
import json
import uuid

import frappe

VALID_STATUSES = {"Open", "Waiting", "Resolved", "Archived"}
VALID_SOURCES = {"Manual", "External AI", "Flow", "Import"}


def upsert_topic(
	conversation: str,
	title: str,
	summary: str = "",
	category: str = "",
	status: str = "Open",
	confidence: float = 0,
	message_names: list[str] | None = None,
	source: str = "External AI",
	topic_name: str | None = None,
	attributes: dict | None = None,
) -> dict:
	if not frappe.db.exists("WhatsApp Core Conversation", conversation):
		frappe.throw("Conversation does not exist")
	if status not in VALID_STATUSES:
		frappe.throw("Unsupported topic status")
	if source not in VALID_SOURCES:
		frappe.throw("Unsupported topic source")
	title = (title or "").strip()
	if not title:
		frappe.throw("Topic title is required")

	if topic_name:
		topic = frappe.get_doc("WhatsApp Core Conversation Topic", topic_name)
		if topic.conversation != conversation:
			frappe.throw("Topic belongs to another conversation")
	else:
		topic = frappe.get_doc({
			"doctype": "WhatsApp Core Conversation Topic",
			"topic_key": str(uuid.uuid4()),
			"conversation": conversation,
		})
	topic.title = title[:140]
	topic.summary = (summary or "").strip()
	topic.category = (category or "").strip()[:140]
	topic.status = status
	topic.confidence = max(0, min(float(confidence or 0), 100))
	topic.source = source
	topic.attributes = json.dumps(
		attributes or {},
		separators=(",", ":"),
		ensure_ascii=False,
	)
	if topic.is_new():
		topic.insert(ignore_permissions=True)
	else:
		topic.save(ignore_permissions=True)

	for message_name in message_names or []:
		_assign_message(topic, message_name, source, topic.confidence)
	_refresh_topic(topic)
	frappe.publish_realtime(
		"whatsapp_core_topic",
		{"topic": topic.name, "conversation": topic.conversation, "status": topic.status},
		after_commit=True,
	)
	return topic.as_dict()


def list_topics(conversation: str) -> list[dict]:
	topics = frappe.get_all(
		"WhatsApp Core Conversation Topic",
		filters={"conversation": conversation},
		fields=[
			"name",
			"title",
			"summary",
			"category",
			"status",
			"confidence",
			"source",
			"first_message",
			"last_message",
			"message_count",
			"modified",
		],
		order_by="modified desc",
		limit_page_length=100,
	)
	assignments = (
		frappe.get_all(
			"WhatsApp Core Topic Message",
			filters={"topic": ["in", [topic.name for topic in topics]]},
			fields=["topic", "message"],
			order_by="creation asc",
			limit_page_length=5000,
		)
		if topics
		else []
	)
	messages_by_topic = {}
	for assignment in assignments:
		messages_by_topic.setdefault(assignment.topic, []).append(
			assignment.message
		)
	for topic in topics:
		topic["messages"] = messages_by_topic.get(topic.name, [])
	return topics


def unclassified_messages(
	limit: int = 50,
	conversation: str | None = None,
) -> list[dict]:
	limit = max(1, min(int(limit), 250))
	conversation_filter = (
		"AND message.conversation = %(conversation)s"
		if conversation
		else ""
	)
	return frappe.db.sql(
		f"""
		SELECT
			message.name,
			message.conversation,
			message.direction,
			message.message_type,
			message.body,
			message.provider_timestamp
		FROM `tabWhatsApp Core Message` AS message
		LEFT JOIN `tabWhatsApp Core Topic Message` AS assignment
			ON assignment.message = message.name
		WHERE assignment.name IS NULL
			{conversation_filter}
		ORDER BY message.provider_timestamp DESC
		LIMIT %(limit)s
		""",
		{"conversation": conversation, "limit": limit},
		as_dict=True,
	)


def _assign_message(topic, message_name: str, source: str, confidence: float) -> None:
	message = frappe.db.get_value(
		"WhatsApp Core Message",
		message_name,
		["name", "conversation"],
		as_dict=True,
	)
	if not message:
		frappe.throw(f"Message {message_name} does not exist")
	if message.conversation != topic.conversation:
		frappe.throw(f"Message {message_name} belongs to another conversation")
	existing = frappe.db.get_value(
		"WhatsApp Core Topic Message",
		{"message": message.name},
		["name", "topic"],
		as_dict=True,
	)
	if existing:
		if existing.topic == topic.name:
			return
		frappe.throw(f"Message {message_name} is already assigned to another topic")
	assignment_key = hashlib.sha256(
		f"{topic.name}:{message.name}".encode()
	).hexdigest()
	if frappe.db.exists("WhatsApp Core Topic Message", assignment_key):
		return
	frappe.get_doc({
		"doctype": "WhatsApp Core Topic Message",
		"assignment_key": assignment_key,
		"topic": topic.name,
		"message": message.name,
		"assigned_by": source,
		"confidence": confidence,
	}).insert(ignore_permissions=True)


def _refresh_topic(topic) -> None:
	messages = frappe.db.sql(
		"""
		SELECT message.name
		FROM `tabWhatsApp Core Topic Message` AS assignment
		INNER JOIN `tabWhatsApp Core Message` AS message
			ON message.name = assignment.message
		WHERE assignment.topic = %(topic)s
		ORDER BY message.provider_timestamp ASC, message.creation ASC
		""",
		{"topic": topic.name},
		as_dict=True,
	)
	topic.message_count = len(messages)
	topic.first_message = messages[0].name if messages else None
	topic.last_message = messages[-1].name if messages else None
	topic.save(ignore_permissions=True)
