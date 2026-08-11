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

FLOW_BUILDER_ROLES = {
	"System Manager",
	"WhatsApp Flow User",
	"WhatsApp Manager",
}

CORE_APP_ROLES = CORE_ACCESS_ROLES | FLOW_BUILDER_ROLES

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


def require_flow_builder_access(*, manage: bool = False):
	"""Authorize visual-flow authors, or managers for approval/publication actions."""

	def decorator(method):
		@wraps(method)
		def guarded(*args, **kwargs):
			if frappe.session.user == "Guest":
				frappe.throw("Authentication required", frappe.AuthenticationError)

			required_roles = CORE_MANAGEMENT_ROLES if manage else FLOW_BUILDER_ROLES
			if not (set(frappe.get_roles()) & required_roles):
				message = (
					"WhatsApp Flow approval access is required"
					if manage
					else "WhatsApp Flow authoring access is required"
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
	assigned_team, assigned_user, remote_identity = frappe.db.get_value(
		"WhatsApp Core Conversation",
		conversation,
		["assigned_team", "assigned_user", "remote_identity"],
	)
	assert_identity_team_access(remote_identity)
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
	contact_condition, contact_values = identity_team_condition(f"{alias}.remote_identity")
	conditions.append(contact_condition)
	values.update(contact_values)
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


def assert_identity_team_access(identity: str) -> None:
	"""Allow uncategorized contacts, or contacts in one of the user's teams."""
	roles = set(frappe.get_roles())
	if roles & CORE_MANAGEMENT_ROLES:
		return
	row = frappe.db.sql(
		"""
		SELECT
			COUNT(DISTINCT team_contact.parent) AS category_count,
			COUNT(DISTINCT member.parent) AS matching_team_count
		FROM `tabWhatsApp Core Team Contact` AS team_contact
		JOIN `tabWhatsApp Core Team` AS team
			ON team.name = team_contact.parent AND team.enabled = 1
		LEFT JOIN `tabWhatsApp Core Team Member` AS member
			ON member.parent = team.name
			AND member.parenttype = 'WhatsApp Core Team'
			AND member.parentfield = 'members'
			AND member.enabled = 1
			AND member.user = %(user)s
		WHERE team_contact.parenttype = 'WhatsApp Core Team'
			AND team_contact.parentfield = 'contacts'
			AND team_contact.enabled = 1
			AND team_contact.identity = %(identity)s
		""",
		{"identity": identity, "user": frappe.session.user},
		as_dict=True,
	)[0]
	if int(row.category_count or 0) and not int(row.matching_team_count or 0):
		frappe.throw("This contact is assigned to another team", frappe.PermissionError)


def identity_team_condition(identity_expression: str) -> tuple[str, dict]:
	"""Return a SQL visibility condition for a Core identity expression."""
	roles = set(frappe.get_roles())
	if roles & CORE_MANAGEMENT_ROLES:
		return "1 = 1", {}
	if not all(character.isalnum() or character in "_.`" for character in identity_expression):
		frappe.throw("Invalid identity expression", frappe.ValidationError)
	return (
		f"""(
			NOT EXISTS (
				SELECT 1
				FROM `tabWhatsApp Core Team Contact` AS contact_scope
				JOIN `tabWhatsApp Core Team` AS contact_team
					ON contact_team.name = contact_scope.parent AND contact_team.enabled = 1
				WHERE contact_scope.parenttype = 'WhatsApp Core Team'
					AND contact_scope.parentfield = 'contacts'
					AND contact_scope.enabled = 1
					AND contact_scope.identity = {identity_expression}
			)
			OR EXISTS (
				SELECT 1
				FROM `tabWhatsApp Core Team Contact` AS visible_contact
				JOIN `tabWhatsApp Core Team` AS visible_team
					ON visible_team.name = visible_contact.parent AND visible_team.enabled = 1
				JOIN `tabWhatsApp Core Team Member` AS visible_member
					ON visible_member.parent = visible_team.name
					AND visible_member.parenttype = 'WhatsApp Core Team'
					AND visible_member.parentfield = 'members'
					AND visible_member.enabled = 1
				WHERE visible_contact.parenttype = 'WhatsApp Core Team'
					AND visible_contact.parentfield = 'contacts'
					AND visible_contact.enabled = 1
					AND visible_contact.identity = {identity_expression}
					AND visible_member.user = %(contact_scope_user)s
			)
		)""",
		{"contact_scope_user": frappe.session.user},
	)
