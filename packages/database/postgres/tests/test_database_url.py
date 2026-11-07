import unittest

from agent_platform_database_postgres import normalize_database_url


class NormalizeDatabaseUrlTest(unittest.TestCase):
    def test_localhost_is_pinned_to_ipv4(self):
        self.assertEqual(
            normalize_database_url("postgresql://saas:saas@localhost:5434/saas"),
            "postgresql://saas:saas@127.0.0.1:5434/saas",
        )

    def test_ipv6_loopback_is_pinned_to_ipv4(self):
        self.assertEqual(
            normalize_database_url("postgresql://saas:saas@[::1]:5432/saas"),
            "postgresql://saas:saas@127.0.0.1:5432/saas",
        )

    def test_remote_host_is_untouched(self):
        url = "postgresql://saas:saas@db.internal:5432/saas"
        self.assertEqual(normalize_database_url(url), url)

    def test_password_containing_localhost_is_untouched(self):
        url = "postgresql://saas:localhost@db.internal:5432/saas"
        self.assertEqual(normalize_database_url(url), url)


if __name__ == "__main__":
    unittest.main()
