"""Stable product and transport compatibility metadata.

This payload is intentionally secret-free.  Hub uses it during onboarding and
production acceptance so incompatible app releases fail before customer
traffic is enabled, rather than after a webhook or outbound message is lost.
"""

from __future__ import annotations

from frappe_whatsapp_core import __version__

PRODUCT_ID = "frappe_whatsapp_core"
PRODUCT_NAME = "WhatsApp Core"
TRANSPORT_CONTRACT_VERSION = 3
SUPPORTED_HUB_CONTRACT_VERSIONS = (3,)
SUPPORTED_FRAPPE_MAJORS = (15, 16)


def product_manifest() -> dict:
	return {
		"id": PRODUCT_ID,
		"name": PRODUCT_NAME,
		"version": __version__,
		"transport_contract_version": TRANSPORT_CONTRACT_VERSION,
		"supported_hub_contract_versions": list(SUPPORTED_HUB_CONTRACT_VERSIONS),
		"supported_frappe_majors": list(SUPPORTED_FRAPPE_MAJORS),
	}
