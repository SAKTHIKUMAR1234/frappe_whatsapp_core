import unittest
from unittest.mock import patch

from frappe_whatsapp_core.delivery import (
	advance_delivery_status,
	dispatch_delivery_status_handlers,
	enqueue_delivery_status_handlers,
)


class TestDeliveryTransitions(unittest.TestCase):
	def test_provider_callbacks_cannot_regress_delivery(self):
		self.assertEqual(advance_delivery_status("Queued", "Sent"), "Sent")
		self.assertEqual(
			advance_delivery_status("Delivered", "Sent"),
			"Delivered",
		)
		self.assertEqual(advance_delivery_status("Read", "Delivered"), "Read")

	def test_failure_does_not_override_confirmed_delivery(self):
		self.assertEqual(advance_delivery_status("Queued", "Failed"), "Failed")
		self.assertEqual(
			advance_delivery_status("Delivered", "Failed"),
			"Delivered",
		)

	@patch("frappe_whatsapp_core.delivery.frappe.enqueue")
	@patch(
		"frappe_whatsapp_core.delivery.frappe.get_hooks",
		return_value=["custom_app.delivery.project"],
	)
	def test_delivery_projection_is_queued_after_commit(self, _hooks, enqueue):
		enqueue_delivery_status_handlers({
			"message_name": "MSG-1",
			"delivery_status": "delivered",
		})

		enqueue.assert_called_once_with(
			"frappe_whatsapp_core.delivery.dispatch_delivery_status_handlers",
			queue="short",
			enqueue_after_commit=True,
			updates=[{
				"message_name": "MSG-1",
				"delivery_status": "Delivered",
			}],
		)

	@patch("frappe_whatsapp_core.delivery.frappe.get_attr")
	@patch(
		"frappe_whatsapp_core.delivery.frappe.get_hooks",
		return_value=["custom_app.delivery.project"],
	)
	@patch(
		"frappe_whatsapp_core.delivery.frappe.db.get_value",
		return_value="Read",
	)
	def test_delivery_projection_rereads_authoritative_status(
		self, get_value, _hooks, get_attr
	):
		handler = get_attr.return_value
		dispatch_delivery_status_handlers([{
			"message_name": "MSG-1",
			"delivery_status": "Sent",
		}])

		get_value.assert_called_once_with(
			"WhatsApp Core Message", "MSG-1", "delivery_status"
		)
		handler.assert_called_once_with(
			message_name="MSG-1",
			delivery_status="Read",
		)


if __name__ == "__main__":
	unittest.main()
