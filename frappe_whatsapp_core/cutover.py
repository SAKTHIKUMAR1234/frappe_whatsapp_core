"""Guarded operator helpers for a clean WhatsApp Core cutover.

These helpers are intentionally not whitelisted.  They are bench-only tools for
operators who have already taken a site backup and need to remove runtime/test
data without touching transport credentials or installed solution metadata.
"""

from __future__ import annotations

import frappe
from frappe.utils import cint


CORE_RUNTIME_DOCTYPES = (
	"WhatsApp Core Group Receipt",
	"WhatsApp Core Group Member",
	"WhatsApp Core Campaign Recipient",
	"WhatsApp Core Flow Step Run",
	"WhatsApp Core Flow Response",
	"WhatsApp Core Flow Instance",
	"WhatsApp Core Topic Message",
	"WhatsApp Core Conversation Topic",
	"WhatsApp Core Message Read",
	"WhatsApp Core Message Bookmark",
	"WhatsApp Core Message Category Assignment",
	"WhatsApp Core Message Insight",
	"WhatsApp Core Conversation Read",
	"WhatsApp Core Contact Summary",
	"WhatsApp Core Party Binding",
	"WhatsApp Core Identity Link",
	"WhatsApp Core Team Contact",
	"WhatsApp Core Team Member",
	"WhatsApp Core Handler Run",
	"WhatsApp Core Call",
	"WhatsApp Core Case",
	"WhatsApp Core Group",
	"WhatsApp Core Campaign",
	"WhatsApp Core Flow Trigger",
	"WhatsApp Core Flow Version",
	"WhatsApp Core Flow",
	"WhatsApp Core Meta Flow Exchange",
	"WhatsApp Core Summary Period",
	"WhatsApp Core MCP Invocation",
	"WhatsApp Core Message",
	"WhatsApp Core Conversation",
	"WhatsApp Core Team",
	"WhatsApp Core Template",
	"WhatsApp Core Identity",
	"WhatsApp Core Event",
)

LEGACY_RUNTIME_DOCTYPES = (
	"WhatsApp Poll Response",
	"WhatsApp AI Escalation",
	"WhatsApp AI Bot Log",
	"WhatsApp Webhook Log",
	"AI WhatsApp Queue",
	"Personal WhatsApp Queue",
	"WhatsApp Bulk Message",
	"WhatsApp Poll",
	"Template Wiring",
	"WhatsApp Message",
	"WhatsApp Template",
	"WhatsApp Contact",
	"Personal WhatsApp Account",
	"WhatsApp Account",
)

TEST_USERS = (
	"whatsapp.e2e@local.test",
	"whatsapp.reader@local.test",
)


def clean_cutover_data(expected_site: str, execute: int = 0) -> dict:
	"""Remove runtime data while preserving credentials and product metadata.

	The caller must pass the exact active site name and explicitly set
	``execute=1``.  A call without execute returns the same count plan without
	writing anything.
	"""
	expected_site = str(expected_site or "").strip()
	if not expected_site or expected_site != frappe.local.site:
		frappe.throw(
			f"Cutover target mismatch: active site is {frappe.local.site}",
			frappe.ValidationError,
		)

	core_doctypes = [doctype for doctype in CORE_RUNTIME_DOCTYPES if _doctype_exists(doctype)]
	legacy_doctypes = [doctype for doctype in LEGACY_RUNTIME_DOCTYPES if _doctype_exists(doctype)]
	core_files = (
		frappe.get_all(
			"File",
			filters={"attached_to_doctype": ["like", "WhatsApp Core %"]},
			pluck="name",
			limit_page_length=100000,
		)
		if _doctype_exists("File")
		else []
	)
	preserved_channels = (
		set(
			frappe.get_all(
				"WhatsApp Core Hub Account",
				filters={"channel": ["is", "set"]},
				pluck="channel",
				limit_page_length=1000,
			)
		)
		if _doctype_exists("WhatsApp Core Hub Account")
		else set()
	)
	all_channels = (
		set(
			frappe.get_all(
				"WhatsApp Core Channel",
				pluck="name",
				limit_page_length=100000,
			)
		)
		if _doctype_exists("WhatsApp Core Channel")
		else set()
	)
	test_channels = sorted(all_channels - preserved_channels)

	before = {
		**{doctype: frappe.db.count(doctype) for doctype in core_doctypes},
		**{doctype: frappe.db.count(doctype) for doctype in legacy_doctypes},
		"File (WhatsApp Core attachments)": len(core_files),
		"WhatsApp Core Channel (unreferenced)": len(test_channels),
		"User (known WhatsApp tests)": sum(
			bool(frappe.db.exists("User", user)) for user in TEST_USERS
		),
	}
	result = {
		"site": frappe.local.site,
		"execute": bool(cint(execute)),
		"before": before,
		"preserved": {
			"settings": ["WhatsApp Core Settings", "SD WhatsApp Hub Settings"],
			"channels": sorted(preserved_channels),
			"configuration": [
				"WhatsApp Core Identity Source",
				"WhatsApp Core Message Category",
				"WhatsApp Core Solution",
				"WhatsApp Core Workspace",
				"WhatsApp Core Case Type",
			],
			"legacy_file_metadata": True,
		},
	}
	if not cint(execute):
		return result

	try:
		for doctype in core_doctypes:
			frappe.db.delete(doctype)
		for doctype in legacy_doctypes:
			frappe.db.delete(doctype)
		for name in core_files:
			if frappe.db.exists("File", name):
				frappe.delete_doc("File", name, ignore_permissions=True, force=True)
		if test_channels:
			frappe.db.delete("WhatsApp Core Channel", {"name": ["in", test_channels]})
		for user in TEST_USERS:
			if frappe.db.exists("User", user):
				frappe.delete_doc("User", user, ignore_permissions=True, force=True)
		frappe.db.commit()
	except Exception:
		frappe.db.rollback()
		raise

	result["after"] = {
		**{doctype: frappe.db.count(doctype) for doctype in core_doctypes},
		**{doctype: frappe.db.count(doctype) for doctype in legacy_doctypes},
		"File (WhatsApp Core attachments)": frappe.db.count(
			"File", {"attached_to_doctype": ["like", "WhatsApp Core %"]}
		),
		"WhatsApp Core Channel (unreferenced)": (
			frappe.db.count(
				"WhatsApp Core Channel", {"name": ["in", test_channels]}
			)
			if test_channels
			else 0
		),
		"User (known WhatsApp tests)": sum(
			bool(frappe.db.exists("User", user)) for user in TEST_USERS
		),
	}
	return result


def _doctype_exists(doctype: str) -> bool:
	return bool(
		frappe.db.exists("DocType", doctype) and frappe.db.table_exists(doctype)
	)
