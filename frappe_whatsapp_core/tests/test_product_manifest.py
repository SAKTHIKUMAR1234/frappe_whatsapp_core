from unittest import TestCase

from frappe_whatsapp_core.product import product_manifest


class TestProductManifest(TestCase):
	def test_manifest_is_stable_and_secret_free(self):
		manifest = product_manifest()
		self.assertEqual(manifest["id"], "frappe_whatsapp_core")
		self.assertEqual(manifest["version"], "2.0.0")
		self.assertEqual(manifest["transport_contract_version"], 3)
		self.assertEqual(manifest["supported_hub_contract_versions"], [3])
		self.assertEqual(manifest["supported_frappe_majors"], [15, 16])
		self.assertNotIn("secret", repr(manifest).lower())
