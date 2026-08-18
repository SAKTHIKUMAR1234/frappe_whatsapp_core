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

# Dedicated machine roles remain the least-privilege deployment option. A
# WhatsApp Manager API credential is also a valid unified transport identity so
# an operator can configure one stable credential across ingress, templates,
# flows, and result callbacks without creating parallel identities.
TRANSPORT_SERVICE_ROLE = "WhatsApp Core Transport Service"
TEMPLATE_SERVICE_ROLE = "WhatsApp Core Template Service"
FLOW_SERVICE_ROLE = "WhatsApp Core Flow Service"
TRANSPORT_CAPABILITY_ROLES = {
	"ingress": TRANSPORT_SERVICE_ROLE,
	"template": TEMPLATE_SERVICE_ROLE,
	"flow": FLOW_SERVICE_ROLE,
}


def _permission_user(user: str | None = None) -> str:
	return user or frappe.session.user or "Guest"


def _conversation_scope_sql(alias: str, user: str) -> str:
	"""Return the canonical row-level conversation scope for a specific user.

	This expression is intentionally self-contained so Frappe can append it to
	generic ``/api/resource`` queries. API methods use the equivalent parameterized
	conditions below; both paths must enforce the same team/contact boundary.
	"""
	if user == "Administrator" or set(frappe.get_roles(user)) & CORE_MANAGEMENT_ROLES:
		return "1 = 1"
	if user == "Guest":
		return "1 = 0"
	escaped_user = frappe.db.escape(user)
	return f"""(
		(
			(
				EXISTS (
					SELECT 1
					FROM `tabWhatsApp Core Team Member` user_team
					INNER JOIN `tabWhatsApp Core Team` enabled_user_team
						ON enabled_user_team.name = user_team.parent
						AND enabled_user_team.enabled = 1
					WHERE user_team.parenttype = 'WhatsApp Core Team'
						AND user_team.parentfield = 'members'
						AND user_team.enabled = 1
						AND user_team.user = {escaped_user}
				)
				AND EXISTS (
					SELECT 1
					FROM `tabWhatsApp Core Team Contact` visible_contact
					INNER JOIN `tabWhatsApp Core Team` visible_contact_team
						ON visible_contact_team.name = visible_contact.parent
						AND visible_contact_team.enabled = 1
					INNER JOIN `tabWhatsApp Core Team Member` visible_member
						ON visible_member.parent = visible_contact.parent
						AND visible_member.parenttype = 'WhatsApp Core Team'
						AND visible_member.parentfield = 'members'
						AND visible_member.enabled = 1
						AND visible_member.user = {escaped_user}
					WHERE visible_contact.parenttype = 'WhatsApp Core Team'
						AND visible_contact.parentfield = 'contacts'
						AND visible_contact.enabled = 1
						AND visible_contact.identity = {alias}.remote_identity
				)
			)
			OR (
				NOT EXISTS (
					SELECT 1
					FROM `tabWhatsApp Core Team Member` user_team
					INNER JOIN `tabWhatsApp Core Team` enabled_user_team
						ON enabled_user_team.name = user_team.parent
						AND enabled_user_team.enabled = 1
					WHERE user_team.parenttype = 'WhatsApp Core Team'
						AND user_team.parentfield = 'members'
						AND user_team.enabled = 1
						AND user_team.user = {escaped_user}
				)
				AND NOT EXISTS (
				SELECT 1
				FROM `tabWhatsApp Core Team Contact` scoped_contact
				INNER JOIN `tabWhatsApp Core Team` scoped_contact_team
					ON scoped_contact_team.name = scoped_contact.parent
					AND scoped_contact_team.enabled = 1
				WHERE scoped_contact.parenttype = 'WhatsApp Core Team'
					AND scoped_contact.parentfield = 'contacts'
					AND scoped_contact.enabled = 1
					AND scoped_contact.identity = {alias}.remote_identity
			)
			)
		)
		AND (
			(
				COALESCE({alias}.assigned_team, '') = ''
				AND COALESCE({alias}.assigned_user, '') = ''
			)
			OR {alias}.assigned_user = {escaped_user}
			OR EXISTS (
				SELECT 1
				FROM `tabWhatsApp Core Team Member` assigned_member
				WHERE assigned_member.parent = {alias}.assigned_team
					AND assigned_member.parenttype = 'WhatsApp Core Team'
					AND assigned_member.parentfield = 'members'
					AND assigned_member.enabled = 1
					AND assigned_member.user = {escaped_user}
			)
		)
	)"""


def conversation_permission_query(user: str | None = None, **_kwargs) -> str:
	return _conversation_scope_sql("`tabWhatsApp Core Conversation`", _permission_user(user))


def team_permission_query(user: str | None = None, **_kwargs) -> str:
	user = _permission_user(user)
	if user == "Administrator" or set(frappe.get_roles(user)) & CORE_MANAGEMENT_ROLES:
		return "1 = 1"
	if user == "Guest":
		return "1 = 0"
	escaped_user = frappe.db.escape(user)
	return f"""EXISTS (
		SELECT 1 FROM `tabWhatsApp Core Team Member` scoped_member
		WHERE scoped_member.parent = `tabWhatsApp Core Team`.name
			AND scoped_member.parenttype = 'WhatsApp Core Team'
			AND scoped_member.parentfield = 'members'
			AND scoped_member.enabled = 1
			AND scoped_member.user = {escaped_user}
	)"""


def template_permission_query(user: str | None = None, **_kwargs) -> str:
	"""Expose only sendable templates to operators; managers may audit every state."""
	user = _permission_user(user)
	if user == "Administrator" or set(frappe.get_roles(user)) & CORE_MANAGEMENT_ROLES:
		return "1 = 1"
	if user == "Guest":
		return "1 = 0"
	return """`tabWhatsApp Core Template`.enabled = 1
		AND `tabWhatsApp Core Template`.approval_status = 'APPROVED'
		AND COALESCE(`tabWhatsApp Core Template`.account_name, '') != ''
		AND COALESCE(`tabWhatsApp Core Template`.channel, '') != ''"""


def has_scoped_template_permission(doc, ptype="read", user=None, **_kwargs):
	user = _permission_user(user)
	if user == "Administrator" or set(frappe.get_roles(user)) & CORE_MANAGEMENT_ROLES:
		return True
	if ptype != "read" or user == "Guest":
		return False
	return bool(
		doc.get("enabled")
		and doc.get("approval_status") == "APPROVED"
		and doc.get("account_name")
		and doc.get("channel")
	)


def has_scoped_team_permission(doc, ptype="read", user=None, **_kwargs):
	user = _permission_user(user)
	if user == "Administrator" or set(frappe.get_roles(user)) & CORE_MANAGEMENT_ROLES:
		return True
	if ptype != "read":
		return False
	return bool(
		frappe.db.exists(
			"WhatsApp Core Team Member",
			{
				"parent": doc.name,
				"parenttype": "WhatsApp Core Team",
				"parentfield": "members",
				"enabled": 1,
				"user": user,
			},
		)
	)


def _linked_conversation_permission_query(
	doctype: str,
	conversation_field: str,
	user: str | None = None,
) -> str:
	source = f"`tab{doctype}`"
	scope = _conversation_scope_sql("scoped_conversation", _permission_user(user))
	return f"""EXISTS (
		SELECT 1 FROM `tabWhatsApp Core Conversation` scoped_conversation
		WHERE scoped_conversation.name = {source}.`{conversation_field}`
			AND {scope}
	)"""


def message_permission_query(user: str | None = None, **_kwargs) -> str:
	return _linked_conversation_permission_query(
		"WhatsApp Core Message", "conversation", user
	)


def conversation_read_permission_query(user: str | None = None, **_kwargs) -> str:
	return _linked_conversation_permission_query(
		"WhatsApp Core Conversation Read", "conversation", user
	)


def message_read_permission_query(user: str | None = None, **_kwargs) -> str:
	return _linked_conversation_permission_query(
		"WhatsApp Core Message Read", "conversation", user
	)


def call_permission_query(user: str | None = None, **_kwargs) -> str:
	return _linked_conversation_permission_query(
		"WhatsApp Core Call", "conversation", user
	)


def _has_conversation_scope(conversation: str | None, user: str | None = None) -> bool:
	user = _permission_user(user)
	if not conversation:
		return False
	if user == "Administrator" or set(frappe.get_roles(user)) & CORE_MANAGEMENT_ROLES:
		return True
	scope = _conversation_scope_sql("scoped_conversation", user)
	return bool(
		frappe.db.sql(
			f"""SELECT 1
			FROM `tabWhatsApp Core Conversation` scoped_conversation
			WHERE scoped_conversation.name = %s AND {scope}
			LIMIT 1""",
			(conversation,),
		)
	)


def has_scoped_conversation_permission(doc, ptype="read", user=None, **_kwargs):
	return _has_conversation_scope(doc.name, user)


def has_scoped_message_permission(doc, ptype="read", user=None, **_kwargs):
	return _has_conversation_scope(doc.get("conversation"), user)


def has_scoped_conversation_read_permission(doc, ptype="read", user=None, **_kwargs):
	return _has_conversation_scope(doc.get("conversation"), user)


def has_scoped_message_read_permission(doc, ptype="read", user=None, **_kwargs):
	return _has_conversation_scope(doc.get("conversation"), user)


def has_scoped_call_permission(doc, ptype="read", user=None, **_kwargs):
	return _has_conversation_scope(doc.get("conversation"), user)


def assert_call_access(call_id: str) -> None:
	"""Apply the inbox assignment boundary to one provider call."""
	conversation = frappe.db.get_value(
		"WhatsApp Core Call", {"call_id": str(call_id or "").strip()}, "conversation"
	)
	if not conversation:
		frappe.throw("Call not found or outside your access scope", frappe.PermissionError)
	assert_conversation_access(conversation)


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


def require_system_manager():
	"""Protect installation/configuration APIs from operational manager roles."""

	def decorator(method):
		@wraps(method)
		def guarded(*args, **kwargs):
			if frappe.session.user == "Guest":
				frappe.throw("Authentication required", frappe.AuthenticationError)
			if "System Manager" not in set(frappe.get_roles()):
				frappe.throw("System Manager access is required", frappe.PermissionError)
			return method(*args, **kwargs)

		return guarded

	return decorator


def require_transport_access(capability: str | None = "ingress"):
	"""Authorize a WhatsApp Manager or a capability-scoped service identity.

	Administrator remains available for local recovery and test fixtures. A plain
	System Manager is intentionally rejected; the user must explicitly hold the
	WhatsApp Manager role or an exact dedicated transport role.
	"""
	if capability is not None and capability not in TRANSPORT_CAPABILITY_ROLES:
		raise ValueError(f"Unsupported transport capability: {capability}")

	def decorator(method):
		@wraps(method)
		def guarded(*args, **kwargs):
			user = frappe.session.user
			if user == "Guest":
				frappe.throw("Authentication required", frappe.AuthenticationError)
			roles = set(frappe.get_roles(user))
			if (
				user != "Administrator"
				and "WhatsApp Manager" not in roles
				and not is_dedicated_transport_user(user, capability=capability)
			):
				frappe.throw(
					"WhatsApp Core machine service access is required for this capability",
					frappe.PermissionError,
				)
			_suppress_machine_session_persistence()
			return method(*args, **kwargs)

		return guarded

	return decorator


def _suppress_machine_session_persistence() -> None:
	"""Keep concurrent service requests away from the shared User activity row.

	Frappe commits the endpoint transaction before updating ``tabSessions`` and
	``User.last_active``. API-token requests do not need that interactive-session
	bookkeeping, and concurrent relay batches otherwise contend on the same service
	user after their business work has already committed. Restrict the optimization
	to real HTTP requests so direct calls from patches, tests, and the console retain
	their surrounding session object.
	"""
	if getattr(frappe.local, "request", None) is not None:
		frappe.local.session_obj = None


def is_dedicated_transport_user(user: str, *, capability: str | None = "ingress") -> bool:
	"""Return whether ``user`` is an enabled, service-only Website User.

	Checking the User document on every machine request prevents a human or Desk
	identity from becoming a relay principal merely by acquiring the transport
	role through a direct assignment or role profile.
	"""
	if not user or not frappe.db.exists("User", user):
		return False
	identity = frappe.get_doc("User", user)
	direct_roles = {row.role for row in (identity.roles or [])}
	all_transport_roles = set(TRANSPORT_CAPABILITY_ROLES.values())
	if capability == "all":
		allowed_role_sets = {frozenset(all_transport_roles)}
	elif capability is not None:
		allowed_role_sets = {
			frozenset({TRANSPORT_CAPABILITY_ROLES[capability]}),
			frozenset(all_transport_roles),
		}
	else:
		allowed_role_sets = {
			frozenset({role}) for role in all_transport_roles
		} | {frozenset(all_transport_roles)}
	return bool(
		identity.enabled
		and identity.user_type == "Website User"
		and not getattr(identity, "role_profile_name", None)
		and frozenset(direct_roles) in allowed_role_sets
	)


def current_transport_capability(user: str | None = None) -> str:
	"""Return the action family assigned to one validated transport user."""
	user = user or frappe.session.user
	if user == "Administrator" or "WhatsApp Manager" in set(frappe.get_roles(user)):
		return "all"
	if not is_dedicated_transport_user(user, capability=None):
		return ""
	direct_roles = {row.role for row in frappe.get_doc("User", user).roles or []}
	if direct_roles == set(TRANSPORT_CAPABILITY_ROLES.values()):
		return "all"
	return next(
		(capability for capability, role in TRANSPORT_CAPABILITY_ROLES.items() if role in direct_roles),
		"",
	)


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
	"""Require the user's team state to match the contact's team state."""
	roles = set(frappe.get_roles())
	if roles & CORE_MANAGEMENT_ROLES:
		return
	row = frappe.db.sql(
		"""
		SELECT
			EXISTS (
				SELECT 1
				FROM `tabWhatsApp Core Team Member` user_team
				JOIN `tabWhatsApp Core Team` team
					ON team.name = user_team.parent AND team.enabled = 1
				WHERE user_team.parenttype = 'WhatsApp Core Team'
					AND user_team.parentfield = 'members'
					AND user_team.enabled = 1
					AND user_team.user = %(user)s
			) AS has_user_team,
			EXISTS (
				SELECT 1
				FROM `tabWhatsApp Core Team Contact` team_contact
				JOIN `tabWhatsApp Core Team` team
					ON team.name = team_contact.parent AND team.enabled = 1
				WHERE team_contact.parenttype = 'WhatsApp Core Team'
					AND team_contact.parentfield = 'contacts'
					AND team_contact.enabled = 1
					AND team_contact.identity = %(identity)s
			) AS has_contact_team,
			EXISTS (
				SELECT 1
				FROM `tabWhatsApp Core Team Contact` team_contact
				JOIN `tabWhatsApp Core Team` team
					ON team.name = team_contact.parent AND team.enabled = 1
				JOIN `tabWhatsApp Core Team Member` member
					ON member.parent = team_contact.parent
					AND member.parenttype = 'WhatsApp Core Team'
					AND member.parentfield = 'members'
					AND member.enabled = 1
					AND member.user = %(user)s
				WHERE team_contact.parenttype = 'WhatsApp Core Team'
					AND team_contact.parentfield = 'contacts'
					AND team_contact.enabled = 1
					AND team_contact.identity = %(identity)s
			) AS has_matching_team
		""",
		{"identity": identity, "user": frappe.session.user},
		as_dict=True,
	)[0]
	if bool(row.has_user_team) != bool(row.has_contact_team) or (
		row.has_user_team and not row.has_matching_team
	):
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
			(
				EXISTS (
					SELECT 1
					FROM `tabWhatsApp Core Team Member` AS user_team
					JOIN `tabWhatsApp Core Team` AS enabled_user_team
						ON enabled_user_team.name = user_team.parent
						AND enabled_user_team.enabled = 1
					WHERE user_team.parenttype = 'WhatsApp Core Team'
						AND user_team.parentfield = 'members'
						AND user_team.enabled = 1
						AND user_team.user = %(contact_scope_user)s
				)
				AND EXISTS (
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
			)
			OR (
				NOT EXISTS (
					SELECT 1
					FROM `tabWhatsApp Core Team Member` AS user_team
					JOIN `tabWhatsApp Core Team` AS enabled_user_team
						ON enabled_user_team.name = user_team.parent
						AND enabled_user_team.enabled = 1
					WHERE user_team.parenttype = 'WhatsApp Core Team'
						AND user_team.parentfield = 'members'
						AND user_team.enabled = 1
						AND user_team.user = %(contact_scope_user)s
				)
				AND NOT EXISTS (
					SELECT 1
					FROM `tabWhatsApp Core Team Contact` AS contact_scope
					JOIN `tabWhatsApp Core Team` AS contact_team
						ON contact_team.name = contact_scope.parent AND contact_team.enabled = 1
					WHERE contact_scope.parenttype = 'WhatsApp Core Team'
						AND contact_scope.parentfield = 'contacts'
						AND contact_scope.enabled = 1
						AND contact_scope.identity = {identity_expression}
				)
			)
		)""",
		{"contact_scope_user": frappe.session.user},
	)
