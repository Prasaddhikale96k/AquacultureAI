"""DO prediction API, manual pH-only input, R7 alerts and calibration tests.

All sensor/DO values are synthetic fixtures, not farm measurements.
"""
import json
import os
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["AQUA_BACKEND_DATA"] = tempfile.mkdtemp(prefix="aqua_do_base_")
os.environ["AQUA_SCHEDULER"] = "0"

from starlette.testclient import TestClient  # noqa: E402
import backend.main as api  # noqa: E402
from backend import alerts, behavior_stats, sensors, water  # noqa: E402
from backend.app.services import do_model, do_service  # noqa: E402

NOW_HOUR = datetime(2026, 10, 24, 12, 0).timestamp()


class FakeResp:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, n=2048):
        return b"{}"


def iso(hours_ago=0.5):
    return datetime.fromtimestamp(time.time() - hours_ago * 3600, timezone.utc).isoformat()


def series_for(now, temp=28.0, ntu=22.5, temp_age=60, ntu_age=60):
    def _series(field, minutes):
        if field == "temperature":
            return [(now - temp_age, temp)]
        if field == "turbidity":
            return [(now - ntu_age, ntu)]
        return []
    return _series


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="aqua_do_api_")
        self.env = mock.patch.dict(os.environ, {
            "AQUA_BACKEND_DATA": self.tmp,
            "AQUA_SCHEDULER": "0",
            "AQUA_DO_PREDICT": "1",
            "AQUA_DO_ALERT": "1",
            "AQUA_DO_CAL": "0",
            "AQUA_ALERT_TEST": "",
            "AQUA_ALERT_PROVIDERS": "textbee,log",
        }, clear=False)
        self.env.start()
        sensors._cache = None
        sensors._loaded = False
        water.init(self.tmp, api._video_result)
        alerts._last_sent.clear()
        alerts._loaded = True
        alerts._prev_active = set()
        alerts._do_last_level = None
        alerts._do_streak = 0
        behavior_stats._windows.clear()
        self.c = TestClient(api.app)

    def tearDown(self):
        self.env.stop()

    def get_prediction(self, **kw):
        now = time.time()
        with mock.patch.object(sensors, "series", side_effect=series_for(now, **kw)):
            return self.c.get("/api/do-prediction").json()

    def write_water(self, ph, hours_ago=1.0, tank="T1"):
        rec = {
            "id": "a" * 32,
            "createdAt": iso(hours_ago),
            "tankId": tank,
            "species": "tilapia",
            "lifeStage": "juvenile",
            "system": "ras",
            "timestamp": iso(hours_ago),
            "source": "manual",
            "supersedes": None,
            "measurements": {"pH": {"value": ph, "unit": "pH", "canonicalValue": ph}},
        }
        (Path(self.tmp) / "water_readings.jsonl").write_text(json.dumps(rec) + "\n", encoding="utf-8")


class PredictionApi(Base):
    def test_contract_keys_and_ok_status(self):
        body = self.get_prediction()
        self.assertEqual(set(body), {
            "status", "do_mgl", "band_low", "band_high", "percent_saturation",
            "do_sat_mgl", "s_factor", "risk_level", "confidence", "label_provisional",
            "inputs", "turbidity_unit", "behaviour_evidence", "feed_evidence",
            "reason", "generated_at", "model_version",
        })
        self.assertEqual(body["turbidity_unit"], "raw_adc")
        self.assertIsNone(body["behaviour_evidence"])
        self.assertEqual(body["feed_evidence"]["s_feed"], 0.0)
        self.assertEqual(set(body["inputs"]), {
            "temp_c", "temp_age_min", "turbidity_ntu", "turbidity_age_min",
            "ph", "ph_age_hours",
        })
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["model_version"], "do-physics-v1")
        self.assertTrue(body["label_provisional"])
        self.assertIn(body["risk_level"], ("safe", "watch", "risk", "critical"))
        self.assertLessEqual(body["band_low"], body["do_mgl"])
        self.assertGreaterEqual(body["band_high"], body["do_mgl"])

    def test_stale_temp_is_insufficient_and_emits_no_r7(self):
        body = self.get_prediction(temp_age=3600)
        self.assertEqual(body["status"], "insufficient_data")
        self.assertIsNone(body["do_mgl"])
        self.assertIn("temp", body["reason"])
        now = time.time()
        with mock.patch.object(sensors, "series", side_effect=series_for(now, temp_age=3600)), \
             mock.patch.object(sensors, "latest", return_value=None), \
             mock.patch.object(sensors, "recent", return_value=[]):
            rules = alerts.current_rules(now=now)
        self.assertNotIn("R7", {r["rule"] for r in rules})

    def test_farm_tz_hour_and_prediction_wiring(self):
        stamp = datetime(2026, 10, 24, 20, 30, tzinfo=timezone.utc).timestamp()
        self.assertEqual(do_service.farm_clock.farm_hour(stamp), 2.0)
        with mock.patch.dict(os.environ, {"AQUA_FARM_TZ": "UTC"}, clear=False):
            self.assertEqual(do_service.farm_clock.farm_hour(stamp), 20.5)
        base = do_model.estimate_do(28.0, 22.5, 7.9, 2.0, 0.0)
        with mock.patch.object(sensors, "series", side_effect=series_for(stamp)), \
             mock.patch.object(do_model, "estimate_do", return_value=base) as est:
            do_service.prediction(now=stamp)
        self.assertAlmostEqual(est.call_args.kwargs["hour"], 2.0, places=3)

    def test_missing_and_old_ph_still_estimate(self):
        body = self.get_prediction()
        self.assertEqual(body["status"], "ok")
        self.assertIsNone(body["inputs"]["ph"])
        self.assertEqual(body["confidence"], "low")
        self.write_water(7.2, hours_ago=30)
        body = self.get_prediction()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["inputs"]["ph"], 7.2)
        self.assertGreaterEqual(body["inputs"]["ph_age_hours"], 24)
        self.assertEqual(body["confidence"], "low")

    def test_alert_requires_two_consecutive_critical_evaluations_and_sends_once(self):
        os.environ.update({"AQUA_ALERT_PHONES": "+919876543210",
                           "TEXTBEE_API_KEY": "k-not-real", "TEXTBEE_DEVICE_ID": "d"})
        pred = {"status": "ok", "risk_level": "critical", "do_mgl": 1.5}
        fresh = {"t": NOW_HOUR, "temperature": 28.0, "turbidity": 300.0}
        with mock.patch.object(do_service, "prediction", return_value=pred), \
             mock.patch.object(sensors, "latest", return_value=fresh), \
             mock.patch.object(sensors, "recent", return_value=[fresh]), \
             mock.patch.object(alerts.urllib.request, "urlopen", return_value=FakeResp()) as up:
            first = alerts.evaluate(now=NOW_HOUR)
            second = alerts.evaluate(now=NOW_HOUR + 60)
        self.assertNotIn("R7", [r["rule"] for r in first])
        self.assertIn("R7", [r["rule"] for r in second])
        self.assertEqual(up.call_count, 1)
        row = next(r for r in second if r["rule"] == "R7")
        self.assertTrue(row["delivered"])
        msg = row["message"] if "message" in row else next(
            r for r in alerts.recent(10) if r["rule"] == "R7")["message"]
        self.assertLessEqual(len(msg), 160)
        self.assertTrue(msg.isascii())

    def test_risk_level_logs_without_sms(self):
        os.environ.update({"AQUA_ALERT_PHONES": "+919876543210",
                           "TEXTBEE_API_KEY": "k-not-real", "TEXTBEE_DEVICE_ID": "d"})
        pred = {"status": "ok", "risk_level": "risk", "do_mgl": 3.0}
        fresh = {"t": NOW_HOUR, "temperature": 28.0, "turbidity": 300.0}
        with mock.patch.object(do_service, "prediction", return_value=pred), \
             mock.patch.object(sensors, "latest", return_value=fresh), \
             mock.patch.object(sensors, "recent", return_value=[fresh]), \
             mock.patch.object(alerts.urllib.request, "urlopen", return_value=FakeResp()) as up:
            alerts.evaluate(now=NOW_HOUR)
            second = alerts.evaluate(now=NOW_HOUR + 60)
        self.assertIn("R7", [r["rule"] for r in second])
        self.assertEqual(up.call_count, 0)
        row = [r for r in second if r["rule"] == "R7"][0]
        self.assertFalse(row["delivered"])
        self.assertEqual(row["statuses"], ["logged"])

    def test_alert_flag_and_predict_flag(self):
        os.environ.update({"AQUA_ALERT_PHONES": "+919876543210",
                           "TEXTBEE_API_KEY": "k-not-real", "TEXTBEE_DEVICE_ID": "d"})
        pred = {"status": "ok", "risk_level": "critical", "do_mgl": 1.5}
        fresh = {"t": NOW_HOUR, "temperature": 28.0, "turbidity": 300.0}
        os.environ["AQUA_DO_ALERT"] = "0"
        with mock.patch.object(do_service, "prediction", return_value=pred), \
             mock.patch.object(sensors, "latest", return_value=fresh), \
             mock.patch.object(sensors, "recent", return_value=[fresh]), \
             mock.patch.object(alerts.urllib.request, "urlopen", return_value=FakeResp()) as up:
            alerts.evaluate(now=NOW_HOUR)
            second = alerts.evaluate(now=NOW_HOUR + 60)
        self.assertNotIn("R7", [r["rule"] for r in second])
        self.assertEqual(up.call_count, 0)
        os.environ["AQUA_DO_ALERT"] = "1"
        os.environ["AQUA_DO_PREDICT"] = "0"
        body = self.get_prediction()
        self.assertEqual(body["status"], "disabled")
        self.assertIsNone(body["do_mgl"])

    def test_manual_ph_only_and_legacy_payload_unchanged(self):
        now = iso(1)
        base = {"tankId": "T1", "species": "tilapia", "system": "ras",
                "lifeStage": "juvenile", "timestamp": now, "source": "manual"}
        with mock.patch.object(sensors, "series", side_effect=series_for(time.time())):
            r = self.c.post("/api/water-readings", json={**base, "ph": 7.6})
        self.assertEqual(r.status_code, 201)
        body = r.json()
        self.assertTrue(body["ph_only"])
        self.assertEqual(set(body["reading"]["measurements"]), {"pH"})
        self.assertAlmostEqual(body["reading"]["measurements"]["pH"]["canonicalValue"], 7.6)
        temp_item = next(m for m in body["assessment"]["measurements"] if m["parameter"] == "temperature")
        self.assertEqual(temp_item["source"], "sensor")
        self.assertEqual(temp_item["value"], 28.0)
        legacy = {**base, "measurements": {
            "temperature": {"value": 28, "unit": "C"},
            "pH": {"value": 7.6},
            "dissolvedOxygen": {"value": 6.5, "unit": "mg/L"},
        }}
        r2 = self.c.post("/api/water-readings", json=legacy)
        self.assertEqual(r2.status_code, 201)
        body2 = r2.json()
        self.assertNotIn("ph_only", body2)
        self.assertEqual(set(body2), {"reading", "assessment"})
        self.assertEqual(set(body2["reading"]["measurements"]), {"temperature", "pH", "dissolvedOxygen"})

    def test_do_reading_validation_and_history(self):
        now = time.time()
        with mock.patch.object(sensors, "series", side_effect=series_for(now)):
            bad = [(-1, 422), (25, 422), ("abc", 422)]
            for value, code in bad:
                r = self.c.post("/api/water/do-reading", json={"value_mgl": value,
                                                              "measured_at": iso(1), "method": "kit"})
                self.assertEqual(r.status_code, code)
            ok = self.c.post("/api/water/do-reading", json={"value_mgl": 6.4,
                                                            "measured_at": iso(1), "method": "kit"})
            self.assertEqual(ok.status_code, 201)
            self.assertIsNotNone(ok.json()["reading"]["do_est"])
            for i in range(2):
                self.c.post("/api/water/do-reading", json={"value_mgl": 6.0 + i,
                                                           "measured_at": iso(0.2 + i), "method": "kit"})
            hist = self.c.get("/api/water/do-readings?limit=2").json()
        self.assertEqual(hist["count"], 2)
        self.assertGreaterEqual(hist["readings"][0]["measured_t"], hist["readings"][1]["measured_t"])

    def test_calibration_dormant_then_applied_then_ignored(self):
        self.write_water(7.8, hours_ago=1)
        for i in range(20):
            x = round(3.0 + i * 0.1, 2)
            do_service.append_reading({
                "id": f"r{i:02d}", "value_mgl": round(2 * x + 10, 2),
                "measured_at": iso(1), "measured_t": time.time() - 3600,
                "do_est": x, "model_version": do_model.MODEL_VERSION, "provisional": True,
            })
        body = self.get_prediction(temp=20.0, ntu=0.0)
        self.assertEqual(body["confidence"], "low")
        self.assertLess(body["do_mgl"], 20)
        self.assertIsNone(do_service.read_calibration())

        os.environ["AQUA_DO_CAL"] = "1"
        body = self.get_prediction(temp=20.0, ntu=0.0)
        cal = do_service.read_calibration()
        self.assertEqual(cal["n"], 20)
        self.assertAlmostEqual(cal["a"], 2.0, places=3)
        self.assertAlmostEqual(cal["b"], 10.0, places=3)
        self.assertEqual(body["confidence"], "medium")
        self.assertEqual(body["do_mgl"], 20.0)
        self.assertLessEqual(body["band_high"], 20)

        os.environ["AQUA_DO_CAL"] = "0"
        body = self.get_prediction(temp=20.0, ntu=0.0)
        self.assertEqual(body["confidence"], "low")
        self.assertLess(body["do_mgl"], 20)


if __name__ == "__main__":
    unittest.main()
