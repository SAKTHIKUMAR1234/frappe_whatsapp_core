from __future__ import annotations

import re

import frappe
from frappe.model.document import Document

from frappe_whatsapp_core.network_security import validate_service_origin


ICE_URL_PATTERN = re.compile(
	r"^(?P<scheme>stun|stuns|turn|turns):"
	r"(?P<host>\[[0-9a-f:]+\]|[a-z0-9.-]+)"
	r"(?::(?P<port>[0-9]{1,5}))?"
	r"(?:\?transport=(?:udp|tcp))?$",
	re.IGNORECASE,
)
DEFAULT_STUN_URL = "stun:stun.cloudflare.com:3478"


def parse_ice_urls(value, *, schemes, label):
	urls = []
	for candidate in re.split(r"[,\r\n]+", str(value or "")):
		url = candidate.strip()
		if not url:
			continue
		match = ICE_URL_PATTERN.fullmatch(url)
		if not match or match.group("scheme").lower() not in schemes:
			frappe.throw(f"{label} contains an invalid ICE server URL: {url}")
		port = match.group("port")
		if port and not 1 <= int(port) <= 65535:
			frappe.throw(f"{label} contains an invalid port: {url}")
		if url not in urls:
			urls.append(url)
	if len(urls) > 10:
		frappe.throw(f"{label} cannot contain more than 10 URLs")
	return urls


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

		stun_urls = parse_ice_urls(
			self.webrtc_stun_urls,
			schemes={"stun", "stuns"},
			label="STUN Server URLs",
		)
		turn_urls = parse_ice_urls(
			self.webrtc_turn_urls,
			schemes={"turn", "turns"},
			label="TURN Server URLs",
		)
		self.webrtc_stun_urls = "\n".join(stun_urls)
		self.webrtc_turn_urls = "\n".join(turn_urls)
		turn_username = str(self.webrtc_turn_username or "").strip()
		self.webrtc_turn_username = turn_username
		turn_credential = bool(self.webrtc_turn_credential)
		if turn_urls and (not turn_username or not turn_credential):
			frappe.throw("TURN Username and TURN Credential are required when TURN URLs are configured")
		if not turn_urls and (turn_username or turn_credential):
			frappe.throw("Configure a TURN Server URL before entering TURN credentials")

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

	def get_webrtc_ice_servers(self) -> list[dict]:
		stun_urls = parse_ice_urls(
			self.webrtc_stun_urls,
			schemes={"stun", "stuns"},
			label="STUN Server URLs",
		)
		turn_urls = parse_ice_urls(
			self.webrtc_turn_urls,
			schemes={"turn", "turns"},
			label="TURN Server URLs",
		)
		if not stun_urls and not turn_urls:
			return []
		servers = [{"urls": stun_urls or [DEFAULT_STUN_URL]}]
		if turn_urls:
			username = str(self.webrtc_turn_username or "").strip()
			credential = self.get_password("webrtc_turn_credential", raise_exception=False)
			if username and credential:
				servers.append({
					"urls": turn_urls,
					"username": username,
					"credential": credential,
				})
		return servers

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
