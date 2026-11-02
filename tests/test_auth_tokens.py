"""Tests for session tokens, CSRF pairing, and 7-day expiration."""
import os
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.auth import tokens


class TestAuthTokens(unittest.TestCase):
    def setUp(self):
        tokens.clear_sessions()

    def test_session_creation_and_validation(self):
        now = time.time()
        token, csrf = tokens.create_session("+919876543210", now=now)
        self.assertTrue(len(token) > 20)
        self.assertTrue(len(csrf) > 20)

        # Validate valid session
        sess = tokens.validate_session(token, now=now + 100)
        self.assertIsNotNone(sess)
        self.assertEqual(sess["phone"], "+919876543210")
        self.assertEqual(sess["csrf_token"], csrf)

    def test_session_expiry_at_seven_days(self):
        now = time.time()
        token, _ = tokens.create_session("+919876543210", now=now)

        # Valid at 6 days, 23 hours
        valid_time = now + (7 * 86400 - 3600)
        self.assertIsNotNone(tokens.validate_session(token, now=valid_time))

        # Expired at 7 days + 1 second
        expired_time = now + (7 * 86400 + 1)
        self.assertIsNone(tokens.validate_session(token, now=expired_time))

    def test_invalid_or_missing_token_rejected(self):
        self.assertIsNone(tokens.validate_session(""))
        self.assertIsNone(tokens.validate_session("non_existent_token_string"))

    def test_revoke_session_on_logout(self):
        token, _ = tokens.create_session("+919876543210")
        self.assertIsNotNone(tokens.validate_session(token))

        revoked = tokens.revoke_session(token)
        self.assertTrue(revoked)
        self.assertIsNone(tokens.validate_session(token))


if __name__ == "__main__":
    unittest.main()
