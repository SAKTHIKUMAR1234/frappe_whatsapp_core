"""Site-local API consumed by the separate PrimeVue Core application."""

from __future__ import annotations

import frappe

from frappe_whatsapp_core.permissions import (
	CORE_ACCESS_ROLES,
	require_core_access,
)


@frappe.whitelist(allow_guest=True)
def bootstrap():
	user = frappe.session.user
	if user == "Guest":
		return {"authenticated": False, "site": frappe.local.site}
	roles = set(frappe.get_roles(user))
	return {
		"authenticated": True,
		"site": frappe.local.site,
		"user": {
			"name": user,
			"full_name": frappe.db.get_value("User", user, "full_name") or user,
			"roles": sorted(roles & CORE_ACCESS_ROLES),
		},
		"can_manage": bool(roles & {"System Manager", "WhatsApp Core Admin", "WhatsApp Core Manager"}),
		"modules": [
			"dashboard",
			"templates",
			"campaigns",
			"ai-queue",
			"polls",
			"flows",
			"connectors",
			"health",
			"settings",
		],
	}


@frappe.whitelist()
@require_core_access()
def dashboard():
	return {
		"metrics": {
			"configured_flows": frappe.db.count("WhatsApp Core Flow"),
			"active_flows": frappe.db.count(
				"WhatsApp Core Flow",
				{"status": "Published", "enabled": 1},
			),
			"running_instances": frappe.db.count(
				"WhatsApp Core Flow Instance",
				{"status": ["in", ["Running", "Waiting"]]},
			),
			"failed_steps": frappe.db.count(
				"WhatsApp Core Flow Step Run",
				{"status": "Failed"},
			),
		},
		"lifecycle": {
			"draft": frappe.db.count(
				"WhatsApp Core Flow",
				{"status": "Draft"},
			),
			"published": frappe.db.count(
				"WhatsApp Core Flow",
				{"status": "Published"},
			),
			"waiting": frappe.db.count(
				"WhatsApp Core Flow Instance",
				{"status": "Waiting"},
			),
			"completed": frappe.db.count(
				"WhatsApp Core Flow Instance",
				{"status": "Completed"},
			),
		},
		"recent_flows": frappe.get_list(
			"WhatsApp Core Flow",
			fields=["name", "title", "status", "active_version", "modified"],
			order_by="modified desc",
			limit_page_length=6,
		),
	}


@frappe.whitelist()
@require_core_access()
def list_flows():
	return frappe.get_list(
		"WhatsApp Core Flow",
		fields=[
			"name",
			"flow_key",
			"title",
			"description",
			"status",
			"enabled",
			"active_version",
			"modified",
		],
		order_by="modified desc",
		limit_page_length=500,
	)


@frappe.whitelist()
@require_core_access(manage=True)
def create_starter_flow(title, flow_key):
	from frappe_whatsapp_core.flow_templates import create_from_template

	return create_from_template(
		template_key="branched_review",
		flow_key=flow_key,
		title=title,
	)
