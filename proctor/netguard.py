"""SSRF protection for customer-supplied chat endpoints (docs/06 security).

A chat Target URL is attacker-controllable, and the server makes outbound POSTs to it. Without
restriction a caller could point us at internal services or the cloud metadata endpoint
(169.254.169.254). We allow only http(s) to public, non-reserved IPs.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse


class UnsafeURLError(ValueError):
    """Raised when a target URL resolves to a disallowed destination."""


def validate_external_url(url: str) -> str:
    """Return the URL if it is a safe public http(s) endpoint, else raise UnsafeURLError."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise UnsafeURLError(f"URL scheme must be http or https, got '{parsed.scheme or 'none'}'.")
    host = parsed.hostname
    if not host:
        raise UnsafeURLError("URL has no host.")

    # Resolve every address the host maps to; reject if any is non-public.
    try:
        infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80),
                                   proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise UnsafeURLError(f"Could not resolve host '{host}': {e}")

    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
                or ip.is_multicast or ip.is_unspecified):
            raise UnsafeURLError(
                f"Host '{host}' resolves to a non-public address ({ip}); refusing to test it.")
    return url
