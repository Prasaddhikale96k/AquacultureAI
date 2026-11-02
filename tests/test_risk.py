"""Unified risk engine tests: 5-level taxonomy, documented combination logic."""
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
_TMP = tempfile.mkdtemp(prefix="aqua_risk_test_")
os.environ["AQUA_BACKEND_DATA"] = _TMP

import unittest
from starlette.testclient import TestClient  # noqa: E402
import backend.main as api  # noqa: E402
from backend import risk as risk_engine  # noqa: E402

client = TestClient(api.app)


def post_reading(tank, temp, age_h=0, ph=7.5, do=6.0):
    ts = (datetime.now(timezone.utc) - timedelta(hours=age_h)).isoformat()
    return client.post("/api/water-readings", json={
        "tankId": tank, "species": "tilapia", "lifeStage": "adult", "system": "ras",
        "timestamp": ts, "source": "manual",
        "measurements": {"temperature": {"value": temp, "unit": "C"},
                         "pH": {"value": ph, "unit": "pH"},
                         "dissolvedOxygen": {"value": do, "unit": "mg/L"}}})


def risk_of(tank):
    r = client.post("/api/risk", json={"tankId": tank})
    assert r.status_code == 200, r.text
    return r.json()


class Levels(unittest.TestCase):
    def test_no_rule_triggered_is_normal(self):
        self.assertEqual(post_reading("R-NORM", 29.5).status_code, 201)
        doc = risk_of("R-NORM")
        self.assertEqual(doc["status"], "NORMAL")
        self.assertEqual(doc["domains"]["water"]["origin"], "rule-based")
        self.assertEqual(doc["domains"]["behavior"]["origin"], "experimental")
        self.assertFalse(doc["domains"]["video"]["used_in_risk"])

    def test_warning_rule_is_watch(self):
        post_reading("R-WATCH", 33.0)
        self.assertEqual(risk_of("R-WATCH")["status"], "WATCH")

    def test_high_concern_is_warning(self):
        post_reading("R-WARN", 36.0)
        doc = risk_of("R-WARN")
        self.assertEqual(doc["status"], "WARNING")
        self.assertTrue(doc["triggered_rules"])
        self.assertTrue(all(t["provisional"] for t in doc["triggered_rules"]))
        self.assertTrue(doc["recommended_checks"])

    def test_unconfirmed_critical_is_warning_not_critical(self):
        post_reading("R-CRIT1", 40.0)
        doc = risk_of("R-CRIT1")
        self.assertEqual(doc["status"], "WARNING")  # single reading: must repeat to confirm
        self.assertTrue(any("repeat" in u.lower() for u in doc["uncertainty"]))

    def test_confirmed_critical_is_critical(self):
        post_reading("R-CRIT2", 40.0)
        post_reading("R-CRIT2", 40.5)
        self.assertEqual(risk_of("R-CRIT2")["status"], "CRITICAL")

    def test_partial_core_data_is_insufficient(self):
        ts = datetime.now(timezone.utc).isoformat()
        r = client.post("/api/water-readings", json={
            "tankId": "R-INS", "species": "tilapia", "lifeStage": "adult", "system": "ras",
            "timestamp": ts, "source": "manual",
            "measurements": {"turbidity": {"value": 5, "unit": "NTU"}}})
        self.assertEqual(r.status_code, 201)
        self.assertEqual(risk_of("R-INS")["status"], "INSUFFICIENT_DATA")

    def test_stale_core_reading_is_insufficient_not_normal(self):
        post_reading("R-STALE", 29.5, age_h=48)  # temperature stale_after_hours = 24
        doc = risk_of("R-STALE")
        # Stale core data is unusable: the engine must not report NORMAL on it.
        self.assertEqual(doc["status"], "INSUFFICIENT_DATA")

    def test_unknown_tank_is_404(self):
        self.assertEqual(client.post("/api/risk", json={"tankId": "NoSuchTank"}).status_code, 404)


class VideoNeutrality(unittest.TestCase):
    """Video evidence must never change the water-driven level (unit-level)."""

    def _combined(self, water_risk, video_available, reliability):
        water = {"waterRisk": water_risk, "summary": "s", "species": "tilapia",
                 "system": "ras", "profile": "p", "lifeStageNote": None,
                 "rulesStatus": "r", "measurements": [], "concerns": [],
                 "notes": [], "dataQuality": {"status": "sufficient", "missing": [],
                                              "stale": [], "contradictory": [],
                                              "coreMissingOrUnusable": []}}
        if water_risk == "no_rule_triggered":
            water["measurements"] = [{"label": "Temperature", "value": 29.5, "unit": "°C",
                                      "level": "normal", "dataQuality": "ok",
                                      "timestamp": "2026-10-16T00:00:00+00:00"}]
        video = {"available": video_available, "reliability": reliability,
                 "observations": ["o"], "usedInRisk": False}
        return {"water": water, "video": video, "overallStatus": "x",
                "dataQuality": {}, "uncertainty": [], "crossNotes": []}

    def test_bad_video_does_not_escalate_normal(self):
        c = self._combined("no_rule_triggered", True,
                           {"detections": "unreliable", "movement": "unreliable"})
        self.assertEqual(risk_engine.assess(c)["status"], "NORMAL")

    def test_good_video_does_not_clear_warning(self):
        c = self._combined("high_concern", True,
                           {"detections": "reliable", "movement": "reliable"})
        doc = risk_engine.assess(c)
        self.assertEqual(doc["status"], "WARNING")
        self.assertFalse(doc["domains"]["video"]["used_in_risk"])

    def test_no_evidence_is_insufficient(self):
        c = self._combined("insufficient_data", False, {})
        self.assertEqual(risk_engine.assess(c)["status"], "INSUFFICIENT_DATA")


if __name__ == "__main__":
    unittest.main()
