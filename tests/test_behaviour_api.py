"""BEH-A/BEH-B tests: HBS, warming, sustain, SMS repeat, view selection, DO link."""
import json
import math
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
os.environ["AQUA_BACKEND_DATA"] = tempfile.mkdtemp(prefix="aqua_beh_base_")
os.environ["AQUA_SCHEDULER"] = "0"

from starlette.testclient import TestClient  # noqa: E402
import backend.main as api  # noqa: E402
from backend import alerts, sensors  # noqa: E402
from backend.app.services import behaviour_service, do_model, do_service, farm_clock  # noqa: E402


class FakeResp:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, n=2048):
        return b"{}"


def metrics(surface=0.30, lethargy=0.50, speed_z=-2.0, erratic=3.0, count=5, edge=None):
    out = {"speed_mean_pxs": 40.0, "speed_z": speed_z, "lethargy_ratio": lethargy,
           "erratic_z": erratic, "count_confirmed": count, "vertical_cg": 0.12}
    if surface is not None:
        out["surface_ratio"] = surface
    if edge is not None:
        out["edge_ratio"] = edge
    return out


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="aqua_beh_api_")
        self.env = mock.patch.dict(os.environ, {
            "AQUA_BACKEND_DATA": self.tmp,
            "AQUA_SCHEDULER": "0",
            "AQUA_BEH_ALERT": "1",
            "AQUA_BEH_WARMUP_DAYS": "0",
            "AQUA_BEH_HBS_SUSPECT": "60",
            "AQUA_BEH_SMS_REPEAT_MIN": "60",
            "AQUA_BEH_DO_LINK": "1",
            "AQUA_ALERT_PROVIDERS": "textbee,log",
            "AQUA_ALERT_PHONES": "",
            "AQUA_DO_PREDICT": "1",
        }, clear=False)
        self.env.start()
        self.c = TestClient(api.app)
        alerts._last_sent.clear()
        alerts._loaded = True
        alerts._prev_active = set()
        alerts._do_last_level = None
        alerts._do_streak = 0
        sensors._cache = None
        sensors._loaded = False

    def tearDown(self):
        self.env.stop()

    def post(self, end, view="side", m=None):
        body = {"window_start": behaviour_service._iso(end - 300),
                "window_end": behaviour_service._iso(end),
                "view": view, "metrics": m if m is not None else metrics()}
        return self.c.post("/api/behaviour/observations", json=body)

    def seed_high(self, n=3, end=None):
        end = time.time() if end is None else end
        rows = []
        for i in range(n):
            r = self.post(end - (n - 1 - i) * 300)
            rows.append(r)
        return rows


class HbsMath(unittest.TestCase):
    def test_hand_computed_example(self):
        # 40*1 + 25*1 + 20*1 + 15*1 = 100
        self.assertEqual(behaviour_service.hbs_for(metrics(), "side", -2.5, 3), 100)

    def test_clamp_bounds_and_top_view(self):
        self.assertEqual(behaviour_service.hbs_for(metrics(surface=0, lethargy=0, speed_z=5, erratic=0), "side", 5, 0), 0)
        self.assertEqual(behaviour_service.hbs_for(metrics(surface=1, lethargy=1, speed_z=-9, erratic=9), "side", -9, 9), 100)
        self.assertEqual(behaviour_service.hbs_for(metrics(surface=None, edge=0.5, lethargy=0.5, speed_z=0, erratic=0), "top", 0, 0), 65)

    def test_view_selection(self):
        self.assertEqual(behaviour_service.hbs_for(metrics(surface=0.30, lethargy=0, speed_z=0, erratic=0), "side", 0, 0), 40)
        self.assertEqual(behaviour_service.hbs_for(metrics(surface=None, edge=0.50, lethargy=0, speed_z=0, erratic=0), "top", 0, 0), 40)


class Api(Base):
    def test_contract_and_additive_existing_endpoint(self):
        self.post(time.time())
        body = self.c.get("/api/behaviour/summary").json()
        self.assertEqual(set(body), {"state", "hbs", "sustained_min", "view", "window_start",
                                     "window_end", "metrics", "z_scores", "baseline", "threshold",
                                     "label_provisional", "model_version", "reason", "generated_at"})
        self.assertTrue(body["label_provisional"])
        old = self.c.get("/api/behavior-stats")
        self.assertEqual(old.status_code, 200)
        self.assertIn("latest", old.json())
        self.assertIn("anomaly", old.json())

    def test_warming_up_has_null_hbs_and_no_alert(self):
        os.environ["AQUA_BEH_WARMUP_DAYS"] = "3"
        with mock.patch.object(alerts, "send_alert") as send:
            self.post(time.time())
            body = self.c.get("/api/behaviour/summary").json()
        self.assertEqual(body["state"], "warming_up")
        self.assertIsNone(body["hbs"])
        self.assertFalse(send.called)

    def test_sustained_three_windows_and_two_calm_deescalation(self):
        end = time.time()
        self.seed_high(2, end=end - 300)
        body = self.c.get("/api/behaviour/summary").json()
        self.assertNotEqual(body["state"], "hypoxia_suspect")
        self.assertTrue(self.post(end).status_code == 201)
        body = self.c.get("/api/behaviour/summary").json()
        self.assertEqual(body["state"], "hypoxia_suspect")
        self.assertEqual(body["sustained_min"], 15)
        calm = metrics(surface=0, lethargy=0, speed_z=0, erratic=0)
        self.post(end + 300, m=calm)
        self.assertNotEqual(self.c.get("/api/behaviour/summary").json()["state"], "calm")
        self.post(end + 600, m=calm)
        self.assertEqual(self.c.get("/api/behaviour/summary").json()["state"], "calm")

    def test_immediate_sms_and_hourly_repeat(self):
        os.environ.update({"AQUA_ALERT_PHONES": "+919876543210",
                           "TEXTBEE_API_KEY": "k-not-real", "TEXTBEE_DEVICE_ID": "d"})
        end = time.time()
        with mock.patch.object(alerts.urllib.request, "urlopen", return_value=FakeResp()) as up:
            for i in range(3):
                self.post(end - (2 - i) * 300)
            self.assertEqual(up.call_count, 1)
            alerts.evaluate(now=end + 60)
            self.assertEqual(up.call_count, 2)
            alerts.evaluate(now=end + 120)
            self.assertEqual(up.call_count, 2)
        row = next(r for r in alerts.recent(20) if r.get("rule") == "R8")
        self.assertIn("AquaAI BEHAVIOUR", row["message"])
        self.assertIn("15 min", row["message"])
        self.assertTrue(row["message"].isascii())
        self.assertLessEqual(len(row["message"]), 160)

    def test_no_data_when_camera_off(self):
        end = time.time()
        empty = metrics(surface=0, lethargy=0, speed_z=0, erratic=0, count=0)
        for i in range(3):
            self.post(end - (2 - i) * 300, m=empty)
        self.assertEqual(self.c.get("/api/behaviour/summary").json()["state"], "no_data")

    def test_baseline_z_math(self):
        end = time.time()
        for i in range(2):
            self.post(end - (2 - i) * 300, m=metrics(surface=0.1, lethargy=0.1, speed_z=0,
                                                    erratic=0, count=5))
        self.post(end, m={**metrics(surface=0.1, lethargy=0.1, speed_z=0, erratic=0, count=5),
                          "speed_mean_pxs": 80.0})
        z = self.c.get("/api/behaviour/summary").json()["z_scores"]["speed_mean_pxs"]
        self.assertGreater(z, 0)

    def test_side_and_top_view_metrics(self):
        end = time.time()
        r = self.post(end, view="side", m=metrics())
        self.assertEqual(r.status_code, 201)
        side = self.c.get("/api/behaviour/summary").json()
        self.assertEqual(side["view"], "side")
        self.assertIn("surface_ratio", side["metrics"])
        top_m = metrics(surface=None, edge=0.5)
        r = self.post(end + 300, view="top", m=top_m)
        self.assertEqual(r.status_code, 201)
        top = self.c.get("/api/behaviour/summary").json()
        self.assertEqual(top["view"], "top")
        self.assertIn("edge_ratio", top["metrics"])

    def test_validation_and_jsonl_append(self):
        end = time.time()
        bad = [
            {**{"window_start": behaviour_service._iso(end - 300), "window_end": behaviour_service._iso(end),
                 "view": "side"}, "metrics": metrics(surface=-0.1)},
            {**{"window_start": behaviour_service._iso(end - 300), "window_end": behaviour_service._iso(end),
                 "view": "side"}, "metrics": metrics(surface=1.1)},
            {"window_end": behaviour_service._iso(end), "view": "side", "metrics": metrics()},
            {"window_start": behaviour_service._iso(end - 300), "window_end": behaviour_service._iso(end),
             "view": "top", "metrics": metrics(surface=None, edge=None)},
        ]
        for body in bad:
            self.assertEqual(self.c.post("/api/behaviour/observations", json=body).status_code, 422)
        self.assertEqual(self.post(end).status_code, 201)
        p = Path(self.tmp) / "behaviour_obs.jsonl"
        self.assertEqual(len(p.read_text(encoding="utf-8").splitlines()), 1)

    def test_stale_window_is_no_data(self):
        end = time.time()
        self.post(end, m=metrics())
        self.assertEqual(behaviour_service.summary(now=end + 901)["state"], "no_data")

    def test_alert_flag_off_suppresses_immediate_sms(self):
        os.environ["AQUA_BEH_ALERT"] = "0"
        end = time.time()
        with mock.patch.object(alerts, "send_alert") as send:
            for i in range(3):
                self.post(end - (2 - i) * 300)
        self.assertFalse(send.called)
        self.assertEqual(alerts.RULE_POINTS["R8"], 0)

    def test_escalation_pure(self):
        self.assertEqual(behaviour_service.escalate_with_behaviour("safe", "hypoxia_suspect")[0], "watch")
        self.assertEqual(behaviour_service.escalate_with_behaviour("critical", "hypoxia_suspect")[0], "critical")
        self.assertEqual(behaviour_service.escalate_with_behaviour("risk", "calm")[0], "risk")
        self.assertEqual(behaviour_service.escalate_with_behaviour("safe", "calm")[0], "safe")

    def test_do_link_flag_and_alert_flag(self):
        now = time.time()
        fresh = {"t": now, "temperature": 28.0, "turbidity": 300.0}
        ev = {"hbs": 90, "state": "hypoxia_suspect", "sustained_min": 15, "source": "camera-tracks"}
        with mock.patch.object(sensors, "series", side_effect=lambda f, m: [(now - 60, 28.0 if f == "temperature" else 22.5)]), \
             mock.patch.object(behaviour_service, "evidence", return_value=ev):
            base = do_service.prediction(now=now)
            self.assertEqual(base["risk_level"], "risk")
            do_value = base["do_mgl"]
            os.environ["AQUA_BEH_DO_LINK"] = "0"
            off = do_service.prediction(now=now)
            self.assertEqual(off["behaviour_evidence"]["state"], "hypoxia_suspect")
            self.assertEqual(off["risk_level"], "watch")  # physics value stays; no extra escalation
            self.assertEqual(off["do_mgl"], do_value)
        os.environ["AQUA_BEH_DO_LINK"] = "1"
        os.environ["AQUA_BEH_ALERT"] = "0"
        with mock.patch.object(behaviour_service, "evidence", return_value=ev), \
             mock.patch.object(sensors, "latest", return_value=fresh), \
             mock.patch.object(sensors, "recent", return_value=[fresh]):
            rules = alerts.current_rules(now=now)
        self.assertNotIn("R8", {r["rule"] for r in rules})

    def test_farm_tz_hour_bucket(self):
        stamp = datetime(2026, 10, 24, 20, 30, tzinfo=timezone.utc).timestamp()
        self.assertEqual(farm_clock.farm_hour(stamp), 2.0)

    def test_r8_fires_immediately_no_cooldown_gate(self):
        """R8 is an emergency: it must fire on every fresh transition, with no
        60-min cooldown, and must not repeat while the state persists."""
        os.environ.update({"AQUA_ALERT_PHONES": "+919876543210",
                           "TEXTBEE_API_KEY": "k-not-real", "TEXTBEE_DEVICE_ID": "d"})

        def r8_count():
            return sum(1 for r in alerts.recent(200)
                       if r.get("rule") == "R8" and r.get("event") == "alert")

        end = time.time()
        with mock.patch.object(alerts.urllib.request, "urlopen", return_value=FakeResp()):
            # transition into suspect -> one immediate SMS (camera path)
            for i in range(3):
                self.post(end - (2 - i) * 300)
            self.assertEqual(r8_count(), 1)
            # persisting suspect state: R8 must NOT repeat (no cooldown gate
            # needed because it is already in _prev_active).
            alerts.evaluate(now=end + 60)
            self.assertEqual(r8_count(), 1)
            # de-escalate to calm, then re-enter suspect -> fires again immediately
            calm = metrics(surface=0, lethargy=0, speed_z=0, erratic=0)
            self.post(end + 300, m=calm)
            self.post(end + 600, m=calm)
            self.assertEqual(self.c.get("/api/behaviour/summary").json()["state"], "calm")
            for i in range(3):
                self.post(end + 900 + i * 300)
            self.assertEqual(r8_count(), 2)
        row = next(r for r in alerts.recent(20) if r.get("rule") == "R8")
        self.assertIn("AquaAI BEHAVIOUR", row["message"])
        self.assertIn("15 min", row["message"])
        self.assertTrue(row["message"].isascii())
        self.assertLessEqual(len(row["message"]), 160)


if __name__ == "__main__":
    unittest.main()
