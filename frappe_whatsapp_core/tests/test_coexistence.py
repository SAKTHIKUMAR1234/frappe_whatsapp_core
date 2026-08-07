import json

import frappe
from frappe.tests.utils import FrappeTestCase

from frappe_whatsapp_core.api import describe_payload
from frappe_whatsapp_core.materializer import materialize_event


class TestCoexistence(FrappeTestCase):
	def _event(self, event_id, payload):
		return frappe.get_doc({
			"doctype": "WhatsApp Core Event",
			"event_id": event_id,
			"status": "Pending",
			"event_type": "coexistence",
			"direction": "Inbound",
			"payload": json.dumps(payload),
		}).insert(ignore_permissions=True)

	def test_business_app_echo_is_projected_as_outbound(self):
		payload = {
			"entry": [{"id": "WABA-COEX", "changes": [{"field": "smb_message_echoes", "value": {
				"metadata": {"phone_number_id": "PHONE-COEX"},
				"message_echoes": [{
					"id": "wamid.echo-1", "to": "919876543210", "timestamp": "1712345678",
					"type": "text", "text": {"body": "Sent from Business App"},
				}],
			}}]}],
		}
		event = self._event("coexistence-echo", payload)
		result = materialize_event(event, payload)[0]
		message = frappe.get_doc("WhatsApp Core Message", result["name"])
		self.assertEqual(message.direction, "Outbound")
		self.assertEqual(message.delivery_status, "Sent")
		self.assertEqual(message.body, "Sent from Business App")
		self.assertEqual(describe_payload(payload)["event_type"], "message_echo:text")

	def test_history_import_preserves_direction_and_deduplicates(self):
		payload = {
			"entry": [{"id": "WABA-COEX", "changes": [{"field": "history", "value": {
				"history": [{
					"metadata": {"phone_number_id": "PHONE-HISTORY"},
					"threads": [{"id": "919999999999", "messages": [
						{"id": "wamid.history-in", "from": "919999999999", "timestamp": "1712345678", "type": "text", "text": {"body": "Inbound history"}},
						{"id": "wamid.history-out", "to": "919999999999", "timestamp": "1712345679", "type": "text", "text": {"body": "Outbound history"}},
					]}],
				}],
			}}]}],
		}
		event = self._event("coexistence-history", payload)
		result = materialize_event(event, payload)
		self.assertEqual([row["status"] for row in result], ["created", "created"])
		self.assertEqual(
			frappe.get_doc("WhatsApp Core Message", result[0]["name"]).direction,
			"Inbound",
		)
		self.assertEqual(
			frappe.get_doc("WhatsApp Core Message", result[1]["name"]).direction,
			"Outbound",
		)
		self.assertEqual(
			[row["status"] for row in materialize_event(event, payload)],
			["duplicate", "duplicate"],
		)
		self.assertEqual(describe_payload(payload)["event_type"], "coexistence:history")

	def test_edit_and_revoke_update_original_message(self):
		original = {
			"entry": [{"id": "WABA-COEX", "changes": [{"field": "smb_message_echoes", "value": {
				"metadata": {"phone_number_id": "PHONE-MUTATION"},
				"message_echoes": [{"id": "wamid.original", "to": "919111111111", "type": "text", "text": {"body": "Before"}}],
			}}]}],
		}
		original_event = self._event("coexistence-original", original)
		message_name = materialize_event(original_event, original)[0]["name"]

		edit = {
			"entry": [{"id": "WABA-COEX", "changes": [{"field": "smb_message_echoes", "value": {
				"metadata": {"phone_number_id": "PHONE-MUTATION"},
				"message_echoes": [{"id": "wamid.edit-event", "type": "edit", "edit": {
					"message_id": "wamid.original", "message": {"type": "text", "text": {"body": "After"}},
				}}],
			}}]}],
		}
		edit_event = self._event("coexistence-edit", edit)
		self.assertEqual(materialize_event(edit_event, edit)[0]["status"], "updated")
		message = frappe.get_doc("WhatsApp Core Message", message_name)
		self.assertEqual(message.body, "After")

		revoke = {
			"entry": [{"id": "WABA-COEX", "changes": [{"field": "smb_message_echoes", "value": {
				"metadata": {"phone_number_id": "PHONE-MUTATION"},
				"message_echoes": [{"id": "wamid.revoke-event", "type": "revoke", "revoke": {"message_id": "wamid.original"}}],
			}}]}],
		}
		revoke_event = self._event("coexistence-revoke", revoke)
		self.assertEqual(materialize_event(revoke_event, revoke)[0]["status"], "updated")
		message.reload()
		self.assertEqual(message.delivery_status, "Deleted")
		self.assertEqual(message.body, "[Message deleted]")
