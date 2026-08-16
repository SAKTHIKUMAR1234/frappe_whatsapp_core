import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from unittest.mock import MagicMock, patch

import requests
from frappe.tests.utils import FrappeTestCase

from frappe_whatsapp_core import safe_http


def _answer(address):
	ip = address.split("%", 1)[0]
	family = socket.AF_INET6 if ":" in ip else socket.AF_INET
	sockaddr = (address, 443, 0, 0) if family == socket.AF_INET6 else (address, 443)
	return (family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", sockaddr)


class _Handler(BaseHTTPRequestHandler):
	target_calls = 0

	def do_GET(self):
		if self.path == "/redirect":
			self.send_response(302)
			self.send_header("Location", "/target")
			self.end_headers()
			return
		if self.path == "/target":
			type(self).target_calls += 1
		body = b"healthy"
		self.send_response(200)
		self.send_header("Content-Length", str(len(body)))
		self.end_headers()
		self.wfile.write(body)

	def log_message(self, *_args):
		return


class TestSafeHTTP(FrappeTestCase):
	def test_private_and_mixed_dns_are_rejected_before_dial(self):
		for addresses in (
			["10.1.2.3"],
			["93.184.216.34", "127.0.0.1"],
			["169.254.169.254"],
			["100.64.0.1"],
			["::1"],
			["::ffff:127.0.0.1"],
		):
			resolver = MagicMock(return_value=[_answer(item) for item in addresses])
			with self.assertRaisesRegex(OSError, "non-public address"):
				safe_http._resolve_destination("tenant.example", 443, resolver=resolver)

	def test_resolution_is_pinned_without_a_second_dns_lookup(self):
		resolver = MagicMock(
			side_effect=[[_answer("93.184.216.34")], [_answer("127.0.0.1")]]
		)
		connection = safe_http._PinnedHTTPSConnection("tenant.example", 443)
		with (
			patch("frappe_whatsapp_core.safe_http.socket.getaddrinfo", resolver),
			patch("frappe_whatsapp_core.safe_http._connect_candidate", return_value=MagicMock()) as dial,
		):
			connection._new_conn()
		resolver.assert_called_once()
		self.assertEqual(dial.call_args.args[1][4][0], "93.184.216.34")

	def test_tls_keeps_origin_hostname_for_sni_and_certificate_verification(self):
		connection = safe_http._PinnedHTTPSConnection("tenant.example", 443)
		wrapped = MagicMock()
		wrapped.socket.selected_alpn_protocol.return_value = "http/1.1"
		with (
			patch.object(connection, "_new_conn", return_value=MagicMock()),
			patch("urllib3.connection.http2_probe.acquire_and_get", return_value=False),
			patch(
				"urllib3.connection._ssl_wrap_socket_and_match_hostname",
				return_value=wrapped,
			) as wrap,
		):
			connection.connect()
		self.assertEqual(connection.host, "tenant.example")
		self.assertEqual(wrap.call_args.kwargs["server_hostname"], "tenant.example")
		self.assertIsNone(wrap.call_args.kwargs["assert_hostname"])

	def test_redirect_is_rejected_without_calling_target(self):
		server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
		thread = Thread(target=server.serve_forever, daemon=True)
		thread.start()
		_Handler.target_calls = 0
		try:
			with patch(
				"frappe_whatsapp_core.safe_http._development_loopback_allowed",
				return_value=True,
			):
				response = safe_http.get(
					f"http://127.0.0.1:{server.server_port}/redirect",
					timeout=2,
				)
			self.assertEqual(response.status_code, 302)
			self.assertEqual(_Handler.target_calls, 0)
		finally:
			server.shutdown()
			server.server_close()
			thread.join(timeout=2)

	def test_response_body_is_bounded_and_proxies_are_rejected(self):
		server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
		thread = Thread(target=server.serve_forever, daemon=True)
		thread.start()
		try:
			with (
				patch(
					"frappe_whatsapp_core.safe_http._development_loopback_allowed",
					return_value=True,
				),
				patch("frappe_whatsapp_core.safe_http.MAX_RESPONSE_BYTES", 4),
			):
				with self.assertRaisesRegex(requests.RequestException, "size limit"):
					safe_http.get(f"http://127.0.0.1:{server.server_port}/", timeout=2)
			with self.assertRaisesRegex(requests.RequestException, "proxies are disabled"):
				safe_http.get("https://tenant.example", proxies={"https": "http://proxy"})
		finally:
			server.shutdown()
			server.server_close()
			thread.join(timeout=2)
