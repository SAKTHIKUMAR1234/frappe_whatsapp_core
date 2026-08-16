from unittest import TestCase
from unittest.mock import patch

import frappe

from frappe_whatsapp_core import network_security


class TestServiceOriginSecurity(TestCase):
	def test_external_http_and_embedded_credentials_are_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			network_security.validate_service_origin(
				"http://hub.example.com", label="Hub URL"
			)
		with self.assertRaises(frappe.ValidationError):
			network_security.validate_service_origin(
				"https://user:secret@hub.example.com", label="Hub URL"
			)

	def test_service_origin_cannot_include_an_operator_controlled_path(self):
		with self.assertRaises(frappe.ValidationError):
			network_security.validate_service_origin(
				"https://hub.example.com/redirect", label="Hub URL"
			)

	def test_private_dns_destination_is_rejected_outside_tests(self):
		with (
			patch.object(
				network_security.socket,
				"getaddrinfo",
				return_value=[(2, 1, 6, "", ("10.0.0.5", 443))],
			),
			self.assertRaises(frappe.ValidationError),
		):
			network_security._validate_public_destination(
				"hub.example.com", 443, False, "Hub URL"
			)

	def test_public_https_origin_is_normalized(self):
		self.assertEqual(
			network_security.validate_service_origin(
				"https://hub.example.com/", label="Hub URL"
			),
			"https://hub.example.com",
		)
