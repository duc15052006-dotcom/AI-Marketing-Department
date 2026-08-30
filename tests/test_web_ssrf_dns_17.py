import socket
import unittest
from unittest.mock import MagicMock, patch

from connectors.web_connector import RealWebConnector
from tools.gateway.security import SecurityValidationError, SecurityValidator
from tools.receipts import ExecutionMode


class WebSsrfDns17Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.connector = RealWebConnector()

    def test_hostname_resolving_to_private_ip_is_blocked_before_http(self):
        private_dns_answer = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.20.30.40", 0)),
        ]
        with patch("tools.gateway.security.socket.getaddrinfo", return_value=private_dns_answer), patch(
            "connectors.web_connector.urllib.request.urlopen"
        ) as urlopen:
            result = self.connector.execute("read_page", {"url": "https://public-looking.example/path"})

        self.assertFalse(result.success)
        self.assertEqual(result.error_code, "SSRF_BLOCKED")
        urlopen.assert_not_called()

    def test_unresolvable_hostname_fails_closed_before_http(self):
        with patch(
            "tools.gateway.security.socket.getaddrinfo",
            side_effect=socket.gaierror("not found"),
        ), patch("connectors.web_connector.urllib.request.urlopen") as urlopen:
            result = self.connector.execute("read_page", {"url": "https://unresolvable.example/path"})

        self.assertFalse(result.success)
        self.assertEqual(result.error_code, "DNS_RESOLUTION_FAILED")
        urlopen.assert_not_called()

    def test_empty_dns_answer_fails_closed(self):
        with patch("tools.gateway.security.socket.getaddrinfo", return_value=[]):
            with self.assertRaises(SecurityValidationError) as ctx:
                SecurityValidator.validate_url("https://empty-dns.example/")

        self.assertEqual(ctx.exception.code, "DNS_RESOLUTION_FAILED")

    def test_public_dns_answer_can_reach_mocked_http_transport(self):
        public_dns_answer = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 0)),
        ]
        response = MagicMock()
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        response.read.return_value = b"<html><body><h1>Public page</h1></body></html>"
        response.headers.get.return_value = "text/html; charset=utf-8"

        with patch("tools.gateway.security.socket.getaddrinfo", return_value=public_dns_answer), patch(
            "connectors.web_connector.urllib.request.urlopen", return_value=response
        ) as urlopen:
            result = self.connector.execute("read_page", {"url": "https://public.example/page"})

        self.assertTrue(result.success)
        self.assertEqual(result.execution_mode, ExecutionMode.REAL)
        self.assertIn("Public page", result.data["extracted_text"])
        urlopen.assert_called_once()


if __name__ == "__main__":
    unittest.main()
