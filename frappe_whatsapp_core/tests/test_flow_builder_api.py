import copy

import frappe
from frappe.tests.utils import FrappeTestCase

from frappe_whatsapp_core.flow_api import (
	_empty_graph,
	create_flow,
	get_builder,
	list_flows,
	publish,
	reject,
	request_approval,
	save_draft,
	validate_draft,
)


class TestFlowBuilderAPI(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.suffix = frappe.generate_hash(length=10)
		self.flow_key = f"test.builder.{self.suffix}"

	def _create(self):
		return create_flow(
			"Builder regression",
			self.flow_key,
			_empty_graph(),
			"Lifecycle coverage",
		)

	def test_create_list_get_and_duplicate_boundary(self):
		created = self._create()
		self.assertEqual(created["flow_key"], self.flow_key)
		self.assertEqual(created["errors"], [])

		listed = {row.name for row in list_flows(limit=500)}
		self.assertIn(created["name"], listed)
		builder = get_builder(created["name"])
		self.assertEqual(builder["flow_key"], self.flow_key)
		self.assertTrue(builder["can_manage"])
		self.assertEqual(builder["errors"], [])
		self.assertIn("actions", builder["catalog"])

		with self.assertRaises(frappe.DuplicateEntryError):
			self._create()

	def test_draft_change_resets_approval_and_supports_review_lifecycle(self):
		created = self._create()
		graph = copy.deepcopy(_empty_graph())
		graph["nodes"][1]["config"]["label"] = "Completed"

		saved = save_draft(created["name"], graph)
		self.assertEqual(saved["errors"], [])
		self.assertEqual(validate_draft(created["name"])["errors"], [])
		requested = request_approval(created["name"])
		self.assertEqual(requested["approval_status"], "Pending Approval")

		rejected = reject(created["name"], "Add a customer-facing message")
		self.assertEqual(rejected["approval_status"], "Rejected")
		self.assertEqual(rejected["rejection_reason"], "Add a customer-facing message")

		published = publish(created["name"])
		self.assertEqual(published["status"], "published")
		self.assertEqual(
			frappe.db.get_value("WhatsApp Core Flow", created["name"], "approval_status"),
			"Approved",
		)

	def test_invalid_graph_cannot_be_submitted_or_published(self):
		created = self._create()
		invalid = {"schema_version": 1, "triggers": [], "nodes": [], "edges": []}
		saved = save_draft(created["name"], invalid)
		self.assertTrue(saved["errors"])
		with self.assertRaises(frappe.ValidationError):
			request_approval(created["name"])
		with self.assertRaises(frappe.ValidationError):
			publish(created["name"])

	def test_required_fields_are_enforced(self):
		with self.assertRaises(frappe.ValidationError):
			create_flow("", "", _empty_graph())
