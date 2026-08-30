import socket
import unittest
import urllib.request
from unittest.mock import MagicMock, patch

from connectors.web_connector import (
    RealWebConnector,
    _SafeRedirectHandler,
    _safe_create_connection,
)
from tools.gateway.security import SecurityValidationError, SecurityValidator
from tools.receipts import ExecutionMode


class WebConnectorRebinding19Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.connector = RealWebConnector()

    def test_redirect_to_private_destination_is_rejected_before_follow(self):
        handler = _SafeRedirectHandler()
        request = urllib.request.Request("https://safe.example/start")

        with self.assertRaises(SecurityValidationError) as ctx:
            handler.redirect_request(
                request,
                None,
                302,
                "Found",
                {},
                "http://192.168.1.50/admin",
            )

        self.assertTrue(ctx.exception.code.startswith("SSRF_"))

    def test_rebinding_private_answer_is_blocked_before_socket_creation(self):
        error = SecurityValidationError(
            "SSRF_PRIVATE_NETWORK",
            "Access to private network IP '127.0.0.1' is blocked.",
        )
        with patch.object(
            SecurityValidator,
            "resolve_public_addresses",
            side_effect=error,
        ), patch("connectors.web_connector.socket.socket") as socket_ctor:
            with self.assertRaises(SecurityValidationError):
                _safe_create_connection(("rebinding.example", 443), timeout=1.0)

        socket_ctor.assert_not_called()

    def test_connection_uses_validated_sockaddr_without_hostname_reresolve(self):
        public_dns_answer = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443)),
        ]
        sock = MagicMock()

        with patch.object(
            SecurityValidator,
            "resolve_public_addresses",
            return_value=public_dns_answer,
        ) as resolver, patch(
            "connectors.web_connector.socket.socket",
            return_value=sock,
        ):
            connected = _safe_create_connection(("public.example", 443), timeout=2.0)

        self.assertIs(connected, sock)
        resolver.assert_called_once_with("public.example", 443)
        sock.settimeout.assert_called_once_with(2.0)
        sock.connect.assert_called_once_with(("8.8.8.8", 443))

    def test_execute_maps_redirect_security_failure_without_network_error_masking(self):
        opener = MagicMock()
        opener.open.side_effect = SecurityValidationError(
            "SSRF_PRIVATE_NETWORK",
            "redirect rebound to private IP",
        )

        with patch.object(
            SecurityValidator,
            "validate_url",
            return_value="https://public.example/start",
        ), patch(
            "connectors.web_connector.urllib.request.build_opener",
            return_value=opener,
        ) as build_opener:
            result = self.connector.execute(
                "read_page",
                {"url": "https://public.example/start"},
            )

        self.assertFalse(result.success)
        self.assertEqual(result.error_code, "SSRF_BLOCKED")
        self.assertIn("SSRF_PRIVATE_NETWORK", result.error_message)
        build_opener.assert_called_once()
        handlers = build_opener.call_args.args
        self.assertTrue(any(isinstance(h, urllib.request.ProxyHandler) for h in handlers))
        self.assertTrue(any(isinstance(h, _SafeRedirectHandler) for h in handlers))

    def test_safe_public_mocked_fetch_preserves_final_redirect_url(self):
        response = MagicMock()
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        response.read.return_value = b"<html><body><h1>Public page</h1></body></html>"
        response.headers.get.return_value = "text/html; charset=utf-8"
        response.geturl.return_value = "https://public.example/final"

        opener = MagicMock()
        opener.open.return_value = response

        with patch.object(
            SecurityValidator,
            "validate_url",
            return_value="https://public.example/start",
        ), patch(
            "connectors.web_connector.urllib.request.build_opener",
            return_value=opener,
        ):
            result = self.connector.execute(
                "read_page",
                {"url": "https://public.example/start"},
            )

        self.assertTrue(result.success)
        self.assertEqual(result.execution_mode, ExecutionMode.REAL)
        self.assertEqual(result.data["url"], "https://public.example/final")
        self.assertIn("Public page", result.data["extracted_text"])


if __name__ == "__main__":
    unittest.main()
