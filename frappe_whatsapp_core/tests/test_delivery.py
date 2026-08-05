import unittest

from frappe_whatsapp_core.delivery import advance_delivery_status


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


if __name__ == "__main__":
	unittest.main()
