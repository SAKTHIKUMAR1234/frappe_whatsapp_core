"""Reusable authorization decorators for Core API boundaries."""

from __future__ import annotations

from functools import wraps
from inspect import signature

import frappe

CORE_ACCESS_ROLES = {
	"System Manager",
	"WhatsApp User",
	"WhatsApp Manager",
}

CORE_MANAGEMENT_ROLES = {
	"System Manager",
	"WhatsApp Manager",
}


def require_core_access(*, manage: bool = False):
	"""Authorize a site user before entering a company-facing API method."""

	def decorator(method):
		@wraps(method)
		def guarded(*args, **kwargs):
			if frappe.session.user == "Guest":
				frappe.throw("Authentication required", frappe.AuthenticationError)

			required_roles = CORE_MANAGEMENT_ROLES if manage else CORE_ACCESS_ROLES
			if not (set(frappe.get_roles()) & required_roles):
				message = (
					"WhatsApp Core management access is required"
					if manage
					else "WhatsApp Core access is required"
				)
				frappe.throw(message, frappe.PermissionError)

			return method(*args, **kwargs)

		return guarded

	return decorator


def require_document_permission(
	doctype: str,
	permission_type: str,
	*,
	name_argument: str,
):
	"""Apply Frappe document permissions without repeating checks in endpoints."""

	def decorator(method):
		method_signature = signature(method)

		@wraps(method)
		def guarded(*args, **kwargs):
			bound_arguments = method_signature.bind_partial(*args, **kwargs)
			document_name = bound_arguments.arguments.get(name_argument)
			if document_name is None:
				frappe.throw(f"Missing required argument: {name_argument}")
			frappe.has_permission(
				doctype,
				permission_type,
				document_name,
				throw=True,
			)
			return method(*args, **kwargs)

		return guarded

	return decorator
