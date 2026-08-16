"""Network-boundary validation for operator-configured service origins."""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit

import frappe


def validate_service_origin(value: str, *, label: str) -> str:
	value = str(value or "").strip().rstrip("/")
	if not value:
		return ""
	parsed = urlsplit(value)
	if not parsed.hostname or parsed.username or parsed.password:
		frappe.throw(f"{label} must be an absolute service URL without credentials")
	if parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
		frappe.throw(f"{label} must contain only a service origin")

	literal = _literal_ip(parsed.hostname)
	developer_loopback = bool(frappe.conf.developer_mode) and bool(
		parsed.hostname == "localhost" or (literal and literal.is_loopback)
	)
	if parsed.scheme != "https" and not (parsed.scheme == "http" and developer_loopback):
		frappe.throw(f"{label} must use HTTPS")

	# Unit tests commonly use reserved .test names. Production and real request
	# paths resolve and re-check every address before opening a connection.
	try:
		port = parsed.port or (443 if parsed.scheme == "https" else 80)
	except ValueError:
		frappe.throw(f"{label} contains an invalid port")
	if not getattr(frappe.flags, "in_test", False):
		_validate_public_destination(
			parsed.hostname,
			port,
			developer_loopback,
			label,
		)
	return value


def _literal_ip(hostname: str):
	try:
		return ipaddress.ip_address(hostname)
	except ValueError:
		return None


def _validate_public_destination(
	hostname: str, port: int, developer_loopback: bool, label: str
) -> None:
	try:
		addresses = {
			ipaddress.ip_address(item[4][0])
			for item in socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
		}
	except (OSError, ValueError) as exception:
		frappe.throw(f"{label} host could not be resolved: {exception}")
	if not addresses:
		frappe.throw(f"{label} host did not resolve to an address")
	for address in addresses:
		if address.is_global:
			continue
		if developer_loopback and address.is_loopback:
			continue
		frappe.throw(f"{label} cannot target a private or reserved network address")
