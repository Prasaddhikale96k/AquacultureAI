"""Tests for Starlette AuthMiddleware allow-listing, open/full modes, and Bearer fallback."""
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from starlette.testclient import TestClient
import backend.main as api
from backend.app.auth import tokens

client = TestClient(api.app)


class TestAuthMiddleware(unittest.TestCase):
    def setUp(self):
        tokens.clear_sessions()

    def tearDown(self):
        os.environ["AQUA_AUTH_MODE"] = "open"


    def test_allow_list_endpoints_public_in_full_mode(self):
        """Public endpoints like /health and /api/auth/status do not require authentication."""
        os.environ["AQUA_AUTH_MODE"] = "full"
        res_health = client.get("/health")
        self.assertEqual(res_health.status_code, 200)

        res_auth_status = client.get("/api/auth/status")
        self.assertEqual(res_auth_status.status_code, 200)

    def test_auth_status_reports_mode_for_ui_rollback(self):
        """Additive auth_mode field lets the SPA drop the login gate in open mode."""
        os.environ["AQUA_AUTH_MODE"] = "open"
        self.assertEqual(client.get("/api/auth/status").json().get("auth_mode"), "open")
        os.environ["AQUA_AUTH_MODE"] = "full"
        self.assertEqual(client.get("/api/auth/status").json().get("auth_mode"), "full")

    def test_full_mode_blocks_unauthenticated_api_endpoints_with_401(self):
        """In full mode, protected /api/ endpoints require valid authentication."""
        os.environ["AQUA_AUTH_MODE"] = "full"
        res = client.get("/api/sensors")
        self.assertEqual(res.status_code, 401)
        self.assertIn("Authentication required", res.json()["reason"])

    def test_open_mode_bypasses_auth_for_rollback_safety(self):
        """In open mode (rollback switch), /api/ endpoints do not require auth."""
        os.environ["AQUA_AUTH_MODE"] = "open"
        res = client.get("/api/sensors")
        # In open mode, sensors status returns 200
        self.assertEqual(res.status_code, 200)

    def test_bearer_token_fallback_accepted_in_full_mode(self):
        """Bearer token is accepted interchangeably with session cookie."""
        os.environ["AQUA_AUTH_MODE"] = "full"
        raw_token, _ = tokens.create_session("+919876543210")

        # Access with Authorization header
        headers = {"Authorization": f"Bearer {raw_token}"}
        res = client.get("/api/sensors", headers=headers)
        self.assertEqual(res.status_code, 200)

    def test_cookie_and_csrf_validation_on_mutating_requests(self):
        """Cookie auth requires X-CSRF-Token on POST requests."""
        os.environ["AQUA_AUTH_MODE"] = "full"
        raw_token, csrf_token = tokens.create_session("+919876543210")

        # 1. Mutating request with cookie but missing CSRF header -> 403
        client.cookies.set("aqua_session", raw_token)
        res_no_csrf = client.post("/api/risk", json={})
        self.assertEqual(res_no_csrf.status_code, 403)

        # 2. Mutating request with cookie and valid X-CSRF-Token -> succeeds (not 401/403)
        res_with_csrf = client.post("/api/risk", json={}, headers={"X-CSRF-Token": csrf_token})
        self.assertNotIn(res_with_csrf.status_code, (401, 403))
        client.cookies.clear()


if __name__ == "__main__":
    unittest.main()
