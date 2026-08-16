from __future__ import annotations

import frappe
from frappe.model.document import Document

from frappe_whatsapp_core.network_security import validate_service_origin


class WhatsAppCoreSettings(Document):
	def validate(self):
		self.hub_url = validate_service_origin(self.hub_url, label="Hub URL")
		self.relay_url = validate_service_origin(self.relay_url, label="Go Relay URL")
		self.default_country_calling_code = "".join(
			character
			for character in str(self.default_country_calling_code or "91")
			if character.isdigit()
		)
		if not 1 <= len(self.default_country_calling_code) <= 3:
			frappe.throw("Default country calling code must contain 1 to 3 digits")
		if self.enabled and not self.hub_url:
			frappe.throw("Hub URL is required when WhatsApp Core is enabled")
		if self.enabled and not self.relay_url:
			frappe.throw("Go Relay URL is required when WhatsApp Core is enabled")
		if self.outbound_enabled and not self.enabled:
			frappe.throw("Enable WhatsApp Core before enabling outbound messages")

		channels = set()
		account_names = set()
		defaults = 0
		for row in self.accounts:
			if row.channel in channels:
				frappe.throw(f"Core channel is mapped more than once: {row.channel}")
			channels.add(row.channel)
			if row.account_name in account_names:
				frappe.throw(f"Hub account is mapped more than once: {row.account_name}")
			account_names.add(row.account_name)
			if row.get("template_service_user"):
				from frappe_whatsapp_core.permissions import is_dedicated_transport_user

				if not is_dedicated_transport_user(
					row.template_service_user, capability="template"
				):
					frappe.throw(
						"Template Service User must be an enabled, service-only Website User "
						"with exactly the WhatsApp Core Template Service role"
					)
			defaults += int(bool(row.is_default))
		if defaults > 1:
			frappe.throw("Only one Hub account can be the default")

	def get_hub_auth_headers(self) -> dict:
		api_key = self.get_password("api_key")
		api_secret = self.get_password("api_secret")
		if not api_key or not api_secret:
			frappe.throw("WhatsApp Core Hub credentials are not configured")
		return {
			"Authorization": f"token {api_key}:{api_secret}",
			"Content-Type": "application/json",
		}

	def get_account_name(self, channel: str) -> str:
		for row in self.accounts:
			if row.channel == channel:
				return row.account_name
		frappe.throw(f"No Hub account is mapped to Core channel {channel}")
