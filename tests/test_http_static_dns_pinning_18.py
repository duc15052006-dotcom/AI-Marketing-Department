import socket
import unittest
from unittest.mock import patch

import httpx

from tools.gateway.http_transport import PinnedDNSHTTPTransport
from tools.gateway.security import SecurityValidationError, SecurityValidator
from tools.observation.http_backend import HttpStaticBackend


class HttpStaticDnsPinning18Tests(unittest.TestCase):
    @staticmethod
    def _public(ip: str, port: int = 443):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))]

    def test_transport_pins_validated_ip_and_preserves_host_and_sni(self):
        transport = PinnedDNSHTTPTransport()
        request = httpx.Request("GET", "https://public.example/path")
        seen = {}

        def fake_parent(_transport, inner_request):
            seen["url_host"] = inner_request.url.host
            seen["host_header"] = inner_request.headers.get("host")
            seen["sni"] = inner_request.extensions.get("sni_hostname")
            return httpx.Response(200, request=inner_request, content=b"ok")

        with patch.object(
            SecurityValidator,
            "resolve_public_addresses",
            return_value=self._public("8.8.8.8"),
        ) as resolver, patch.object(
            httpx.HTTPTransport,
            "handle_request",
            autospec=True,
            side_effect=fake_parent,
        ):
            response = transport.handle_request(request)

        self.assertEqual(response.status_code, 200)
        resolver.assert_called_once_with("public.example", 443)
        self.assertEqual(seen["url_host"], "8.8.8.8")
        self.assertEqual(seen["host_header"], "public.example")
        self.assertEqual(seen["sni"], "public.example")
        self.assertEqual(request.url.host, "public.example")
        self.assertNotIn("sni_hostname", request.extensions)

    def test_transport_falls_back_across_validated_public_addresses(self):
        transport = PinnedDNSHTTPTransport()
        request = httpx.Request("GET", "https://multi.example/")
        addresses = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("1.1.1.1", 443)),
        ]
        seen_hosts = []

        def fake_parent(_transport, inner_request):
            seen_hosts.append(inner_request.url.host)
            if len(seen_hosts) == 1:
                raise httpx.ConnectError("first address unavailable", request=inner_request)
            return httpx.Response(200, request=inner_request, content=b"ok")

        with patch.object(
            SecurityValidator,
            "resolve_public_addresses",
            return_value=addresses,
        ), patch.object(
            httpx.HTTPTransport,
            "handle_request",
            autospec=True,
            side_effect=fake_parent,
        ):
            response = transport.handle_request(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(seen_hosts, ["8.8.8.8", "1.1.1.1"])
        self.assertEqual(request.url.host, "multi.example")

    def test_rebinding_to_private_ip_is_blocked_at_transport_boundary(self):
        backend = HttpStaticBackend()
        initial_public = self._public("8.8.8.8")
        rebinding_error = SecurityValidationError(
            "SSRF_PRIVATE_NETWORK",
            "Access to private network IP '127.0.0.1' is blocked.",
        )

        with patch.object(
            SecurityValidator,
            "resolve_public_addresses",
            side_effect=[initial_public, rebinding_error],
        ):
            observation, error = backend.read_page(
                url="https://rebinding.example/secret",
                product_id="PROD_TEST",
                brand_id="BRAND_TEST",
            )

        self.assertIsNone(observation)
        self.assertIsNotNone(error)
        self.assertEqual(error.error_code, "SSRF_PRIVATE_NETWORK")
        self.assertFalse(error.retryable)


if __name__ == "__main__":
    unittest.main()
