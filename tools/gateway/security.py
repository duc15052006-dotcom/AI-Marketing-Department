"""Security and SSRF Protection Layer for Tool Gateway.

Validates URLs, performs safe DNS resolution, prevents private-network SSRF access,
rejects embedded credentials, handles IP normalization (including IPv4-mapped IPv6),
and enforces content-size and protocol boundaries.
"""

from __future__ import annotations

import ipaddress
import socket
import urllib.parse
from typing import List, Optional


class SecurityValidationError(Exception):
    """Raised when an outbound URL violates security, SSRF, or credential constraints."""
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class SecurityValidator:
    """Validates outbound HTTP targets to prevent SSRF and internal network probing."""

    ALLOWED_SCHEMES = {"http", "https"}
    MAX_WIRE_BYTES = 5 * 1024 * 1024       # 5 MB
    MAX_DECODED_BYTES = 10 * 1024 * 1024   # 10 MB
    DEFAULT_TIMEOUT_SECONDS = 15.0

    FORBIDDEN_HOSTNAMES = {
        "localhost",
        "localhost.localdomain",
        "local",
        "metadata.google.internal",
        "instance-data",
        "169.254.169.254",  # AWS/GCP/Azure link-local metadata IP
    }

    @classmethod
    def validate_url(cls, url: str, allowed_domains: Optional[List[str]] = None) -> str:
        """Thoroughly validate outbound URL against SSRF, forbidden schemes, credentials, and private IPs."""
        if not url or not isinstance(url, str):
            raise SecurityValidationError("INVALID_URL", "Target URL must be a non-empty string.")

        cleaned = url.strip()
        parsed = urllib.parse.urlparse(cleaned)

        # 1. Scheme Validation
        if not parsed.scheme or parsed.scheme.lower() not in cls.ALLOWED_SCHEMES:
            raise SecurityValidationError(
                "FORBIDDEN_SCHEME",
                f"URL scheme '{parsed.scheme}' is forbidden. Only HTTP and HTTPS are permitted.",
            )

        # 2. Embedded Credentials / UserInfo Rejection
        if parsed.username or parsed.password or "@" in (parsed.netloc.split(":")[0] if parsed.netloc else ""):
            raise SecurityValidationError(
                "CREDENTIALS_IN_URL_REJECTED",
                "URLs containing embedded username/password credentials are strictly prohibited.",
            )

        raw_hostname = parsed.hostname
        if not raw_hostname:
            raise SecurityValidationError("MISSING_HOST", "Target URL does not contain a valid hostname.")

        # 3. Hostname Normalization (Strip trailing dots, lowercase, IDNA)
        hostname_normalized = raw_hostname.strip().rstrip(".").lower()
        if not hostname_normalized:
            raise SecurityValidationError("INVALID_HOST", "Target URL contains an empty normalized hostname.")

        try:
            # Normalize IDNA / Unicode domains
            hostname_ascii = hostname_normalized.encode("idna").decode("ascii")
        except Exception:
            hostname_ascii = hostname_normalized

        # 4. Direct Forbidden Hostname / Keyword Check
        if hostname_ascii in cls.FORBIDDEN_HOSTNAMES:
            raise SecurityValidationError(
                "SSRF_BLOCKED_HOST",
                f"Access to protected/private hostname '{raw_hostname}' is strictly blocked.",
            )

        # 5. IP Address Validation (Literal IP in URL, including IPv4-mapped IPv6)
        try:
            # Handle bracketed IPv6 notation if present
            clean_ip_str = hostname_ascii.strip("[]")
            ip = ipaddress.ip_address(clean_ip_str)
            cls._verify_ip_safety(ip)
        except ValueError:
            # Hostname is a domain name; perform a fail-closed DNS safety check.
            cls._verify_dns_resolution_safety(hostname_ascii)

        # 6. Optional Domain Whitelist Enforcement
        if allowed_domains:
            matched = any(
                hostname_ascii == d.lower() or hostname_ascii.endswith(f".{d.lower()}")
                for d in allowed_domains
            )
            if not matched:
                raise SecurityValidationError(
                    "DOMAIN_NOT_ALLOWED",
                    f"Domain '{raw_hostname}' is not in the configured allowed domains whitelist.",
                )

        return cleaned

    @classmethod
    def _verify_ip_safety(cls, ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> None:
        """Verify that an IP address is public and not within private, loopback, or link-local ranges.

        Handles IPv4-mapped IPv6 addresses (e.g. ::ffff:127.0.0.1, ::ffff:10.0.0.1).
        """
        # 1. Inspect IPv4-mapped IPv6 addresses
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
            # Validate underlying mapped IPv4
            cls._verify_ip_safety(ip.ipv4_mapped)
            return

        # 2. Standard IP Range Verification
        if ip.is_loopback:
            raise SecurityValidationError("SSRF_LOOPBACK", f"Access to loopback IP '{ip}' is blocked.")
        if ip.is_private:
            raise SecurityValidationError("SSRF_PRIVATE_NETWORK", f"Access to private network IP '{ip}' is blocked.")
        if ip.is_link_local:
            raise SecurityValidationError("SSRF_LINK_LOCAL", f"Access to link-local IP '{ip}' is blocked.")
        if ip.is_multicast or ip.is_reserved or ip.is_unspecified:
            raise SecurityValidationError("SSRF_RESERVED_IP", f"Access to reserved/multicast IP '{ip}' is blocked.")

        # Additional IPv6 unique local addresses check (fc00::/7)
        if isinstance(ip, ipaddress.IPv6Address) and (ip.is_site_local or ip.is_private):
            raise SecurityValidationError("SSRF_PRIVATE_NETWORK", f"Access to private IPv6 '{ip}' is blocked.")

    @classmethod
    def resolve_public_addresses(cls, hostname: str, port: Optional[int] = None):
        """Resolve a hostname and return only after every result is proven public.

        DNS resolution fails closed: an unresolvable hostname, an empty/invalid DNS
        answer, or any private/local address is rejected before network dispatch.
        Callers that later open sockets can reuse this result to avoid re-resolving.
        """
        try:
            addr_info = socket.getaddrinfo(
                hostname,
                port,
                socket.AF_UNSPEC,
                socket.SOCK_STREAM,
            )
        except (socket.gaierror, OSError) as exc:
            raise SecurityValidationError(
                "DNS_RESOLUTION_FAILED",
                f"Hostname '{hostname}' could not be resolved safely.",
            ) from exc

        if not addr_info:
            raise SecurityValidationError(
                "DNS_RESOLUTION_FAILED",
                f"Hostname '{hostname}' returned no usable addresses.",
            )

        validated = []
        for entry in addr_info:
            sockaddr = entry[4]
            if not sockaddr:
                raise SecurityValidationError(
                    "DNS_RESOLUTION_FAILED",
                    f"Hostname '{hostname}' returned an invalid address record.",
                )

            ip_str = sockaddr[0]
            try:
                ip = ipaddress.ip_address(ip_str)
            except ValueError as exc:
                raise SecurityValidationError(
                    "DNS_RESOLUTION_FAILED",
                    f"Hostname '{hostname}' returned a non-IP address record.",
                ) from exc

            cls._verify_ip_safety(ip)
            validated.append(entry)

        return validated

    @classmethod
    def _verify_dns_resolution_safety(cls, hostname: str) -> None:
        """Resolve hostname via DNS and ensure every resolved IP is public."""
        cls.resolve_public_addresses(hostname, None)
