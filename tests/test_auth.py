"""OTP phone verification (farmer login) unit tests. No network, no real SMS."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["AQUA_BACKEND_DATA"] = tempfile.mkdtemp(prefix="aqua_auth_test_")
os.environ["AQUA_SCHEDULER"] = "0"
os.environ.pop("AQUA_ALERT_PHONES", None)
os.environ.pop("TEXTBEE_API_KEY", None)
os.environ.pop("SMSGATE_USERNAME", None)
os.environ.pop("SMSGATE_PASSWORD", None)
os.environ.pop("AQUA_OTP_WAIT_S", None)

from backend import alerts, auth  # noqa: E402


def _reset():
    auth._pending.clear()
    auth._req_times.clear()
    alerts._last_sent.clear()
    alerts._loaded = True


class Auth(unittest.TestCase):
    def setUp(self):
        _reset()
        self.tmp = tempfile.mkdtemp(prefix="aqua_auth_case_")
        self.env = mock.patch.dict(os.environ, {"AQUA_BACKEND_DATA": self.tmp}, clear=False)
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def test_normalize_and_mask(self):
        self.assertEqual(auth.normalize_phone("98765 43210"), "+919876543210")
        self.assertEqual(auth.normalize_phone("+91-98765-43210"), "+919876543210")
        self.assertIsNone(auth.normalize_phone("123"))
        self.assertEqual(auth.mask("+919876543210"), "***210")

    def test_request_otp_without_provider_is_honest(self):
        with mock.patch.object(auth.alerts, "configured_providers", return_value=[]), \
             mock.patch.object(auth.alerts, "send_alert", return_value={
                 "delivered": False, "statuses": ["skipped_no_config", "logged"],
                 "providers": ["smsgate", "log"], "id": "x"}):
            res = auth.request_otp("+919876543210")
        self.assertFalse(res["ok"])
        self.assertIn("no SMS provider", res["reason"])
        self.assertNotIn("9876543210", str(res))
        self.assertEqual(auth._pending, {})

    def test_otp_verify_success_and_alert_phone_registration(self):
        sent = {"delivered": True, "statuses": ["sent", "logged"], "providers": ["smsgate", "log"], "id": "abc"}
        with mock.patch.object(auth.secrets, "randbelow", return_value=23456), \
             mock.patch.object(auth.alerts, "send_alert", return_value=sent) as send:
            res = auth.request_otp("9876543210")
        self.assertTrue(res["ok"])
        self.assertEqual(res["phone_masked"], "***210")
        self.assertEqual(send.call_args.kwargs["log_message"], "OTP sent (code redacted)")
        self.assertNotIn("123456", send.call_args.args[0])
        self.assertNotIn("123456", Path(self.tmp, "otp_log.jsonl").read_text(encoding="utf-8"))
        bad = auth.verify_otp("9876543210", "000000")
        self.assertFalse(bad["ok"])
        good = auth.verify_otp("9876543210", "123456")
        self.assertTrue(good["ok"])
        self.assertTrue(good["verified"])
        self.assertIn("token", good)
        self.assertIn("+919876543210", auth.verified_phones())
        self.assertIn("+919876543210", alerts.phone_list())
        self.assertIn("+919876543210", Path(self.tmp, "verified_phones.jsonl").read_text(encoding="utf-8"))
        self.assertIsNone(auth.verify_otp("9876543210", "123456").get("token"))

    def test_otp_resend_cooldown_and_expiry(self):
        sent = {"delivered": True, "statuses": ["sent"], "providers": ["smsgate"], "id": "a"}
        with mock.patch.object(auth.secrets, "randbelow", return_value=23456), \
             mock.patch.object(auth.alerts, "send_alert", return_value=sent):
            self.assertTrue(auth.request_otp("+919876543210", now=1000)["ok"])
            again = auth.request_otp("+919876543210", now=1010)
            self.assertFalse(again["ok"])
            self.assertIn("wait", again["reason"])
        expired = auth.verify_otp("+919876543210", "123456", now=1000 + auth.ttl_s() + 1)
        self.assertFalse(expired["ok"])
        self.assertIn("expired", expired["reason"])

    def test_status_has_no_full_phone(self):
        s = auth.status()
        self.assertIn("verified_masked", s)
        self.assertNotIn("verified_phones", s)


if __name__ == "__main__":
    unittest.main()
