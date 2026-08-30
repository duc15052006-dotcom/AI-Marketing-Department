import socket
import unittest
from unittest.mock import MagicMock, patch

from connectors.web_connector import RealWebConnector, _hostname_resolves_to_blocked_address


class WebSsrfDnsPrivate17Tests(unittest.TestCase):
    def setUp(self):
        self.connector = RealWebConnector()

    @patch("connectors.web_connector.socket.getaddrinfo")
    def test_dns_private_ipv4_is_blocked(self, getaddrinfo):
        getaddrinfo.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.23.4.5", 80)),
        ]
        with patch("connectors.web_connector.urllib.request.urlopen") as urlopen:
            result = self.connector.execute("read_page", {"url": "http://internal.example/"})
        self.assertFalse(result.success)
        self.assertEqual(result.error_code, "SSRF_BLOCKED")
        urlopen.assert_not_called()

    @patch("connectors.web_connector.socket.getaddrinfo")
    def test_dns_private_ipv6_is_blocked(self, getaddrinfo):
        getaddrinfo.return_value = [
            (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("fd00::42", 443, 0, 0)),
        ]
        self.assertTrue(_hostname_resolves_to_blocked_address("private.example", 443))

    @patch("connectors.web_connector.socket.getaddrinfo")
    def test_mixed_public_and_private_answers_fail_closed(self, getaddrinfo):
        getaddrinfo.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 80)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.5.4", 80)),
        ]
        self.assertTrue(_hostname_resolves_to_blocked_address("mixed.example", 80))

    @patch("connectors.web_connector.socket.getaddrinfo")
    def test_public_dns_answer_can_reach_http_dispatch(self, getaddrinfo):
        getaddrinfo.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 80)),
        ]
        response = MagicMock()
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        response.read.return_value = b"<html><body>public</body></html>"
        response.headers.get.return_value = "text/html"
        with patch("connectors.web_connector.urllib.request.urlopen", return_value=response) as urlopen:
            result = self.connector.execute("read_page", {"url": "http://public.example/"})
        self.assertTrue(result.success)
        urlopen.assert_called_once()


if __name__ == "__main__":
    unittest.main()
