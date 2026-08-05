import uuid

import frappe
from frappe.tests.utils import FrappeTestCase

from frappe_whatsapp_core.identity import (
	get_or_create_identity,
	resolve_identity,
)


class TestIdentityResolution(FrappeTestCase):
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
