"""Unit and integration tests for OTP generation, hashing, lockout, rate limits, and verification."""
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Note: AQUA_AUTH_MODE is set to 'full' per test in setUp/tearDown per AMENDMENT A1
os.environ["AQUA_SCHEDULER"] = "0"

from starlette.testclient import TestClient
import backend.main as api
from backend.app.auth import otp, store, tokens

client = TestClient(api.app)


class TestAuthOtp(unittest.TestCase):
    def setUp(self):
        self._prev_mode = os.environ.get("AQUA_AUTH_MODE", "open")
        self._prev_data = os.environ.get("AQUA_BACKEND_DATA")
        os.environ["AQUA_AUTH_MODE"] = "full"
        os.environ["AQUA_BACKEND_DATA"] = tempfile.mkdtemp(prefix="aqua_auth_otp_")
        otp.clear_otps()
        tokens.clear_sessions()
        store.clear_store()

    def tearDown(self):
        store.clear_store()
        tokens.clear_sessions()
        if self._prev_data is None:
            os.environ.pop("AQUA_BACKEND_DATA", None)
        else:
            os.environ["AQUA_BACKEND_DATA"] = self._prev_data
        os.environ["AQUA_AUTH_MODE"] = self._prev_mode


    def test_happy_path_register_and_verify(self):
        """Happy path: register user -> receive OTP via alert mock -> verify OTP -> get session."""
        with mock.patch("backend.alerts.send_alert") as mock_send:
            mock_send.return_value = {"delivered": True, "providers": ["smsgate"], "statuses": {"smsgate": "sent"}}
            # 1. Register
            res = client.post("/api/auth/register", json={
                "name": "Ramesh Kumar",
                "phone": "+919876543210",
                "tankId": "Tank-01",
                "species": "Nile Tilapia (GIFT)",
                "system": "RAS"
            })
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertTrue(data.get("ok"))
            self.assertIn("phone_masked", data)

            # Retrieve sent OTP code from internal memory for verification
            norm_phone = otp.normalize_phone("+919876543210")
            otp_rec = otp._otps.get(norm_phone)
            self.assertIsNotNone(otp_rec)

            # Find valid code by comparing hash
            code = None
            for c in range(100000, 1000000):
                if otp.verify_otp(norm_phone, str(c))[0]:
                    code = str(c)
                    break
            # Now verify via endpoint with a fresh OTP
            ok, _, _ = otp.generate_and_send_otp(norm_phone)
            # Brute force in test to grab active code
            salt = otp._otps[norm_phone]["salt"]
            expected_h = otp._otps[norm_phone]["hash"]
            real_code = next(str(c) for c in range(100000, 1000000) if otp._hash_otp(str(c), salt) == expected_h)

            v_res = client.post("/api/auth/verify", json={
                "phone": "+919876543210",
                "otp": real_code
            })
            self.assertEqual(v_res.status_code, 200)
            v_data = v_res.json()
            self.assertTrue(v_data.get("ok"))
            self.assertEqual(v_data["user"]["name"], "Ramesh Kumar")
            self.assertIn("aqua_session", v_res.cookies)
            self.assertIn("aqua_csrf", v_res.cookies)

    def test_wrong_otp_x3_lockout(self):
        """Entering incorrect OTP 3 times locks out the code."""
        with mock.patch("backend.alerts.send_alert", return_value={"delivered": True, "providers": ["smsgate"], "statuses": {}}):
            client.post("/api/auth/register", json={"name": "Test", "phone": "+919123456789"})

        # Try 1: wrong
        r1 = client.post("/api/auth/verify", json={"phone": "+919123456789", "otp": "000000"})
        self.assertEqual(r1.status_code, 401)
        # Try 2: wrong
        r2 = client.post("/api/auth/verify", json={"phone": "+919123456789", "otp": "000001"})
        self.assertEqual(r2.status_code, 401)
        # Try 3: wrong -> lockout
        r3 = client.post("/api/auth/verify", json={"phone": "+919123456789", "otp": "000002"})
        self.assertEqual(r3.status_code, 401)
        self.assertIn("Maximum attempts exceeded", r3.json()["reason"])

        # Try 4: active record gone
        r4 = client.post("/api/auth/verify", json={"phone": "+919123456789", "otp": "000003"})
        self.assertEqual(r4.status_code, 401)
        self.assertIn("No active OTP", r4.json()["reason"])

    def test_expired_otp(self):
        """OTP older than 5 minutes is rejected."""
        t0 = time.time()
        norm_phone = otp.normalize_phone("+919999988888")
        otp._otps[norm_phone] = {
            "hash": "somehash",
            "salt": "somesalt",
            "exp": t0 - 10,  # expired 10s ago
            "attempts": 0,
            "created_at": t0 - 310,
        }
        res = client.post("/api/auth/verify", json={"phone": "+919999988888", "otp": "123456"})
        self.assertEqual(res.status_code, 401)
        self.assertIn("expired", res.json()["reason"].lower())

    def test_resend_cooldown_enforcement(self):
        """Requesting OTP again within 30s is rejected with 429."""
        with mock.patch("backend.alerts.send_alert", return_value={"delivered": True, "providers": ["smsgate"], "statuses": {}}):
            r1 = client.post("/api/auth/login", json={"phone": "+919876500000"})
            self.assertEqual(r1.status_code, 200)

            # Immediate second request
            r2 = client.post("/api/auth/resend", json={"phone": "+919876500000"})
            self.assertEqual(r2.status_code, 429)
            self.assertIn("wait", r2.json()["reason"].lower())

    def test_rate_limit_six_otps_in_hour_rejected(self):
        """Requesting more than 5 OTPs within 1 hour is rejected."""
        norm_phone = otp.normalize_phone("+919876511111")
        now = time.time()
        # Seed 5 requests
        otp._req_history[norm_phone] = [now - 3000, now - 2500, now - 2000, now - 1500, now - 1000]

        with mock.patch("backend.alerts.send_alert", return_value={"delivered": True, "providers": ["smsgate"], "statuses": {}}):
            ok, msg, _ = otp.generate_and_send_otp(norm_phone, now=now)
            self.assertFalse(ok)
            self.assertIn("Maximum 5 per hour", msg)


if __name__ == "__main__":
    unittest.main()
