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


def assert_conversation_access(conversation: str) -> None:
	"""Restrict operators to unassigned, directly assigned, or team-assigned chats."""
	if not frappe.db.exists("WhatsApp Core Conversation", conversation):
		frappe.throw("Conversation not found", frappe.DoesNotExistError)
	roles = set(frappe.get_roles())
	if roles & CORE_MANAGEMENT_ROLES:
		return
	assigned_team, assigned_user = frappe.db.get_value(
		"WhatsApp Core Conversation",
		conversation,
		["assigned_team", "assigned_user"],
	)
	if assigned_user == frappe.session.user:
		return
	if assigned_team and frappe.db.exists(
		"WhatsApp Core Team Member",
		{
			"parent": assigned_team,
			"user": frappe.session.user,
			"enabled": 1,
		},
	):
		return
	if not assigned_team and not assigned_user:
		return
	frappe.throw("You are not assigned to this conversation", frappe.PermissionError)


def conversation_conditions(alias: str = "conversation") -> tuple[list[str], dict]:
	"""Return parameterized SQL scope conditions matching ``assert_conversation_access``."""
	if not alias.replace("_", "").isalnum():
		frappe.throw("Invalid conversation table alias", frappe.ValidationError)
	conditions = ["1 = 1"]
	values = {}
	roles = set(frappe.get_roles())
	if roles & CORE_MANAGEMENT_ROLES:
		return conditions, values
	teams = frappe.get_all(
		"WhatsApp Core Team Member",
		filters={"user": frappe.session.user, "enabled": 1},
		pluck="parent",
	)
	values["current_user"] = frappe.session.user
	if teams:
		values["teams"] = tuple(teams)
		conditions.append(
			f"""(
				(
					COALESCE({alias}.assigned_team, '') = ''
					AND COALESCE({alias}.assigned_user, '') = ''
				)
				OR {alias}.assigned_team IN %(teams)s
				OR {alias}.assigned_user = %(current_user)s
			)"""
		)
	else:
		conditions.append(
			f"""(
				(
					COALESCE({alias}.assigned_team, '') = ''
					AND COALESCE({alias}.assigned_user, '') = ''
				)
				OR {alias}.assigned_user = %(current_user)s
			)"""
		)
	return conditions, values
