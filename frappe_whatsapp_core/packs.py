import hashlib
import json
import re

import frappe
from frappe.utils import now

from frappe_whatsapp_core.naming import name_by_key

PACK_KEY = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")


def install_pack(manifest):
	"""Validate and install a versioned organization solution manifest."""
	validate_manifest(manifest)
	canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":"))
	digest = hashlib.sha256(canonical.encode()).hexdigest()
	pack_key = manifest["key"]
	existing = name_by_key("WhatsApp Core Solution", pack_key)
	if existing:
		solution = frappe.get_doc("WhatsApp Core Solution", existing)
		if solution.status == "Active" and solution.manifest_sha256 != digest:
			frappe.throw("An active solution version is immutable; publish a new version")
		if solution.status == "Active" and solution.manifest_sha256 == digest:
			return {"solution": solution.name, "version": solution.version, "sha256": digest}
	else:
		solution = frappe.new_doc("WhatsApp Core Solution")
		solution.solution_key = pack_key

	solution.display_name = manifest["name"]
	solution.version = manifest["version"]
	solution.manifest_sha256 = digest
	solution.manifest = canonical
	solution.status = "Draft"
	solution.save(ignore_permissions=True)

	for workspace in manifest.get("workspaces", []):
		_upsert_workspace(solution.name, workspace)
	for case_type in manifest.get("case_types", []):
		_upsert_case_type(solution.name, manifest["version"], case_type)

	solution.status = "Active"
	solution.installed_at = now()
	solution.installed_by = frappe.session.user
	solution.save(ignore_permissions=True)
	return {"solution": solution.name, "version": solution.version, "sha256": digest}


def validate_manifest(manifest):
	for field in ("key", "name", "version"):
		if not manifest.get(field):
			frappe.throw(f"Solution manifest requires {field}")
	if not PACK_KEY.match(manifest["key"]):
		frappe.throw("Solution key must be namespaced, for example essdee.support")
	workspace_keys = {item.get("key") for item in manifest.get("workspaces", [])}
	for key in workspace_keys:
		if not key or not key.startswith(manifest["key"] + "."):
			frappe.throw(f"Workspace key {key!r} is outside the solution namespace")
	for case_type in manifest.get("case_types", []):
		key = case_type.get("key")
		if not key or not key.startswith(manifest["key"] + "."):
			frappe.throw(f"Case type key {key!r} is outside the solution namespace")
		if case_type.get("workspace") not in workspace_keys:
			frappe.throw(f"Case type {key} refers to an unknown workspace")
		stage_keys = {stage.get("key") for stage in case_type.get("stages", [])}
		if not stage_keys or case_type.get("initial_stage") not in stage_keys:
			frappe.throw(f"Case type {key} has an invalid initial stage")


def _upsert_workspace(solution_name, definition):
	record_name = name_by_key("WhatsApp Core Workspace", definition["key"])
	doc = (
		frappe.get_doc("WhatsApp Core Workspace", record_name)
		if record_name
		else frappe.new_doc("WhatsApp Core Workspace")
	)
	doc.workspace_key = definition["key"]
	doc.display_name = definition["name"]
	doc.solution = solution_name
	doc.parent_workspace = name_by_key("WhatsApp Core Workspace", definition.get("parent"))
	doc.enabled = 1
	doc.save(ignore_permissions=True)


def _upsert_case_type(solution_name, pack_version, definition):
	record_name = name_by_key("WhatsApp Core Case Type", definition["key"])
	doc = (
		frappe.get_doc("WhatsApp Core Case Type", record_name)
		if record_name
		else frappe.new_doc("WhatsApp Core Case Type")
	)
	doc.type_key = definition["key"]
	doc.display_name = definition["name"]
	doc.solution = solution_name
	doc.solution_version = pack_version
	doc.default_workspace = name_by_key("WhatsApp Core Workspace", definition["workspace"])
	doc.initial_stage_key = definition["initial_stage"]
	doc.default_priority = definition.get("default_priority", "Normal")
	doc.field_schema = json.dumps(definition.get("fields", {}), separators=(",", ":"))
	doc.enabled = 1
	doc.set("stages", [])
	for stage in definition["stages"]:
		doc.append("stages", {
			"stage_key": stage["key"],
			"display_name": stage["name"],
			"state_category": stage["state"],
			"is_terminal": 1 if stage["state"] in {"done", "cancelled"} else 0,
			"required_fields": json.dumps(stage.get("required_fields", [])),
		})
	doc.save(ignore_permissions=True)
