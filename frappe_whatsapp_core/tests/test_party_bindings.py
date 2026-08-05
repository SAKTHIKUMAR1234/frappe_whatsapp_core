import frappe
from frappe.tests.utils import FrappeTestCase

from frappe_whatsapp_core.materializer import get_or_create_identity
from frappe_whatsapp_core.party_bindings import (
	get_primary_binding,
	upsert_party_binding,
)


class TestPartyBindings(FrappeTestCase):
	def test_upsert_is_idempotent_and_primary_is_workspace_scoped(self):
		identity = get_or_create_identity(
			f"9197{frappe.utils.now_datetime().strftime('%H%M%S%f')[-10:]}"
		)
		first = upsert_party_binding(
			identity.name,
			"User",
			"Administrator",
			workspace_key="test.workspace",
			party_role="Operator",
			is_primary=True,
			source="Test",
			attributes={"level": 1},
		)
		repeated = upsert_party_binding(
			identity.name,
			"User",
			"Administrator",
			workspace_key="test.workspace",
			party_role="Operator",
			is_primary=True,
			source="Test",
			attributes={"level": 2},
		)
		self.assertEqual(first.name, repeated.name)
		self.assertEqual(frappe.parse_json(repeated.attributes)["level"], 2)

		second = upsert_party_binding(
			identity.name,
			"User",
			"Guest",
			workspace_key="test.workspace",
			party_role="Customer",
			is_primary=True,
			source="Test",
		)
		first.reload()
		self.assertFalse(first.is_primary)
		self.assertEqual(
			get_primary_binding(identity.name, "test.workspace").name,
			second.name,
		)
