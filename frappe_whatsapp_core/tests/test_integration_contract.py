import inspect
import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from frappe_whatsapp_core import api, frontend_api, mcp_tools, template_catalog
from frappe_whatsapp_core.mcp_tools import TOOL_DEFINITIONS


class TestIntegrationCallbackContract(FrappeTestCase):
	def setUp(self):
		super().setUp()
		suffix = frappe.generate_hash(length=8).lower()
		self.account = f"contract-account-{suffix}"
		self.channel = frappe.get_doc({
			"doctype": "WhatsApp Core Channel",
			"channel_key": f"meta:contract-{suffix}",
			"display_name": "Contract Test",
			"provider": "meta",
			"phone_number_id": f"contract-{suffix}",
			"enabled": 1,
		}).insert(ignore_permissions=True)
		settings = frappe.get_single("WhatsApp Core Settings")
		settings.set("accounts", [{
			"channel": self.channel.name,
			"account_name": self.account,
			"is_default": 1,
		}])
		settings.save(ignore_permissions=True)

	def test_integration_callback_endpoints_keep_required_parameters(self):
		outbound = inspect.signature(api.receive_outbound_result).parameters
		self.assertIn("idempotency_key", outbound)
		self.assertIn("status", outbound)
		self.assertTrue(callable(api.receive))
		self.assertIn("template", inspect.signature(template_catalog.receive_push).parameters)

	def test_integration_callbacks_require_dedicated_transport_access(self):
		original_user = frappe.session.user
		frappe.local.session.user = "limited@example.com"
		try:
			with (
				patch.object(api.frappe, "get_roles", return_value=["WhatsApp User"]),
				self.assertRaises(frappe.PermissionError),
			):
				api.receive_outbound_result("not-used", "sent")

			with (
				patch.object(api.frappe, "get_roles", return_value=["WhatsApp User"]),
				self.assertRaises(frappe.PermissionError),
			):
				api.receive()
		finally:
			frappe.local.session.user = original_user

	def test_integration_callbacks_accept_transport_service_role(self):
		transport_user = f"transport-{frappe.generate_hash(length=8).lower()}@example.com"
		frappe.get_doc({
			"doctype": "User",
			"email": transport_user,
			"first_name": "Transport",
			"enabled": 1,
			"user_type": "Website User",
			"send_welcome_email": 0,
			"roles": [{"role": "WhatsApp Core Transport Service"}],
		}).insert(ignore_permissions=True)
		original_user = frappe.session.user
		original_request = getattr(frappe.local, "request", None)
		original_session_obj = getattr(frappe.local, "session_obj", None)
		frappe.local.session.user = transport_user
		frappe.local.request = frappe._dict(method="POST")
		frappe.local.session_obj = object()
		try:
			with (
				patch.object(api, "_apply_outbound_result", return_value={"status": "applied"}),
			):
				self.assertEqual(
					api.receive_outbound_result("transport-proof", "sent"),
					{"status": "applied"},
				)
				self.assertIsNone(frappe.local.session_obj)
		finally:
			frappe.local.session.user = original_user
			frappe.local.request = original_request
			frappe.local.session_obj = original_session_obj

	def test_whatsapp_manager_is_a_unified_transport_identity(self):
		manager = f"transport-manager-{frappe.generate_hash(length=8).lower()}@example.com"
		frappe.get_doc({
			"doctype": "User",
			"email": manager,
			"first_name": "Transport Manager",
			"enabled": 1,
			"user_type": "System User",
			"send_welcome_email": 0,
			"roles": [{"role": "WhatsApp Manager"}],
		}).insert(ignore_permissions=True)
		original_user = frappe.session.user
		frappe.local.session.user = manager
		try:
			with patch.object(api, "_apply_outbound_result", return_value={"status": "applied"}):
				self.assertEqual(
					api.receive_outbound_result("manager-transport-proof", "sent"),
					{"status": "applied"},
				)
			with patch.object(
				frontend_api,
				"_transport_status_payload",
				return_value={"site": frappe.local.site},
			):
				identity = frontend_api.transport_identity()
		finally:
			frappe.local.session.user = original_user
		self.assertEqual(identity["capability"], "all")
		self.assertEqual(identity["allowed_accounts"], [self.account])

	def test_transport_role_on_desk_user_is_rejected(self):
		user_name = f"transport-desk-{frappe.generate_hash(length=8).lower()}@example.com"
		frappe.get_doc({
			"doctype": "User",
			"email": user_name,
			"first_name": "Unsafe Transport",
			"enabled": 1,
			"user_type": "System User",
			"send_welcome_email": 0,
			"roles": [{"role": "WhatsApp Core Transport Service"}],
		}).insert(ignore_permissions=True)
		frappe.db.set_value("User", user_name, "user_type", "System User", update_modified=False)
		frappe.clear_document_cache("User", user_name)
		original_user = frappe.session.user
		frappe.local.session.user = user_name
		try:
			with self.assertRaises(frappe.PermissionError):
				api.receive_outbound_result("not-used", "sent")
		finally:
			frappe.local.session.user = original_user

	def test_ingress_identity_cannot_mutate_template_projection(self):
		user_name = f"transport-cross-{frappe.generate_hash(length=8).lower()}@example.com"
		frappe.get_doc({
			"doctype": "User",
			"email": user_name,
			"first_name": "Ingress Only",
			"enabled": 1,
			"user_type": "Website User",
			"send_welcome_email": 0,
			"roles": [{"role": "WhatsApp Core Transport Service"}],
		}).insert(ignore_permissions=True)
		original_user = frappe.session.user
		frappe.local.session.user = user_name
		try:
			with self.assertRaises(frappe.PermissionError):
				template_catalog.receive_push(template={})
		finally:
			frappe.local.session.user = original_user

	def test_template_callback_identity_is_bound_to_one_exact_account(self):
		allowed_user = f"template-account-{frappe.generate_hash(length=8).lower()}@example.com"
		other_user = f"template-other-{frappe.generate_hash(length=8).lower()}@example.com"
		for user in (allowed_user, other_user):
			frappe.get_doc({
				"doctype": "User",
				"email": user,
				"first_name": "Template Service",
				"enabled": 1,
				"user_type": "Website User",
				"send_welcome_email": 0,
				"roles": [{"role": "WhatsApp Core Template Service"}],
			}).insert(ignore_permissions=True)
		settings = frappe.get_single("WhatsApp Core Settings")
		settings.accounts[0].template_service_user = allowed_user
		settings.save(ignore_permissions=True)
		payload = {
			"account_name": self.account,
			"name": "bound_template",
			"language": "en",
			"status": "DRAFT",
			"components": [{"type": "BODY", "text": "Bound"}],
		}
		original_user = frappe.session.user
		try:
			frappe.local.session.user = other_user
			with self.assertRaises(frappe.PermissionError):
				template_catalog.receive_push(template=payload)
			frappe.local.session.user = allowed_user
			result = template_catalog.receive_push(template=payload)
			self.assertEqual(result["account_name"], self.account)
		finally:
			frappe.local.session.user = original_user

	def test_template_identity_cannot_apply_outbound_result(self):
		user_name = f"template-cross-{frappe.generate_hash(length=8).lower()}@example.com"
		frappe.get_doc({
			"doctype": "User",
			"email": user_name,
			"first_name": "Template Only",
			"enabled": 1,
			"user_type": "Website User",
			"send_welcome_email": 0,
			"roles": [{"role": "WhatsApp Core Template Service"}],
		}).insert(ignore_permissions=True)
		original_user = frappe.session.user
		frappe.local.session.user = user_name
		try:
			with self.assertRaises(frappe.PermissionError):
				api.receive_outbound_result("not-used", "sent")
		finally:
			frappe.local.session.user = original_user

	def test_provisioner_never_reuses_an_existing_human_identity(self):
		user_name = f"transport-human-{frappe.generate_hash(length=8).lower()}@example.com"
		frappe.get_doc({
			"doctype": "User",
			"email": user_name,
			"first_name": "Human Operator",
			"enabled": 1,
			"user_type": "System User",
			"send_welcome_email": 0,
		}).insert(ignore_permissions=True)
		with self.assertRaises(frappe.ValidationError):
			frontend_api.provision_transport_credentials(user_name, rotate=1)

	def test_provisioner_rotates_only_a_service_only_website_user(self):
		user_name = f"transport-service-{frappe.generate_hash(length=8).lower()}@example.com"
		frappe.get_doc({
			"doctype": "User",
			"email": user_name,
			"first_name": "Transport Service",
			"enabled": 1,
			"user_type": "Website User",
			"send_welcome_email": 0,
			"roles": [{"role": "WhatsApp Core Transport Service"}],
		}).insert(ignore_permissions=True)
		with patch(
			"frappe.core.doctype.user.user.generate_keys",
			return_value={"api_key": "test-key", "api_secret": "test-secret"},
		):
			result = frontend_api.provision_transport_credentials(
				user_name, rotate=1, capability="ingress"
			)
		self.assertEqual(result["user"], user_name)
		self.assertEqual(result["api_secret"], "test-secret")

	def test_unified_service_user_handles_every_machine_capability(self):
		from frappe_whatsapp_core.permissions import (
			TRANSPORT_CAPABILITY_ROLES,
			is_dedicated_transport_user,
		)

		user_name = f"unified-service-{frappe.generate_hash(length=8).lower()}@example.com"
		with patch(
			"frappe.core.doctype.user.user.generate_keys",
			return_value={"api_key": "unified-key", "api_secret": "unified-secret"},
		):
			result = frontend_api.provision_transport_credentials(
				user_name,
				capability="all",
				account_name=self.account,
			)
		self.assertEqual(result["capability"], "all")
		self.assertEqual(set(result["roles"]), set(TRANSPORT_CAPABILITY_ROLES.values()))
		self.assertEqual(result["allowed_accounts"], [self.account])
		for capability in ("ingress", "template", "flow", "all"):
			self.assertTrue(is_dedicated_transport_user(user_name, capability=capability))

		original_user = frappe.session.user
		try:
			frappe.local.session.user = user_name
			with patch.object(
				frontend_api,
				"_transport_status_payload",
				return_value={"site": frappe.local.site},
			):
				identity = frontend_api.transport_identity()
		finally:
			frappe.local.session.user = original_user
		self.assertEqual(identity["capability"], "all")
		self.assertEqual(identity["allowed_accounts"], [self.account])

	def test_template_provisioner_binds_identity_to_exact_account(self):
		user_name = f"template-service-{frappe.generate_hash(length=8).lower()}@example.com"
		with patch(
			"frappe.core.doctype.user.user.generate_keys",
			return_value={"api_key": "template-key", "api_secret": "template-secret"},
		):
			result = frontend_api.provision_transport_credentials(
				user_name,
				capability="template",
				account_name=self.account,
			)
		self.assertEqual(result["account_name"], self.account)
		self.assertEqual(result["capability"], "template")
		original_user = frappe.session.user
		try:
			frappe.local.session.user = user_name
			with patch.object(
				frontend_api,
				"_transport_status_payload",
				return_value={"site": frappe.local.site},
			):
				identity = frontend_api.transport_identity()
		finally:
			frappe.local.session.user = original_user
		self.assertEqual(identity["capability"], "template")
		self.assertEqual(identity["allowed_accounts"], [self.account])
		self.assertEqual(
			frappe.db.get_value(
				"WhatsApp Core Hub Account",
				{"parent": "WhatsApp Core Settings", "account_name": self.account},
				"template_service_user",
			),
			user_name,
		)

	def test_template_authoring_is_exposed_through_audited_mcp_contracts(self):
		tool_names = {tool["name"] for tool in TOOL_DEFINITIONS}
		self.assertIn("whatsapp.create_template", tool_names)
		self.assertIn("whatsapp.update_template", tool_names)
		self.assertIn("whatsapp.get_template", tool_names)
		self.assertIn("whatsapp.submit_template", tool_names)
		create_schema = next(
			tool["inputSchema"]
			for tool in TOOL_DEFINITIONS
			if tool["name"] == "whatsapp.create_template"
		)
		self.assertIn("account_name", create_schema["required"])
		self.assertIn("components", create_schema["required"])
		self.assertNotIn("body_text", create_schema["required"])

	def test_mcp_template_draft_preserves_components_and_explicit_action(self):
		components = [
			{"type": "BODY", "add_security_recommendation": True},
			{"type": "BUTTONS", "buttons": [{"type": "OTP", "otp_type": "COPY_CODE"}]},
		]
		with (
			patch.object(mcp_tools.frappe, "get_roles", return_value=["WhatsApp Manager"]),
			patch.object(mcp_tools, "request_template_upsert", return_value={"action": "saved_draft"}) as upsert,
		):
			result = mcp_tools.call_tool("whatsapp.create_template", {
				"account_name": self.account,
				"template_name": "mcp_auth",
				"language_code": "en_US",
				"category": "AUTHENTICATION",
				"parameter_format": "NAMED",
				"components": components,
				"submit": False,
			})
		self.assertEqual(result["action"], "saved_draft")
		self.assertEqual(upsert.call_args.kwargs["template"]["components"], components)
		self.assertEqual(upsert.call_args.kwargs["template"]["parameter_format"], "NAMED")
		self.assertFalse(upsert.call_args.kwargs["submit"])
		self.assertNotIn("submit", upsert.call_args.kwargs["template"])

	def test_same_template_name_is_isolated_per_hub_account(self):
		suffix = frappe.generate_hash(length=8).lower()
		second_channel = frappe.get_doc({
			"doctype": "WhatsApp Core Channel",
			"channel_key": f"meta:contract-second-{suffix}",
			"display_name": "Second Contract Account",
			"provider": "meta",
			"phone_number_id": f"contract-second-{suffix}",
			"enabled": 1,
		}).insert(ignore_permissions=True)
		second_account = f"contract-second-account-{suffix}"
		settings = frappe.get_single("WhatsApp Core Settings")
		settings.append("accounts", {
			"channel": second_channel.name,
			"account_name": second_account,
		})
		settings.save(ignore_permissions=True)
		template_name = f"shared_{suffix}"
		first = template_catalog.sync_template_projection({
			"account_name": self.account,
			"name": template_name,
			"language": "en",
			"status": "APPROVED",
		})
		second = template_catalog.sync_template_projection({
			"account_name": second_account,
			"name": template_name,
			"language": "en",
			"status": "APPROVED",
		})
		self.assertNotEqual(first["name"], second["name"])
		self.assertEqual(first["channel"], self.channel.name)
		self.assertEqual(second["channel"], second_channel.name)

	def test_core_template_edit_is_scoped_to_site_and_reprojects_hub_result(self):
		key = template_catalog.sync_template_projection({
			"account_name": self.account,
			"hub_template_name": "hub-template-test",
			"name": f"contract_{frappe.generate_hash(length=8).lower()}",
			"language": "en",
			"category": "UTILITY",
			"status": "APPROVED",
			"components": [{"type": "BODY", "text": "Original body"}],
		})["name"]
		with patch.object(template_catalog, "call_management") as call_management:
			call_management.return_value = {
				"success": True,
				"template": {
					"account_name": self.account,
					"hub_template_name": "hub-template-test",
					"name": frappe.db.get_value(
						"WhatsApp Core Template", key, "template_name"
					),
					"language": "en",
					"category": "UTILITY",
					"status": "IN_REVIEW",
					"components": [{"type": "BODY", "text": "Revised body"}],
				},
			}
			result = template_catalog.request_template_upsert(
				template={"body_text": "Revised body"},
				template_key=key,
			)
		self.assertTrue(result["success"])
		self.assertEqual(result["approval_status"], "IN_REVIEW")
		arguments = call_management.call_args.args[1]
		self.assertEqual(arguments["site_name"], frappe.local.site)
		self.assertEqual(arguments["hub_template_name"], "hub-template-test")
		self.assertEqual(
			frappe.db.get_value(
				"WhatsApp Core Template", key, ["approval_status", "enabled", "body_text"], as_dict=True
			),
			{"approval_status": "IN_REVIEW", "enabled": 0, "body_text": "Revised body"},
		)

	def test_draft_round_trip_preserves_advanced_components_ttl_and_status_detail(self):
		components = [
			{"type": "BODY", "add_security_recommendation": True},
			{
				"type": "BUTTONS",
				"buttons": [{
					"type": "OTP",
					"otp_type": "ZERO_TAP",
					"package_name": "com.example.app",
					"signature_hash": "signature",
				}],
			},
		]
		remote = {
			"account_name": self.account,
			"hub_template_name": "hub-draft-auth",
			"name": "draft_auth",
			"language": "en_US",
			"category": "AUTHENTICATION",
			"status": "DRAFT",
			"message_send_ttl_seconds": 600,
			"correct_category": "UTILITY",
			"rejection_reason": "Example status detail",
			"parameter_format": "NAMED",
			"source": "CORE",
			"components": components,
		}
		with patch.object(template_catalog, "call_management") as call_management:
			call_management.return_value = {
				"success": True,
				"action": "saved",
				"template": remote,
			}
			result = template_catalog.request_template_upsert(
				template={
					"account_name": self.account,
					"template_name": "draft_auth",
					"language_code": "en_US",
					"category": "AUTHENTICATION",
					"message_send_ttl_seconds": 600,
					"parameter_format": "NAMED",
					"components": components,
				},
				submit=False,
			)
		self.assertEqual(result["action"], "saved_draft")
		self.assertEqual(result["approval_status"], "DRAFT")
		self.assertFalse(call_management.call_args.args[1]["submit"])
		self.assertEqual(
			call_management.call_args.args[1]["template"]["parameter_format"],
			"NAMED",
		)
		readback = template_catalog.get_template(result["template"]["name"])
		self.assertEqual(readback["components"], components)
		self.assertEqual(readback["message_send_ttl_seconds"], 600)
		self.assertEqual(readback["status_reason"], "Example status detail")
		self.assertEqual(readback["correct_category"], "UTILITY")
		self.assertEqual(readback["parameter_format"], "NAMED")
		self.assertEqual(readback["template_source"], "CORE")

	def test_failed_meta_submit_projects_draft_but_never_reports_success(self):
		components = [{"type": "BODY", "text": "Hello {{1}}"}]
		remote = {
			"account_name": self.account,
			"hub_template_name": "hub-failed-submit",
			"name": "failed_submit",
			"language": "en",
			"category": "UTILITY",
			"status": "DRAFT",
			"components": components,
		}
		with patch.object(
			template_catalog,
			"call_management",
			return_value={
				"success": False,
				"error": "Meta rejected the submitted component example",
				"action": "submitted",
				"template": remote,
			},
		):
			result = template_catalog.request_template_upsert(
				template={
					"account_name": self.account,
					"template_name": "failed_submit",
					"language_code": "en",
					"category": "UTILITY",
					"components": components,
				},
				submit=True,
			)
		self.assertFalse(result["success"])
		self.assertIn("Meta rejected", result["error"])
		self.assertEqual(result["template"]["approval_status"], "DRAFT")
		key = template_catalog.scoped_template_key(self.account, "failed_submit", "en")
		self.assertEqual(
			frappe.db.get_value(
				"WhatsApp Core Template",
				{"template_key": key},
				"approval_status",
			),
			"DRAFT",
		)

	def test_submit_existing_draft_sends_complete_projected_document(self):
		components = [
			{"type": "BODY", "text": "Order {{order_id}} is ready", "example": {"body_text_named_params": [{"param_name": "order_id", "example": "A-1"}]}},
			{"type": "BUTTONS", "buttons": [{"type": "FLOW", "text": "Open", "flow_id": "123"}]},
		]
		key = template_catalog.sync_template_projection({
			"account_name": self.account,
			"hub_template_name": "hub-submit-draft",
			"name": "submit_draft",
			"language": "en",
			"category": "UTILITY",
			"status": "DRAFT",
			"message_send_ttl_seconds": 300,
			"parameter_format": "NAMED",
			"components": components,
		})["name"]
		with patch.object(template_catalog, "call_management") as call_management:
			call_management.return_value = {
				"success": True,
				"action": "submitted",
				"template": {
					"account_name": self.account,
					"hub_template_name": "hub-submit-draft",
					"name": "submit_draft",
					"language": "en",
					"category": "UTILITY",
					"status": "IN_REVIEW",
					"message_send_ttl_seconds": 300,
					"parameter_format": "NAMED",
					"components": components,
				},
			}
			result = template_catalog.submit_template(key)
		request = call_management.call_args.args[1]
		self.assertTrue(request["submit"])
		self.assertEqual(request["template"]["components"], components)
		self.assertEqual(request["template"]["message_send_ttl_seconds"], 300)
		self.assertEqual(request["template"]["parameter_format"], "NAMED")
		self.assertEqual(result["approval_status"], "IN_REVIEW")

	def test_template_readback_fails_closed_on_malformed_stored_components(self):
		key = template_catalog.sync_template_projection({
			"account_name": self.account,
			"name": "malformed_readback",
			"language": "en",
			"status": "DRAFT",
			"components": [{"type": "BODY", "text": "Safe"}],
		})["name"]
		frappe.db.set_value(
			"WhatsApp Core Template", key, "components", '["not-an-object"]'
		)
		with self.assertRaisesRegex(frappe.ValidationError, "must be an object"):
			template_catalog.get_template(key)

	def test_frontend_template_catalog_is_paginated_with_exact_total(self):
		for index in range(2):
			template_catalog.sync_template_projection({
				"account_name": self.account,
				"name": f"page_{index}_{frappe.generate_hash(length=6).lower()}",
				"language": "en",
				"status": "APPROVED",
				"components": [{"type": "BODY", "text": "Page"}],
			})
		page = frontend_api.template_catalog(start=0, limit=1)
		self.assertEqual(len(page["templates"]), 1)
		self.assertEqual(page["loaded"], 1)
		self.assertEqual(page["total"], frappe.db.count("WhatsApp Core Template"))
		self.assertEqual(page["has_more"], page["total"] > 1)

	def test_advanced_template_components_pass_through_without_flattening(self):
		components = [
			{"type": "BODY", "add_security_recommendation": True},
			{
				"type": "BUTTONS",
				"buttons": [{
					"type": "OTP",
					"otp_type": "ZERO_TAP",
					"package_name": "com.example.app",
					"signature_hash": "test-signature",
				}],
			},
		]
		payload = template_catalog._editable_payload({
			"account_name": self.account,
			"template_name": "advanced_auth",
			"language_code": "en_US",
			"category": "AUTHENTICATION",
			"components": components,
		})
		self.assertEqual(payload["components"], components)
		with self.assertRaises(frappe.ValidationError):
			template_catalog._editable_payload({"components": []})

	def test_advanced_template_partial_edit_preserves_raw_or_fails_closed(self):
		components = [
			{"type": "BODY", "add_security_recommendation": True},
			{
				"type": "BUTTONS",
				"buttons": [{"type": "OTP", "otp_type": "COPY_CODE"}],
			},
		]
		existing = frappe._dict(
			account_name=self.account,
			template_name="advanced_partial",
			language_code="en_US",
			category="AUTHENTICATION",
			header_type="",
			header_content="",
			body_text="",
			footer_text="",
			components=json.dumps(components),
		)

		merged = template_catalog._merge_existing_template(
			existing, {"category": "AUTHENTICATION"}
		)
		self.assertEqual(merged["components"], components)
		with self.assertRaises(frappe.ValidationError):
			template_catalog._merge_existing_template(
				existing, {"body_text": "A lossy basic edit"}
			)
