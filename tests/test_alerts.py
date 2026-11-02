"""Alert engine, prediction proxies and behaviour windows (A-H workstreams B/C/D/F).

Pure unit tests: no network, no real phone numbers and no API keys. textbee is
exercised through a mocked urlopen; every other send falls back to the log.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["AQUA_BACKEND_DATA"] = tempfile.mkdtemp(prefix="aqua_alerts_test_")
os.environ["AQUA_SCHEDULER"] = "0"
os.environ.pop("AQUA_ALERT_PHONES", None)
os.environ.pop("TEXTBEE_API_KEY", None)
os.environ.pop("TEXTBEE_DEVICE_ID", None)
os.environ.pop("AQUA_ALERT_TEST", None)

from backend import alerts, behavior_stats, predict, sensors  # noqa: E402


def _reset():
    alerts._last_sent.clear()
    alerts._loaded = True
    alerts._prev_active = set()
    behavior_stats._windows.clear()


class FakeResp:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, n=2048):
        return b"{}"


class AlertRules(unittest.TestCase):
    NOW = 1_800_000_000.0

    def setUp(self):
        _reset()
        self.tmp = tempfile.mkdtemp(prefix="aqua_alerts_case_")
        self.env = mock.patch.dict(os.environ, {"AQUA_BACKEND_DATA": self.tmp, "AQUA_ALERT_PROVIDERS": "textbee,log"}, clear=False)
        self.env.start()

    def tearDown(self):
        self.env.stop()
        for k in ("TEXTBEE_API_KEY", "TEXTBEE_DEVICE_ID", "AQUA_ALERT_PHONES", "AQUA_ALERT_TEST",
                  "SMSGATE_URL", "SMSGATE_USERNAME", "SMSGATE_PASSWORD", "SMSGATE_TOKEN", "SMSGATE_DEVICE_ID", "GAMMU_URL", "AQUA_TANK_NAME"):
            os.environ.pop(k, None)

    def _rows(self, now, temp, turb, n=4):
        return [{"t": now - i * 180, "temperature": temp, "turbidity": turb} for i in range(n - 1, -1, -1)]

    def test_stale_sensor_alerts_r1_and_repeats_after_4h(self):
        now = self.NOW
        old = {"t": now - 3600, "temperature": 40.0, "turbidity": 2000.0}
        with mock.patch.object(sensors, "latest", return_value=old), \
             mock.patch.object(sensors, "recent", return_value=[old]):
            rules = alerts.current_rules(now=now)
            self.assertEqual([r["rule"] for r in rules], ["R1"])
            self.assertEqual(rules[0]["level"], "CRITICAL")
            self.assertIn("stopped 60 min ago", rules[0]["message"])
            first = alerts.evaluate(now=now)
            self.assertEqual(len(first), 1)
            self.assertFalse(first[0]["delivered"])
            self.assertTrue(first[0]["logged"])
            self.assertEqual(alerts.evaluate(now=now + 60), [])
            self.assertEqual(len(alerts.evaluate(now=now + 4 * 3600 + 1)), 1)
            self.assertEqual(rules[0]["message"], rules[0]["message"][:160])

    def test_temp_outside_range_must_be_sustained_10_min(self):
        now = self.NOW
        hot = self._rows(now, 35.0, 300.0)
        with mock.patch.object(sensors, "latest", return_value=hot[-1]), \
             mock.patch.object(sensors, "recent", return_value=hot):
            got = {r["rule"] for r in alerts.current_rules(now=now)}
        self.assertIn("R2", got)
        self.assertNotIn("R1", got)
        # only 3 minutes of data is not enough
        short = [{"t": now - 120, "temperature": 35.0, "turbidity": 300.0}, hot[-1]]
        with mock.patch.object(sensors, "latest", return_value=hot[-1]), \
             mock.patch.object(sensors, "recent", return_value=short):
            self.assertNotIn("R2", {r["rule"] for r in alerts.current_rules(now=now)})

    def test_temp_sudden_change_and_turbidity_rise(self):
        now = self.NOW
        recent = [{"t": now - 7200, "temperature": 22.0, "turbidity": 400.0},
                  {"t": now - 6600, "temperature": 22.0, "turbidity": 400.0},
                  {"t": now - 5400, "temperature": 22.0, "turbidity": 400.0},
                  {"t": now - 3900, "temperature": 22.0, "turbidity": 400.0},
                  {"t": now - 600, "temperature": 22.0, "turbidity": 400.0},
                  {"t": now, "temperature": 24.5, "turbidity": 1200.0}]
        with mock.patch.object(sensors, "latest", return_value=recent[-1]), \
             mock.patch.object(sensors, "recent", return_value=recent):
            rules = alerts.current_rules(now=now)
            got = {r["rule"] for r in rules}
        self.assertIn("R3", got)
        self.assertIn("R4", got)
        r3 = next(r for r in rules if r["rule"] == "R3")
        self.assertAlmostEqual(r3["value"], 2.5)
        r4 = next(r for r in rules if r["rule"] == "R4")
        self.assertAlmostEqual(r4["rise_pct"], 200.0)
        for r in rules:
            self.assertLessEqual(len(r["message"]), 160)
            self.assertTrue(r["message"].isascii(), r["message"])

    def test_low_temp_sustained_alerts_r2(self):
        now = self.NOW
        cold = self._rows(now, 15.0, 300.0)
        with mock.patch.object(sensors, "latest", return_value=cold[-1]), \
             mock.patch.object(sensors, "recent", return_value=cold):
            got = {r["rule"] for r in alerts.current_rules(now=now)}
        self.assertIn("R2", got)
        self.assertNotIn("R1", got)

    def test_resolved_note_when_feed_returns(self):
        now = self.NOW
        fresh = {"t": now, "temperature": 28.0, "turbidity": 400.0}
        alerts._prev_active = {"R1"}
        with mock.patch.object(sensors, "latest", return_value=fresh), \
             mock.patch.object(sensors, "recent", return_value=[]):
            sent = alerts.evaluate(now=now)
        self.assertEqual([r["rule"] for r in sent], ["R1_RESOLVED"])
        raw = alerts._file().read_text(encoding="utf-8")
        self.assertIn("RESOLVED R1", raw)
        self.assertIn("is normal again", raw)

    def test_phone_masking_and_test_message_without_config(self):
        os.environ["AQUA_ALERT_PHONES"] = "+91 98765 43210"
        self.assertEqual(alerts.phone_list(), ["+919876543210"])
        self.assertEqual(alerts.mask("+919876543210"), "***210")
        res = alerts.test_alert()
        self.assertFalse(res["ok"])
        self.assertIn("provider", res["reason"])
        self.assertEqual(res["phones_masked"], ["***210"])

    def test_textbee_send_logs_masked_phone_and_no_key(self):
        os.environ.update({"TEXTBEE_API_KEY": "test-key-not-real", "TEXTBEE_DEVICE_ID": "dev",
                           "AQUA_ALERT_PHONES": "+919876543210"})
        with mock.patch.object(alerts.urllib.request, "urlopen", return_value=FakeResp()) as up:
            res = alerts.send_alert("TEST", "hello", "INFO", force=True)
        self.assertTrue(res["delivered"])
        self.assertEqual(up.call_count, 1)
        raw = alerts._file().read_text(encoding="utf-8")
        self.assertNotIn("test-key-not-real", raw)
        self.assertNotIn("9876543210", raw)
        self.assertIn("***210", raw)
        attempt = [json.loads(x) for x in raw.splitlines() if '"attempt"' in x][0]
        for key in ("http_code", "latency_ms", "provider", "status"):
            self.assertIn(key, attempt)

    def test_smsgate_dormant_and_active(self):
        os.environ["AQUA_ALERT_PHONES"] = "+919876543210"
        os.environ["AQUA_ALERT_PROVIDERS"] = "smsgate,log"
        res = alerts.send_alert("TEST", "hello", "INFO", force=True)
        self.assertFalse(res["delivered"])
        self.assertIn("skipped_no_config", res["statuses"])
        os.environ.update({"SMSGATE_USERNAME": "u", "SMSGATE_PASSWORD": "p-not-secret",
                           "SMSGATE_DEVICE_ID": "dev1"})
        with mock.patch.object(alerts.urllib.request, "urlopen", return_value=FakeResp()) as up:
            res = alerts.send_alert("TEST", "hello", "INFO", force=True)
        self.assertTrue(res["delivered"])
        req = up.call_args[0][0]
        self.assertTrue(req.full_url.endswith("/3rdparty/v1/messages"))
        self.assertEqual(req.get_header("Authorization"), "Basic dTpwLW5vdC1zZWNyZXQ=")
        body = json.loads(req.data.decode("utf-8"))
        self.assertEqual(body["textMessage"]["text"], "hello")
        self.assertEqual(body["phoneNumbers"], ["+919876543210"])
        self.assertEqual(body["deviceId"], "dev1")
        self.assertNotIn("p-not-secret", alerts._file().read_text(encoding="utf-8"))

    def test_dry_run_never_sends(self):
        os.environ.update({"TEXTBEE_API_KEY": "k", "TEXTBEE_DEVICE_ID": "d",
                           "AQUA_ALERT_PHONES": "+919876543210", "AQUA_ALERT_TEST": "1"})
        with mock.patch.object(alerts.urllib.request, "urlopen") as up:
            res = alerts.send_alert("TEST", "hello", "INFO", force=True)
        self.assertFalse(res["delivered"])
        up.assert_not_called()

    def test_false_alarm_marking_and_digest(self):
        os.environ["AQUA_ALERT_PHONES"] = "+919876543210"
        sent = alerts.send_alert("R1", "test", "HIGH", force=True)
        self.assertIsNotNone(alerts.mark_false_alarm(sent["id"]))
        self.assertIsNone(alerts.mark_false_alarm("missing"))
        self.assertIn(sent["id"], alerts.false_alarm_ids())
        d = alerts.digest_payload()
        self.assertEqual(d["false_alarms"], 1)
        self.assertEqual(d["alerts"], 0)

    def test_khatra_weights_cap(self):
        rules = [{"rule": "R1"}, {"rule": "R2"}, {"rule": "R3"}, {"rule": "R5", "level": "HIGH"}, {"rule": "R6"}]
        k = alerts.khatra(rules)
        self.assertEqual(k["score"], 100)
        self.assertEqual(k["level"], "HIGH")
        self.assertEqual(alerts.khatra([])["score"], 0)

    def test_weekly_digest_is_logged_without_sms_config(self):
        res = alerts.weekly_digest()
        self.assertEqual(res["rule"], "DIGEST")
        self.assertTrue(res["logged"])
        self.assertFalse(res["delivered"])
        self.assertIn("weekly", alerts._file().read_text(encoding="utf-8"))

    def test_log_rotation(self):
        p = Path(self.tmp) / "rotate.jsonl"
        p.write_text("x" * 2048, encoding="utf-8")
        alerts._rotate(p, max_bytes=1024)
        self.assertTrue(p.with_suffix(".jsonl.1").is_file())
        self.assertFalse(p.exists())

    def test_no_telegram_references(self):
        src = ""
        for p in (ROOT / "backend").glob("*.py"):
            src += p.read_text(encoding="utf-8").lower()
        self.assertNotIn("telegram", src)


class Prediction(unittest.TestCase):
    def test_csat_weiss_values(self):
        self.assertAlmostEqual(predict.csat(0), 14.652, places=3)
        self.assertLess(predict.csat(30), predict.csat(20))

    def test_forecast_insufficient_without_history(self):
        with mock.patch.object(sensors, "series", return_value=[]):
            f = predict.forecast_field("temperature")
        self.assertEqual(f["status"], "insufficient_data")
        self.assertTrue(f["provisional"])

    def test_forecast_and_backtest_shape(self):
        now = 1_800_000_000.0
        pts = [(now - (72 - i) * 3600, 28.0 + (i % 6) * 0.2) for i in range(72)]
        with mock.patch.object(sensors, "series", return_value=pts):
            f = predict.forecast_field("temperature", now=now)
            r = predict.dawn_risk(now=now)
        self.assertEqual(f["status"], "ok")
        self.assertEqual(len(f["points"]), 6)
        self.assertTrue(all(p["low"] <= p["value"] <= p["high"] for p in f["points"]))
        self.assertIn(r["level"], ("LOW", "MEDIUM", "HIGH"))

    def test_dawn_risk_insufficient_without_data(self):
        with mock.patch.object(sensors, "series", return_value=[]):
            r = predict.dawn_risk()
        self.assertEqual(r["level"], "INSUFFICIENT_DATA")
        self.assertTrue(r["provisional"])


class Behavior(unittest.TestCase):
    def setUp(self):
        behavior_stats._windows.clear()
        self.tmp = tempfile.mkdtemp(prefix="aqua_behavior_")
        self.env = mock.patch.dict(os.environ, {"AQUA_BACKEND_DATA": self.tmp}, clear=False)
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def test_windows_flush_and_summary(self):
        t0 = 1_800_000_000.0
        tracks = [{"id": 1, "confirmed": True, "box": [0.1, 0.05, 0.2, 0.15], "mean_speed_px_sec": 40.0},
                  {"id": 2, "confirmed": True, "box": [0.6, 0.6, 0.7, 0.7], "mean_speed_px_sec": 20.0}]
        for i in range(3):
            behavior_stats.observe(tracks, 640, 360, now=t0 + i)
        behavior_stats.observe(tracks, 640, 360, now=t0 + 301)   # next window flushes the first
        rows = behavior_stats._load_windows()
        self.assertEqual(len(rows), 1)
        self.assertGreater(rows[0]["activity_norm"], 0)
        self.assertGreater(rows[0]["spread_norm"], 0)
        self.assertEqual(rows[0]["surface_occ"], 0.5)
        s = behavior_stats.summary(now=t0 + 301)
        self.assertIn("provisional", s)
        self.assertIsNone(behavior_stats.current_anomaly(now=t0 + 301))


class SensorFeed(unittest.TestCase):
    def test_parse_feed_maps_fields(self):
        payload = {"feeds": [
            {"entry_id": 2, "created_at": "2026-10-22T10:00:00Z", "field1": "28.5", "field2": "512"},
            {"entry_id": 3, "created_at": "2026-10-22T10:01:00Z", "field1": "bad", "field2": "530"},
            {"entry_id": 4, "created_at": "2026-10-22T10:02:00Z", "field1": None, "field2": None},
        ]}
        got = sensors.parse_feed(payload)
        self.assertEqual(len(got), 2)
        self.assertEqual(got[0]["temperature"], 28.5)
        self.assertEqual(got[1]["temperature"], None)
        self.assertEqual(got[1]["turbidity"], 530.0)


if __name__ == "__main__":
    unittest.main()

