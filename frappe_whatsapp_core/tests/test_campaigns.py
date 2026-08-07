from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from frappe_whatsapp_core.campaigns import (
	authorize_campaign,
	create_campaign,
	launch_campaign,
	prepare_campaign,
	process_campaign_batch,
)
from frappe_whatsapp_core.template_catalog import sync_template_projection


def blocked_campaign_preflight(_context):
	return {"ready": False, "reasons": ["Test business gate is locked"]}


class TestCampaigns(FrappeTestCase):
	def setUp(self):
		super().setUp()
		suffix = frappe.generate_hash(length=8).lower()
		self.channel = frappe.get_doc({
			"doctype": "WhatsApp Core Channel",
			"channel_key": f"meta:campaign-{suffix}",
			"display_name": "Campaign Test",
			"provider": "meta",
			"phone_number_id": f"campaign-{suffix}",
			"enabled": 1,
		}).insert(ignore_permissions=True)
		self.identities = [
			frappe.get_doc({
				"doctype": "WhatsApp Core Identity",
				"identity_key": f"campaign-identity-{suffix}-{index}",
				"identity_type": "WhatsApp",
				"normalized_value": f"91990000{suffix[:4]}{index}",
				"display_value": f"91990000{suffix[:4]}{index}",
				"provider": "meta",
				"status": "Active",
			}).insert(ignore_permissions=True)
			for index in range(2)
		]
		self.template = sync_template_projection({
			"name": f"campaign_template_{suffix}",
			"language": "en",
			"status": "APPROVED",
			"category": "UTILITY",
			"components": [{
				"type": "BODY",
				"text": "Hello {{1}}",
			}],
		})["name"]
		self.campaign = create_campaign(
			campaign_key=f"campaign.test.{suffix}",
			title="Campaign test",
			channel=self.channel.name,
			template=self.template,
			audience_source={"provider": "test"},
		)

	def test_template_projection_extracts_copy(self):
		template = frappe.get_doc("WhatsApp Core Template", self.template)
		self.assertEqual(template.approval_status, "APPROVED")
		self.assertEqual(template.body_text, "Hello {{1}}")
		self.assertTrue(template.enabled)

	def test_template_projection_notifies_open_core_sessions(self):
		with patch("frappe_whatsapp_core.template_catalog.frappe.publish_realtime") as publish:
			result = sync_template_projection({
				"name": f"realtime_{frappe.generate_hash(length=8).lower()}",
				"language": "en",
				"status": "APPROVED",
			})
		publish.assert_any_call(
			"whatsapp_core_template",
			{"template": result["name"]},
			after_commit=True,
		)

	def test_prepare_is_exact_and_deduplicated(self):
		with patch("frappe_whatsapp_core.campaigns.frappe.publish_realtime") as publish:
			summary = prepare_campaign(
				self.campaign.name,
				[
					{
						"identity": self.identities[0].name,
						"personalization": {"components": []},
					},
					self.identities[0].name,
					self.identities[1].name,
				],
			)
		publish.assert_called_with(
			"whatsapp_core_campaign",
			{"campaign": self.campaign.name, "status": "Prepared", "counts": {}},
			after_commit=True,
		)
		self.assertEqual(summary["status"], "Prepared")
		self.assertEqual(summary["recipient_count"], 2)
		self.assertEqual(
			frappe.db.count(
				"WhatsApp Core Campaign Recipient",
				{"campaign": self.campaign.name},
			),
			2,
		)

	def test_send_authorization_is_separate_and_explicit(self):
		prepare_campaign(
			self.campaign.name,
			[self.identities[0].name],
		)
		with self.assertRaises(frappe.ValidationError):
			authorize_campaign(self.campaign.name, "yes")

		summary = authorize_campaign(
			self.campaign.name,
			f"AUTHORIZE {self.campaign.campaign_key}",
		)
		self.assertTrue(summary["send_authorized"])
		self.assertEqual(summary["template_approval_status"], "APPROVED")

	def test_business_preflight_blocks_launch_while_gate_is_locked(self):
		prepare_campaign(
			self.campaign.name,
			[self.identities[0].name],
		)
		authorize_campaign(
			self.campaign.name,
			f"AUTHORIZE {self.campaign.campaign_key}",
		)
		with patch(
			"frappe_whatsapp_core.campaigns.frappe.get_hooks",
			return_value=[
				"frappe_whatsapp_core.tests.test_campaigns.blocked_campaign_preflight"
			],
		):
			with self.assertRaises(frappe.ValidationError):
				launch_campaign(self.campaign.name)
		self.assertEqual(
			frappe.db.get_value(
				"WhatsApp Core Campaign",
				self.campaign.name,
				"status",
			),
			"Prepared",
		)

	def test_campaign_worker_never_exceeds_relay_batch_limit(self):
		self.campaign.status = "Running"
		self.campaign.save(ignore_permissions=True)
		with (
			patch("frappe_whatsapp_core.campaigns._campaign_batch_sender", return_value=object()),
			patch("frappe_whatsapp_core.campaigns.frappe.get_all", return_value=[]) as get_all,
			patch("frappe_whatsapp_core.campaigns._complete_campaign"),
		):
			process_campaign_batch(self.campaign.name, batch_size=500)
		self.assertEqual(get_all.call_args.kwargs["limit_page_length"], 40)
