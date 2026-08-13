"""Operator entry points for app-owned legacy WhatsApp migrations."""

from __future__ import annotations

import importlib

import frappe

from frappe_whatsapp_core.permissions import require_core_access

HOOK_NAME = "whatsapp_core_legacy_migrations"


@frappe.whitelist()
@require_core_access(manage=True)
def preview_installed_legacy_whatsapp() -> dict:
	"""Preview every installed business-app migration without writing data."""
	results = [_adapter_call(path, "preview_legacy_whatsapp") for path in _adapter_paths()]
	return {
		"adapters": results,
		"migration_ready": bool(results) and all(result.get("migration_ready") for result in results),
		"source_is_read_only": True,
	}


@frappe.whitelist()
@require_core_access(manage=True)
def migrate_installed_legacy_whatsapp(
	batch_size: int = 500,
	commit_every_batch: int = 1,
) -> dict:
	"""Run all registered app migrations with deterministic, resumable keys."""
	paths = _adapter_paths()
	if not paths:
		frappe.throw(
			"No installed app registered a WhatsApp Core legacy migration",
			frappe.DoesNotExistError,
		)
	results = [
		_adapter_call(
			path,
			"migrate_legacy_whatsapp",
			batch_size=batch_size,
			commit_every_batch=commit_every_batch,
		)
		for path in paths
	]
	return {
		"adapters": results,
		"reconciliation_ok": all(result.get("reconciliation_ok") for result in results),
		"source_is_read_only": True,
		"rerun_safe": True,
	}


def _adapter_paths() -> list[str]:
	paths = []
	for value in frappe.get_hooks(HOOK_NAME) or []:
		values = value if isinstance(value, (list, tuple)) else [value]
		for path in values:
			path = str(path or "").strip()
			if path and path not in paths:
				paths.append(path)
	return paths


def _adapter_call(path: str, method: str, **kwargs) -> dict:
	module = importlib.import_module(path)
	callable_method = getattr(module, method, None)
	if not callable(callable_method):
		frappe.throw(
			f"Legacy migration adapter {path} does not define {method}",
			frappe.ValidationError,
		)
	result = callable_method(**kwargs)
	return {
		"adapter": path,
		**(result or {}),
	}
