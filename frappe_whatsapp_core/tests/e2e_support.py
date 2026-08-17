"""Developer-only data preparation for the local browser hardening suite."""

from __future__ import annotations

import csv
from pathlib import Path

import frappe
from frappe.utils import cint, now_datetime


def ensure_local_campaign_audience(count: int = 18_000) -> dict:
	"""Provision a reusable local audience without calling production services."""
	count = cint(count)
	if (
		frappe.local.site != "sales-prod.site"
		or not cint(frappe.conf.developer_mode)
		or frappe.session.user != "Administrator"
	):
		frappe.throw(
			"Local campaign fixtures require Administrator on the developer sales-prod.site",
			frappe.PermissionError,
		)
	if count < 1 or count > 20_000:
		frappe.throw("Local campaign fixture count must be between 1 and 20,000")

	now = now_datetime()
	fields = [
		"name",
		"identity_key",
		"identity_type",
		"identifier_type",
		"normalized_value",
		"display_value",
		"provider",
		"status",
		"resolution_status",
		"owner",
		"creation",
		"modified",
		"modified_by",
	]
	values = []
	names = []
	for index in range(1, count + 1):
		name = f"e2e18k{index:05d}"
		names.append(name)
		phone = f"9188{index:08d}"
		values.append([
			name,
			f"local:e2e:campaign:{index:05d}",
			"WhatsApp",
			"Phone",
			phone,
			f"Local Campaign Recipient {index:05d}",
			"local-e2e",
			"Active",
			"Unresolved",
			"Administrator",
			now,
			now,
			"Administrator",
		])
	frappe.db.bulk_insert(
		"WhatsApp Core Identity",
		fields=fields,
		values=values,
		ignore_duplicates=True,
		chunk_size=2_000,
	)
	available = frappe.db.count(
		"WhatsApp Core Identity",
		{"name": ["in", names], "identity_type": "WhatsApp", "status": "Active"},
	)
	if available != count:
		frappe.throw(f"Expected {count} local campaign identities, found {available}")
	frappe.db.commit()

	output_root = Path(frappe.get_app_path("frappe_whatsapp_core")).parent / "output" / "performance"
	output_root.mkdir(parents=True, exist_ok=True)
	output_path = output_root / "e2e-audience-18000.csv"
	with output_path.open("w", encoding="utf-8", newline="") as handle:
		writer = csv.writer(handle)
		writer.writerow(["identity"])
		writer.writerows([name] for name in names)
	return {"count": count, "path": str(output_path)}
