import unittest

from connectors.web_connector import RealWebConnector, _is_blocked_ip_literal


class WebSsrfLiteralIp16Tests(unittest.TestCase):
    def setUp(self):
        self.connector = RealWebConnector()

    def test_blocks_private_and_local_ipv4_literals(self):
        for url in (
            "http://127.0.0.1/",
            "http://10.0.0.1/",
            "http://172.16.0.1/",
            "http://192.168.1.1/",
            "http://169.254.169.254/latest/meta-data/",
            "http://0.0.0.0/",
        ):
            with self.subTest(url=url):
                result = self.connector.execute("read_page", {"url": url})
                self.assertFalse(result.success)
                self.assertEqual(result.error_code, "SSRF_BLOCKED")

    def test_blocks_private_and_local_ipv6_literals(self):
        for url in (
            "http://[::1]/",
            "http://[fc00::1]/",
            "http://[fe80::1]/",
        ):
            with self.subTest(url=url):
                result = self.connector.execute("read_page", {"url": url})
                self.assertFalse(result.success)
                self.assertEqual(result.error_code, "SSRF_BLOCKED")

    def test_public_ip_literal_is_not_classified_as_internal(self):
        self.assertFalse(_is_blocked_ip_literal("8.8.8.8"))
        self.assertFalse(_is_blocked_ip_literal("2001:4860:4860::8888"))

    def test_hostname_is_left_for_later_dns_validation(self):
        self.assertFalse(_is_blocked_ip_literal("example.com"))


if __name__ == "__main__":
    unittest.main()
