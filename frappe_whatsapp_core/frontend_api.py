"""Site-local API consumed by the separate PrimeVue Core application."""

from __future__ import annotations

import frappe

from frappe_whatsapp_core.campaigns import (
	authorize_campaign,
	campaign_summary,
	cancel_campaign,
	create_campaign,
	launch_campaign,
	prepare_campaign,
	revoke_campaign_authorization,
	schedule_campaign,
)
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
			"conversations",
			"templates",
			"campaigns",
			"ai-queue",
			"polls",
			"flows",
			"connectors",
			"teams",
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


@frappe.whitelist()
@require_core_access()
def campaign_workspace():
	campaigns = frappe.get_all(
		"WhatsApp Core Campaign",
		fields=["name"],
		order_by="modified desc",
		limit_page_length=500,
	)
	summaries = [campaign_summary(row.name) for row in campaigns]
	return {
		"campaigns": summaries,
		"templates": frappe.get_all(
			"WhatsApp Core Template",
			filters={"enabled": 1},
			fields=[
				"name",
				"template_name",
				"language_code",
				"category",
				"approval_status",
				"body_text",
			],
			order_by="template_name asc",
			limit_page_length=500,
		),
		"channels": frappe.get_all(
			"WhatsApp Core Channel",
			filters={"enabled": 1},
			fields=["name", "display_name", "phone_number_id"],
			order_by="display_name asc",
			limit_page_length=100,
		),
		"identities": frappe.get_all(
			"WhatsApp Core Identity",
			filters={"status": "Active"},
			fields=["name", "display_value", "normalized_value"],
			order_by="display_value asc",
			limit_page_length=1000,
		),
		"metrics": {
			"drafts": sum(
				campaign["status"] in {"Draft", "Prepared"}
				for campaign in summaries
			),
			"scheduled": sum(
				campaign["status"] == "Scheduled"
				for campaign in summaries
			),
			"delivered": sum(
				campaign["delivered_count"] + campaign["read_count"]
				for campaign in summaries
			),
		},
	}


@frappe.whitelist()
@require_core_access()
def template_catalog():
	templates = frappe.get_all(
		"WhatsApp Core Template",
		fields=[
			"name",
			"template_name",
			"language_code",
			"category",
			"approval_status",
			"enabled",
			"header_type",
			"body_text",
			"last_synced_at",
		],
		order_by="template_name asc",
		limit_page_length=500,
	)
	return {
		"templates": templates,
		"metrics": {
			"approved": sum(
				template.approval_status == "APPROVED" and template.enabled
				for template in templates
			),
			"available": sum(bool(template.enabled) for template in templates),
			"disabled": sum(not template.enabled for template in templates),
		},
	}


@frappe.whitelist()
@require_core_access(manage=True)
def create_campaign_draft(
	title: str,
	campaign_key: str,
	channel: str,
	template: str,
	description: str = "",
):
	doc = create_campaign(
		campaign_key=campaign_key,
		title=title,
		channel=channel,
		template=template,
		description=description,
		audience_source={"provider": "company_layer"},
	)
	return campaign_summary(doc.name)


@frappe.whitelist()
@require_core_access(manage=True)
def prepare_campaign_audience(campaign_name: str, recipients):
	return prepare_campaign(campaign_name, recipients)


@frappe.whitelist()
@require_core_access(manage=True)
def authorize_campaign_send(campaign_name: str, confirmation: str):
	return authorize_campaign(campaign_name, confirmation)


@frappe.whitelist()
@require_core_access(manage=True)
def revoke_campaign_send(campaign_name: str):
	return revoke_campaign_authorization(campaign_name)


@frappe.whitelist()
@require_core_access(manage=True)
def schedule_campaign_send(campaign_name: str, scheduled_for):
	return schedule_campaign(campaign_name, scheduled_for)


@frappe.whitelist()
@require_core_access(manage=True)
def launch_campaign_send(campaign_name: str):
	return launch_campaign(campaign_name)


@frappe.whitelist()
@require_core_access(manage=True)
def cancel_campaign_send(campaign_name: str):
	return cancel_campaign(campaign_name)
