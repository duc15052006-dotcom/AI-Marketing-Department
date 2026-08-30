import socket
import unittest
import urllib.request
from unittest.mock import MagicMock, patch

from connectors.web_connector import (
    RealWebConnector,
    _SafeRedirectHandler,
    _safe_create_connection,
)
from tools.gateway.security import SecurityValidationError
from tools.receipts import ExecutionMode


class WebConnectorSsrf11Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.connector = RealWebConnector()

    def test_private_and_special_ip_literals_are_blocked_before_network(self):
        blocked_urls = (
            "http://127.0.0.1/",
            "http://10.0.0.1/",
            "http://172.16.0.1/",
            "http://192.168.1.1/",
            "http://169.254.1.1/",
            "http://[::1]/",
            "http://[fc00::1]/",
            "http://[fe80::1]/",
            "http://[::ffff:127.0.0.1]/",
        )

        with patch("connectors.web_connector.urllib.request.build_opener") as build_opener:
            for url in blocked_urls:
                with self.subTest(url=url):
                    result = self.connector.execute("read_page", {"url": url})
                    self.assertFalse(result.success)
                    self.assertEqual(result.error_code, "SSRF_BLOCKED")
            build_opener.assert_not_called()

    def test_hostname_resolving_to_private_ip_is_blocked(self):
        private_dns_answer = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.20.30.40", 0)),
        ]
        with patch("tools.gateway.security.socket.getaddrinfo", return_value=private_dns_answer), patch(
            "connectors.web_connector.urllib.request.build_opener"
        ) as build_opener:
            result = self.connector.execute("read_page", {"url": "https://public-looking.example/path"})

        self.assertFalse(result.success)
        self.assertEqual(result.error_code, "SSRF_BLOCKED")
        build_opener.assert_not_called()

    def test_unresolvable_hostname_fails_closed_before_network(self):
        with patch(
            "tools.gateway.security.socket.getaddrinfo",
            side_effect=socket.gaierror("not found"),
        ), patch("connectors.web_connector.urllib.request.build_opener") as build_opener:
            result = self.connector.execute("read_page", {"url": "https://unresolvable.example/path"})

        self.assertFalse(result.success)
        self.assertEqual(result.error_code, "DNS_RESOLUTION_FAILED")
        build_opener.assert_not_called()

    def test_redirect_handler_rejects_private_destination_before_follow(self):
        handler = _SafeRedirectHandler()
        request = urllib.request.Request("https://safe.example/start")

        with self.assertRaises(SecurityValidationError):
            handler.redirect_request(
                request,
                None,
                302,
                "Found",
                {},
                "http://192.168.0.50/admin",
            )

    def test_safe_connection_rejects_private_rebinding_answer_before_socket(self):
        private_dns_answer = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443)),
        ]
        with patch("tools.gateway.security.socket.getaddrinfo", return_value=private_dns_answer), patch(
            "connectors.web_connector.socket.socket"
        ) as socket_ctor:
            with self.assertRaises(SecurityValidationError):
                _safe_create_connection(("rebinding.example", 443), timeout=1.0)

        socket_ctor.assert_not_called()

    def test_safe_connection_connects_to_validated_sockaddr_without_reresolve(self):
        public_dns_answer = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443)),
        ]
        sock = MagicMock()
        with patch(
            "tools.gateway.security.socket.getaddrinfo",
            return_value=public_dns_answer,
        ) as getaddrinfo, patch("connectors.web_connector.socket.socket", return_value=sock):
            connected = _safe_create_connection(("public.example", 443), timeout=2.0)

        self.assertIs(connected, sock)
        getaddrinfo.assert_called_once_with(
            "public.example",
            443,
            socket.AF_UNSPEC,
            socket.SOCK_STREAM,
        )
        sock.connect.assert_called_once_with(("8.8.8.8", 443))

    def test_public_target_can_use_real_read_path_with_mocked_transport(self):
        public_dns_answer = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 0)),
        ]
        response = MagicMock()
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        response.read.return_value = b"<html><body><h1>Public page</h1></body></html>"
        response.headers.get.return_value = "text/html; charset=utf-8"
        response.geturl.return_value = "https://public.example/page"

        opener = MagicMock()
        opener.open.return_value = response

        with patch("tools.gateway.security.socket.getaddrinfo", return_value=public_dns_answer), patch(
            "connectors.web_connector.urllib.request.build_opener", return_value=opener
        ) as build_opener:
            result = self.connector.execute("read_page", {"url": "https://public.example/page"})

        self.assertTrue(result.success)
        self.assertEqual(result.execution_mode, ExecutionMode.REAL)
        self.assertEqual(result.data["url"], "https://public.example/page")
        self.assertIn("Public page", result.data["extracted_text"])
        build_opener.assert_called_once()
        opener.open.assert_called_once()


if __name__ == "__main__":
    unittest.main()
