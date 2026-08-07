import json
import uuid
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from frappe_whatsapp_core.identity import (
	contact_options,
	get_or_create_identity,
	resolve_identity,
)
from frappe_whatsapp_core.outbound import resolve_recipient_phone


class TestIdentityResolution(FrappeTestCase):
	def setUp(self):
		super().setUp()
		# These tests deliberately create temporary User documents.  A site with
		# recent real user creation can otherwise trip Frappe's global one-minute
		# throttle and make this suite depend on unrelated site activity.
		throttle_patcher = patch("frappe.core.doctype.user.user.throttle_user_creation")
		throttle_patcher.start()
		self.addCleanup(throttle_patcher.stop)

	def test_contact_lookup_searches_business_link_without_loading_all_identities(self):
		suffix = f"7{str(uuid.uuid4().int)[-9:]}"
		full_name = f"Searchable Contact {suffix}"
		user = frappe.get_doc({
			"doctype": "User",
			"email": f"whatsapp.search.{suffix}@example.com",
			"first_name": full_name,
			"mobile_no": f"+91{suffix}",
			"enabled": 1,
			"send_welcome_email": 0,
		}).insert(ignore_permissions=True)
		frappe.get_doc({
			"doctype": "WhatsApp Core Identity Source",
			"source_key": f"test.search.{suffix}",
			"display_name": "Searchable Users",
			"source_doctype": "User",
			"enabled": 1,
			"auto_resolve": 1,
			"priority": 1,
			"phone_field": "mobile_no",
			"display_name_field": "full_name",
			"filters": json.dumps({"name": user.name}),
		}).insert(ignore_permissions=True)
		identity = get_or_create_identity(suffix)

		results = contact_options(search=f"Contact {suffix}", limit=10)
		self.assertEqual([row["identity"] for row in results], [identity.name])
		self.assertEqual(results[0]["label"], user.full_name)

	def test_outbound_uses_current_phone_from_linked_document(self):
		suffix = f"7{str(uuid.uuid4().int)[-9:]}"
		replacement = f"8{str(uuid.uuid4().int)[-9:]}"
		user = frappe.get_doc({
			"doctype": "User",
			"email": f"whatsapp.outbound.{suffix}@example.com",
			"first_name": "Outbound",
			"mobile_no": f"+91{suffix}",
			"enabled": 1,
			"send_welcome_email": 0,
		}).insert(ignore_permissions=True)
		frappe.get_doc({
			"doctype": "WhatsApp Core Identity Source",
			"source_key": f"test.outbound.{suffix}",
			"display_name": "Outbound Users",
			"source_doctype": "User",
			"enabled": 1,
			"auto_resolve": 1,
			"priority": 1,
			"phone_field": "mobile_no",
			"display_name_field": "full_name",
		}).insert(ignore_permissions=True)

		identity = get_or_create_identity(suffix)
		user.mobile_no = f"+91{replacement}"
		user.save(ignore_permissions=True)
		frappe.clear_document_cache("User", user.name)

		with patch(
			"frappe_whatsapp_core.outbound.frappe.get_hooks",
			side_effect=lambda key: {} if key == "whatsapp_core_contact_phone_resolvers" else [],
		):
			self.assertEqual(resolve_recipient_phone(identity), f"91{replacement}")

	def test_generic_source_resolves_and_deactivates_cleanly(self):
		suffix = f"7{str(uuid.uuid4().int)[-9:]}"
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": f"whatsapp.identity.{suffix}@example.com",
				"first_name": "Identity",
				"mobile_no": f"+91{suffix}",
				"enabled": 1,
				"send_welcome_email": 0,
			}
		).insert(ignore_permissions=True)
		source = frappe.get_doc(
			{
				"doctype": "WhatsApp Core Identity Source",
				"source_key": f"test.user.{suffix}",
				"display_name": "Test Users",
				"source_doctype": "User",
				"enabled": 1,
				"auto_resolve": 1,
				"priority": 1,
				"phone_field": "mobile_no",
				"display_name_field": "full_name",
				"filters": '{"enabled": 1}',
			}
		).insert(ignore_permissions=True)

		identity = get_or_create_identity(suffix)
		link = frappe.get_doc(
			"WhatsApp Core Identity Link",
			identity.primary_link,
		)
		self.assertEqual(identity.resolution_status, "Resolved")
		self.assertEqual(link.reference_doctype, "User")
		self.assertEqual(link.reference_name, user.name)
		self.assertEqual(link.match_quality, "Exact")
		self.assertEqual(link.is_primary, 1)

		source.enabled = 0
		source.save(ignore_permissions=True)
		result = resolve_identity(identity)
		identity.reload()
		link.reload()
		self.assertEqual(result["status"], "Unresolved")
		self.assertEqual(identity.resolution_status, "Unresolved")
		self.assertFalse(identity.primary_link)
		self.assertEqual(link.status, "Inactive")

	def test_multiple_business_matches_are_marked_ambiguous(self):
		suffix = f"7{str(uuid.uuid4().int)[-9:]}"
		mobile_no = f"+91{suffix}"
		for index in range(2):
			frappe.get_doc(
				{
					"doctype": "ToDo",
					"description": mobile_no,
				}
			).insert(ignore_permissions=True)
		frappe.get_doc(
			{
				"doctype": "WhatsApp Core Identity Source",
				"source_key": f"test.ambiguous.{suffix}",
				"display_name": "Ambiguous Test Records",
				"source_doctype": "ToDo",
				"enabled": 1,
				"auto_resolve": 1,
				"priority": 1,
				"phone_field": "description",
				"display_name_field": "description",
			}
		).insert(ignore_permissions=True)

		identity = get_or_create_identity(suffix)
		links = frappe.get_all(
			"WhatsApp Core Identity Link",
			filters={
				"identity": identity.name,
				"status": "Active",
			},
			fields=["is_primary"],
		)
		self.assertEqual(identity.resolution_status, "Ambiguous")
		self.assertEqual(len(links), 2)
		self.assertEqual(
			sum(int(link.is_primary or 0) for link in links),
			1,
		)
