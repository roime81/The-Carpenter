import unittest
from types import SimpleNamespace

from app import web_auth


class WebAuthenticationTests(unittest.TestCase):
    def setUp(self):
        self.previous_settings = web_auth.settings
        web_auth.settings = SimpleNamespace(
            admin_token="admin-token-with-enough-entropy-123456",
            operator_token="operator-token-with-enough-entropy-123456",
            viewer_token="viewer-token-with-enough-entropy-123456",
            session_secret="dedicated-session-secret-with-enough-entropy-123456",
        )

    def tearDown(self):
        web_auth.settings = self.previous_settings

    def test_credentials_resolve_to_expected_least_privilege_role(self):
        self.assertEqual(web_auth.authenticate_token(
            "admin-token-with-enough-entropy-123456"
        )["role"], "admin")
        self.assertEqual(web_auth.authenticate_token(
            "operator-token-with-enough-entropy-123456"
        )["role"], "operator")
        self.assertEqual(web_auth.authenticate_token(
            "viewer-token-with-enough-entropy-123456"
        )["role"], "viewer")
        self.assertIsNone(web_auth.authenticate_token("not-a-valid-token"))

    def test_signed_session_round_trips_and_expires(self):
        issued = web_auth.issue_session(
            "admin-token-with-enough-entropy-123456", now=1000
        )
        self.assertIsNotNone(issued)
        identity, cookie = issued
        restored = web_auth.read_session(cookie, now=1001)
        self.assertEqual(restored["subject"], identity["subject"])
        self.assertEqual(restored["role"], "admin")
        self.assertEqual(restored["conversation_id"], identity["conversation_id"])
        second_identity, _ = web_auth.issue_session(
            "admin-token-with-enough-entropy-123456", now=1001
        )
        self.assertNotEqual(second_identity["conversation_id"], identity["conversation_id"])
        self.assertIsNone(web_auth.read_session(
            cookie, now=1000 + web_auth.SESSION_TTL_SECONDS
        ))

    def test_cookie_tampering_is_rejected(self):
        _, cookie = web_auth.issue_session(
            "operator-token-with-enough-entropy-123456", now=1000
        )
        encoded, signature = cookie.rsplit(".", 1)
        altered = encoded[:-1] + ("A" if encoded[-1] != "A" else "B")
        self.assertIsNone(web_auth.read_session(altered + "." + signature, now=1001))
        self.assertIsNone(web_auth.read_session(encoded + ".invalid", now=1001))

    def test_csrf_token_must_match_signed_session(self):
        identity, _ = web_auth.issue_session(
            "admin-token-with-enough-entropy-123456", now=1000
        )
        self.assertTrue(web_auth.verify_csrf(identity, identity["csrf"]))
        self.assertFalse(web_auth.verify_csrf(identity, "attacker-controlled-value"))


if __name__ == "__main__":
    unittest.main()
