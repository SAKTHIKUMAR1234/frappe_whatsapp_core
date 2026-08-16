"""Requests-compatible outbound HTTP with dial-time destination pinning."""

from __future__ import annotations

import ipaddress
import socket
import sys
from collections.abc import Callable

import frappe
import requests as _requests
from requests.adapters import HTTPAdapter
from urllib3.connection import HTTPConnection, HTTPSConnection
from urllib3.connectionpool import HTTPConnectionPool, HTTPSConnectionPool
from urllib3.exceptions import NewConnectionError
from urllib3.poolmanager import PoolManager

DEFAULT_TIMEOUT = (10, 30)
MAX_TIMEOUT_SECONDS = 120
MAX_RESPONSE_BYTES = 128 * 1024 * 1024

# Keep the normal requests exception API available to callers which import
# this module as ``requests``.
RequestException = _requests.RequestException
HTTPError = _requests.HTTPError
TooManyRedirects = _requests.TooManyRedirects


def _development_loopback_allowed() -> bool:
	return bool(getattr(frappe.conf, "developer_mode", False))


def _explicit_loopback(host: str) -> bool:
	host = str(host or "").strip("[]").lower()
	if host == "localhost" or host.endswith(".localhost"):
		return True
	try:
		return ipaddress.ip_address(host).is_loopback
	except ValueError:
		return False


def _normalized_address(value: str):
	address = ipaddress.ip_address(str(value).split("%", 1)[0])
	if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
		return address.ipv4_mapped
	return address


def _resolve_destination(
	host: str,
	port: int,
	*,
	resolver: Callable | None = None,
) -> list[tuple]:
	resolver = resolver or socket.getaddrinfo
	try:
		rows = resolver(host, port, socket.AF_UNSPEC, socket.SOCK_STREAM)
	except (OSError, ValueError) as exception:
		raise OSError(f"outbound host {host!r} could not be resolved") from exception
	if not rows:
		raise OSError(f"outbound host {host!r} resolved to no addresses")

	allow_loopback = _development_loopback_allowed() and _explicit_loopback(host)
	result = []
	seen = set()
	for family, socktype, proto, canonname, sockaddr in rows:
		try:
			raw_address = ipaddress.ip_address(str(sockaddr[0]).split("%", 1)[0])
			address = _normalized_address(sockaddr[0])
		except ValueError as exception:
			raise OSError(f"outbound host {host!r} returned an invalid address") from exception
		if not address.is_global and not (allow_loopback and address.is_loopback):
			raise OSError(f"outbound host {host!r} resolved to a non-public address")
		key = (family, socktype, proto, str(raw_address), sockaddr[1:])
		if key in seen:
			continue
		seen.add(key)
		pinned = (str(raw_address), *sockaddr[1:])
		result.append((family, socktype, proto, canonname, pinned))
	return result


def _connect_candidate(connection, candidate):
	family, socktype, proto, _canonname, sockaddr = candidate
	sock = socket.socket(family, socktype, proto)
	try:
		for option in connection.socket_options or ():
			sock.setsockopt(*option)
		if connection.source_address:
			sock.bind(connection.source_address)
		sock.settimeout(connection.timeout)
		sock.connect(sockaddr)
		return sock
	except BaseException:
		sock.close()
		raise


class _PinnedConnectionMixin:
	def _new_conn(self):
		try:
			candidates = _resolve_destination(self.host, self.port)
			last_error = None
			for candidate in candidates:
				try:
					sock = _connect_candidate(self, candidate)
					sys.audit("http.client.connect", self, self.host, self.port)
					return sock
				except OSError as exception:
					last_error = exception
			raise last_error or OSError("no validated outbound address was reachable")
		except OSError as exception:
			raise NewConnectionError(
				self, f"Failed to establish a safe connection to {self.host}: {exception}"
			) from exception


class _PinnedHTTPConnection(_PinnedConnectionMixin, HTTPConnection):
	pass


class _PinnedHTTPSConnection(_PinnedConnectionMixin, HTTPSConnection):
	pass


class _PinnedHTTPConnectionPool(HTTPConnectionPool):
	ConnectionCls = _PinnedHTTPConnection


class _PinnedHTTPSConnectionPool(HTTPSConnectionPool):
	ConnectionCls = _PinnedHTTPSConnection


class _PinnedPoolManager(PoolManager):
	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		self.pool_classes_by_scheme = {
			"http": _PinnedHTTPConnectionPool,
			"https": _PinnedHTTPSConnectionPool,
		}


class SafeHTTPAdapter(HTTPAdapter):
	def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
		self._pool_connections = connections
		self._pool_maxsize = maxsize
		self._pool_block = block
		self.poolmanager = _PinnedPoolManager(
			num_pools=connections,
			maxsize=maxsize,
			block=block,
			**pool_kwargs,
		)

	def proxy_manager_for(self, *args, **kwargs):
		raise RequestException("outbound HTTP proxies are disabled")

	def send(self, request, stream=False, timeout=None, verify=True, cert=None, proxies=None):
		if proxies:
			raise RequestException("outbound HTTP proxies are disabled")
		response = super().send(
			request,
			stream=True,
			timeout=timeout,
			verify=verify,
			cert=cert,
			proxies={},
		)
		try:
			content = response.raw.read(MAX_RESPONSE_BYTES + 1, decode_content=True)
			if len(content) > MAX_RESPONSE_BYTES:
				raise RequestException("outbound HTTP response exceeded the size limit")
		finally:
			response.close()
		response._content = content
		response._content_consumed = True
		return response


def _bounded_timeout(value):
	if value is None:
		return DEFAULT_TIMEOUT
	if isinstance(value, tuple):
		if len(value) != 2:
			raise ValueError("timeout must be a number or (connect, read) pair")
		return tuple(min(float(item), MAX_TIMEOUT_SECONDS) for item in value)
	return min(float(value), MAX_TIMEOUT_SECONDS)


class Session(_requests.Session):
	def __init__(self):
		super().__init__()
		self.trust_env = False
		adapter = SafeHTTPAdapter(max_retries=0)
		self.mount("http://", adapter)
		self.mount("https://", adapter)

	def request(self, method, url, **kwargs):
		if kwargs.get("proxies"):
			raise RequestException("outbound HTTP proxies are disabled")
		kwargs["allow_redirects"] = False
		kwargs["proxies"] = {}
		kwargs["timeout"] = _bounded_timeout(kwargs.get("timeout"))
		return super().request(method, url, **kwargs)


_session = Session()


def request(method, url, **kwargs):
	return _session.request(method, url, **kwargs)


def get(url, **kwargs):
	return _session.get(url, **kwargs)


def post(url, data=None, json=None, **kwargs):
	return _session.post(url, data=data, json=json, **kwargs)


def put(url, data=None, **kwargs):
	return _session.put(url, data=data, **kwargs)


def patch(url, data=None, **kwargs):
	return _session.patch(url, data=data, **kwargs)


def delete(url, **kwargs):
	return _session.delete(url, **kwargs)
