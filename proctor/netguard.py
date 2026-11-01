"""SSRF protection for customer-supplied endpoints (docs/06 security).

A chat Target URL is attacker-controllable, and the server makes outbound requests to it. Without
restriction a caller could point us at internal services or the cloud metadata endpoint
(169.254.169.254).

Two layers:
- validate_external_url(): cheap pre-check (scheme + resolved IPs are public).
- safe_request(): the actual fetch — resolves once, validates every IP, then connects to that exact
  validated IP (pinned), presenting the real hostname for SNI + cert verification. Pinning closes
  the DNS-rebinding window where a host flips to an internal address between the check and the
  connect. Redirects are disabled and the response body is size-capped.
"""

from __future__ import annotations

import ipaddress
import json as _json
import socket
from urllib.parse import urlparse

import certifi
import urllib3


class UnsafeURLError(ValueError):
    """Raised when a target URL resolves to a disallowed destination."""


def _assert_public_ip(ip: ipaddress._BaseAddress) -> None:
    if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
            or ip.is_multicast or ip.is_unspecified):
        raise UnsafeURLError(f"address {ip} is non-public; refusing to connect.")


def _resolve_public_ips(host: str, port: int) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise UnsafeURLError(f"could not resolve host '{host}': {e}")
    ips = []
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        _assert_public_ip(ip)
        ips.append(str(ip))
    if not ips:
        raise UnsafeURLError(f"host '{host}' did not resolve to any address.")
    return ips


def validate_external_url(url: str) -> str:
    """Return the URL if it is a safe public http(s) endpoint, else raise UnsafeURLError."""
    p = urlparse(url)
    if p.scheme not in ("http", "https"):
        raise UnsafeURLError(f"URL scheme must be http or https, got '{p.scheme or 'none'}'.")
    if not p.hostname:
        raise UnsafeURLError("URL has no host.")
    _resolve_public_ips(p.hostname, p.port or (443 if p.scheme == "https" else 80))
    return url


def safe_request(method: str, url: str, *, json_body=None, headers: dict | None = None,
                 timeout: int = 15, max_bytes: int = 65536) -> tuple[int, str]:
    """Make an outbound request pinned to a validated public IP (rebinding-safe).

    Returns (status_code, body_text). Raises UnsafeURLError if the URL/host is disallowed.
    """
    p = urlparse(url)
    if p.scheme not in ("http", "https"):
        raise UnsafeURLError(f"URL scheme must be http or https, got '{p.scheme or 'none'}'.")
    host = p.hostname
    if not host:
        raise UnsafeURLError("URL has no host.")
    default_port = 443 if p.scheme == "https" else 80
    port = p.port or default_port
    ip = _resolve_public_ips(host, port)[0]        # validate, then pin the exact IP we connect to

    hdrs = dict(headers or {})
    # Include an explicit non-default port in the Host header so port-aware virtual hosts route
    # our request the same way a direct client's would.
    hdrs["Host"] = host if (p.port in (None, default_port)) else f"{host}:{port}"
    body = None
    if json_body is not None:
        body = _json.dumps(json_body).encode()
        hdrs.setdefault("Content-Type", "application/json")
    path = p.path or "/"
    if p.query:
        path += "?" + p.query

    if p.scheme == "https":
        pool = urllib3.HTTPSConnectionPool(
            ip, port=port, server_hostname=host, assert_hostname=host,
            cert_reqs="CERT_REQUIRED", ca_certs=certifi.where(), timeout=timeout, retries=False)
    else:
        pool = urllib3.HTTPConnectionPool(ip, port=port, timeout=timeout, retries=False)
    try:
        # Stream the body and stop reading at max_bytes, so a malicious endpoint streaming an
        # arbitrarily large response cannot exhaust server memory (the cap is enforced on read,
        # not after buffering the whole body).
        r = pool.urlopen(method, path, body=body, headers=hdrs, redirect=False,
                         preload_content=False)
        try:
            raw = r.read(max_bytes + 1)
        finally:
            r.release_conn()
    finally:
        pool.close()
    truncated = raw[:max_bytes]
    return r.status, (truncated.decode("utf-8", "replace") if truncated else "")
