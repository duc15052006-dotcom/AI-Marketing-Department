"""SSRF-safe HTTPX transport helpers.

The transport resolves each outbound hostname through ``SecurityValidator`` and
connects HTTPX to the validated IP address while preserving the original Host
header and TLS SNI hostname.  This closes the DNS-rebinding/TOCTOU gap between
URL validation and the socket connection without disabling normal certificate
verification.
"""

from __future__ import annotations

from typing import Any

import httpx

from tools.gateway.security import SecurityValidator


class PinnedDNSHTTPTransport(httpx.HTTPTransport):
    """HTTPX transport that connects only to DNS answers validated as public.

    HTTPX normally resolves the request hostname inside the transport.  A
    separate SSRF pre-check therefore leaves a time-of-check/time-of-use gap.
    Here we resolve and validate immediately before dispatch, rewrite only the
    transport URL host to the validated IP, and retain the original HTTP Host
    header plus TLS SNI through ``sni_hostname``.
    """

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        original_url = request.url
        original_host = original_url.host
        if not original_host:
            raise httpx.InvalidURL("Outbound HTTP request is missing a hostname.")

        port = original_url.port
        if port is None:
            port = 443 if original_url.scheme == "https" else 80

        # Fail closed: the shared validator raises before any socket is opened if
        # DNS fails or if any answer is private/local/reserved.
        addresses = SecurityValidator.resolve_public_addresses(original_host, port)

        last_error: Exception | None = None
        original_sni: Any = request.extensions.get("sni_hostname")
        had_original_sni = "sni_hostname" in request.extensions

        try:
            request.extensions["sni_hostname"] = original_host

            # Preserve normal multi-address resilience.  Each candidate has
            # already been validated public; retry only connection-establishment
            # failures and never re-resolve the hostname inside HTTPX.
            for entry in addresses:
                ip_address = entry[4][0]
                request.url = original_url.copy_with(host=ip_address)
                try:
                    return super().handle_request(request)
                except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                    last_error = exc

            if last_error is not None:
                raise last_error
            raise httpx.ConnectError("No validated public address was available.", request=request)
        finally:
            # Keep caller-visible request provenance truthful even though the
            # transport connected to a pinned IP internally.
            request.url = original_url
            if had_original_sni:
                request.extensions["sni_hostname"] = original_sni
            else:
                request.extensions.pop("sni_hostname", None)
