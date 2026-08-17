import json
import uuid

import frappe
from frappe.utils import now

from frappe_whatsapp_core.naming import resolve_name


def create_case(case_type_key, title, field_values=None, conversation=None, origin_message=None):
	case_type_name = resolve_name("WhatsApp Core Case Type", case_type_key)
	if not case_type_name:
		frappe.throw("Case type was not found", frappe.DoesNotExistError)
	case_type = frappe.get_doc("WhatsApp Core Case Type", case_type_name)
	if not case_type.enabled:
		frappe.throw("Case type is disabled")
	stage = _stage(case_type, case_type.initial_stage_key)
	values = field_values or {}
	_validate_required(values, stage.required_fields)
	doc = frappe.get_doc({
		"doctype": "WhatsApp Core Case",
		"case_key": str(uuid.uuid4()),
		"case_type": case_type.name,
		"case_type_version": case_type.solution_version,
		"title": title,
		"origin_conversation": conversation,
		"origin_message": origin_message,
		"workspace": case_type.default_workspace,
		"stage_key": stage.stage_key,
		"state_category": stage.state_category,
		"priority": case_type.default_priority or "Normal",
		"field_values": json.dumps(values, separators=(",", ":")),
		"opened_at": now(),
	})
	doc.insert(ignore_permissions=True)
	return doc


def transition_case(case_name, stage_key, values=None):
	case = frappe.get_doc("WhatsApp Core Case", case_name)
	case_type = frappe.get_doc("WhatsApp Core Case Type", case.case_type)
	if case.case_type_version != case_type.solution_version:
		frappe.throw("Pinned case type version is no longer installed")
	stage = _stage(case_type, stage_key)
	merged = json.loads(case.field_values or "{}")
	merged.update(values or {})
	_validate_required(merged, stage.required_fields)
	case.stage_key = stage.stage_key
	case.state_category = stage.state_category
	case.field_values = json.dumps(merged, separators=(",", ":"))
	if stage.is_terminal:
		case.closed_at = now()
	case.save(ignore_permissions=True)
	return case


def _stage(case_type, stage_key):
	for stage in case_type.stages:
		if stage.stage_key == stage_key:
			return stage
	frappe.throw(f"Unknown stage {stage_key}")


def _validate_required(values, required_fields):
	required = json.loads(required_fields or "[]")
	missing = [field for field in required if values.get(field) in (None, "")]
	if missing:
		frappe.throw(f"Missing required fields: {', '.join(missing)}")
