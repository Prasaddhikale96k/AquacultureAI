"""Track IV F1/F3/F4/F5 tests: feeding, digest, backup/export, diagnostics."""
import json
import os
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock
from zipfile import ZipFile
import io

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["AQUA_SCHEDULER"] = "0"
os.environ["AQUA_AUTH_MODE"] = "open"
os.environ["AQUA_BACKEND_DATA"] = tempfile.mkdtemp(prefix="aqua_t4_base_")

from starlette.testclient import TestClient  # noqa: E402
import backend.main as api  # noqa: E402
from backend import alerts, sensors  # noqa: E402
from backend.app.services import (backup_service, behaviour_service, digest_service,  # noqa: E402
                                  diagnostics_service, do_service, farm_clock, feeding_service)
from backend.app.auth import tokens  # noqa: E402


def _iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).isoformat()


def _obs(end, speed, count=2):
    return {"window_start_t": end - 300, "window_end_t": end, "view": "side",
            "metrics": {"speed_mean_pxs": speed, "count_confirmed": count,
                        "surface_ratio": 0.1, "lethargy_ratio": 0.1}}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="aqua_t4_"))
        self.old = os.environ.get("AQUA_BACKEND_DATA")
        self.old_bk = os.environ.get("AQUA_BACKUP_DIR")
        self.old_flag = os.environ.get("AQUA_BACKUP")
        os.environ["AQUA_BACKEND_DATA"] = str(self.tmp)
        os.environ["AQUA_BACKUP_DIR"] = str(self.tmp / "backups")
        os.environ["AQUA_BACKUP"] = "1"
        alerts._loaded = False
        alerts._last_sent = {}
        alerts._prev_active = set()

    def tearDown(self):
        for name, old in (("AQUA_BACKEND_DATA", self.old), ("AQUA_BACKUP_DIR", self.old_bk),
                          ("AQUA_BACKUP", self.old_flag)):
            if old is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = old


class FeedingTests(Base):
    def test_log_and_aggressive_grade(self):
        now = time.time()
        feed = feeding_service.log_feeding(now - 900)
        behaviour_service.append_observation(_obs(now - 1200, 10))
        behaviour_service.append_observation(_obs(now - 600, 20))
        updated = feeding_service.update_responses(now)
        row = next(r for r in updated if r["id"] == feed["id"])
        self.assertEqual(row["response"], "aggressive")
        self.assertGreater(row["response_delta"], 0.3)
        self.assertEqual(len(feeding_service.read_events(2)), 1)
        self.assertTrue(feeding_service.counts_today(now) >= 1)

    def test_weak_feedings_alert_once_with_english_sms(self):
        now = time.time()
        feeding_service.log_feeding(now - 3600)
        feeding_service.log_feeding(now - 1200)
        behaviour_service.append_observation(_obs(now - 3900, 10))
        behaviour_service.append_observation(_obs(now - 3300, 10.5))
        behaviour_service.append_observation(_obs(now - 1500, 10))
        behaviour_service.append_observation(_obs(now - 900, 10.5))
        with mock.patch.dict(os.environ, {"AQUA_FEED_ALERT": "1"}), \
                mock.patch.object(alerts, "send_alert", return_value={"delivered": False}) as send:
            feeding_service.update_responses(now)
        self.assertEqual(send.call_count, 1)
        rule, msg = send.call_args.args[:2]
        self.assertEqual(rule, "R9")
        self.assertIn("Weak feeding response 2 times in a row", msg)
        self.assertIn("Check water/DO/fish health", msg)
        self.assertLessEqual(len(msg), 160)

    def test_no_tracks_is_none_grade(self):
        now = time.time()
        feeding_service.log_feeding(now - 900)
        behaviour_service.append_observation(_obs(now - 1200, 10))
        behaviour_service.append_observation(_obs(now - 600, 0, count=0))
        feeding_service.update_responses(now)
        rows = feeding_service.read_events(2)
        self.assertEqual(rows[-1]["response"], "none")

    def test_feed_dip_evidence_and_flag(self):
        now = time.time()
        feeding_service.log_feeding(now - 3 * 3600)

        def series(field, minutes=1440):
            return [(now - 60, 28.0), (now, 28.0)] if field == "temperature" else [(now, 22.5)]

        with mock.patch.dict(os.environ, {"AQUA_DO_FEED_DIP": "1"}):
            with mock.patch.object(sensors, "series", side_effect=series):
                p = do_service.prediction(now=now)
        self.assertEqual(p["feed_evidence"]["s_feed"], -0.08)
        self.assertAlmostEqual(p["feed_evidence"]["last_feed_age_h"], 3.0, places=1)
        with mock.patch.dict(os.environ, {"AQUA_DO_FEED_DIP": "0"}):
            with mock.patch.object(sensors, "series", side_effect=series):
                p2 = do_service.prediction(now=now)
        self.assertEqual(p2["feed_evidence"]["s_feed"], 0.0)

    def test_logging_flag_off(self):
        with mock.patch.dict(os.environ, {"AQUA_FEED_LOG": "0"}):
            with self.assertRaises(PermissionError):
                feeding_service.log_feeding()

    def test_api_contract_and_validation(self):
        c = TestClient(api.app)
        with mock.patch.dict(os.environ, {"AQUA_FEED_LOG": "1"}):
            r = c.post("/api/feeding", json={"note": "morning"})
            self.assertEqual(r.status_code, 201)
            self.assertEqual(r.json()["feeding"]["note"], "morning")
            self.assertEqual(r.json()["feeding"]["response"], None)
            self.assertEqual(c.post("/api/feeding", json={"fed_at": "not-a-date"}).status_code, 422)
            future = datetime.now(timezone.utc).timestamp() + 3600
            self.assertEqual(c.post("/api/feeding", json={"fed_at": _iso(future)}).status_code, 422)
            g = c.get("/api/feeding")
            self.assertEqual(g.status_code, 200)
            body = g.json()
            self.assertTrue(body["enabled"])
            self.assertIn("dip", body)
            self.assertEqual(body["count"], 1)


class DigestTests(Base):
    def test_message_contains_required_sections(self):
        now = time.time()
        with mock.patch.object(sensors, "stats", return_value={"stale_s": 60}), \
                mock.patch.object(alerts, "khatra", return_value={"score": 42}), \
                mock.patch.object(do_service, "prediction", return_value={"status": "ok", "do_mgl": 4.2}), \
                mock.patch.object(do_service, "read_readings", return_value=[]), \
                mock.patch.object(behaviour_service, "summary", return_value={"state": "calm"}), \
                mock.patch.object(feeding_service, "counts_today", return_value=2):
            msg, stale = digest_service.build_message(now)
        self.assertFalse(stale)
        self.assertIn("DO 4.2 mg/L at night", msg)
        self.assertIn("behaviour calm", msg)
        self.assertIn("risk 42/100", msg)
        self.assertIn("Feedings today 2", msg)
        self.assertIn("-AquaAI", msg)
        self.assertLessEqual(len(msg), 300)

    def test_stale_variant(self):
        with mock.patch.object(sensors, "stats", return_value={"stale_s": 7200}):
            msg, stale = digest_service.build_message(time.time())
        self.assertTrue(stale)
        self.assertIn("sensor data stale 2.0h", msg)
        self.assertIn("No DO/behaviour summary", msg)
        self.assertLessEqual(len(msg), 300)

    def test_once_per_farm_day(self):
        now = time.time()
        state = self.tmp / "daily_digest.json"
        if state.exists():
            state.unlink()
        with mock.patch.dict(os.environ, {"AQUA_DAILY_SMS_TIME": "00:00"}), \
                mock.patch.object(digest_service, "build_message", return_value=("x" * 300, False)), \
                mock.patch.object(alerts, "send_alert", return_value={}) as send:
            first = digest_service.maybe_send(now)
            second = digest_service.maybe_send(now + 60)
        self.assertTrue(first["sent"])
        self.assertFalse(second["sent"])
        self.assertEqual(send.call_count, 1)

    def test_before_send_time(self):
        now = time.time()
        with mock.patch.dict(os.environ, {"AQUA_DAILY_SMS_TIME": "23:59"}), \
                mock.patch.object(farm_clock, "farm_now",
                                  return_value=datetime(2026, 10, 24, 6, 0, tzinfo=timezone.utc)), \
                mock.patch.object(digest_service, "build_message") as build:
            r = digest_service.maybe_send(now)
        self.assertFalse(r["sent"])
        build.assert_not_called()


class BackupTests(Base):
    def _seed(self):
        (self.tmp / "sensors.jsonl").write_text('{"ok":1}\n', encoding="utf-8")
        (self.tmp / "do_cal.json").write_text('{"a":1}', encoding="utf-8")
        (self.tmp / "jobs").mkdir()
        (self.tmp / "jobs" / "frame.jpg").write_bytes(b"not-a-backup")

    def test_backup_copies_top_level_only(self):
        self._seed()
        now = datetime(2026, 10, 24, 12, tzinfo=timezone.utc).timestamp()
        r = backup_service.backup(now)
        dest = Path(r["dir"])
        self.assertTrue((dest / "sensors.jsonl").is_file())
        self.assertTrue((dest / "do_cal.json").is_file())
        self.assertFalse((dest / "jobs").exists())
        self.assertFalse((dest / "backups").exists())

    def test_retention_prunes_old_days(self):
        self._seed()
        root = backup_service._backup_root()
        old = root / "2000-01-01"
        old.mkdir(parents=True)
        (old / "x.json").write_text("{}", encoding="utf-8")
        now = datetime(2026, 10, 24, 12, tzinfo=timezone.utc).timestamp()
        r = backup_service.backup(now)
        self.assertIn("2000-01-01", r["pruned"])
        self.assertFalse(old.exists())

    def test_export_zip_excludes_jobs_and_backups(self):
        self._seed()
        (self.tmp / "backups").mkdir()
        (self.tmp / "backups" / "x.json").write_text("{}", encoding="utf-8")
        payload, names = backup_service.export_zip()
        self.assertIn("sensors.jsonl", names)
        self.assertNotIn("jobs", names)
        self.assertNotIn("backups", names)
        with ZipFile(io.BytesIO(payload)) as zf:
            self.assertIn("sensors.jsonl", zf.namelist())
            self.assertNotIn("jobs/frame.jpg", zf.namelist())

    def test_backup_flag_off(self):
        with mock.patch.dict(os.environ, {"AQUA_BACKUP": "0"}):
            self.assertFalse(backup_service.maybe_backup()["created"])


class DiagnosticsTests(Base):
    def test_snapshot_allow_list_has_no_secrets(self):
        snap = diagnostics_service.snapshot()
        blob = json.dumps(snap).lower()
        for secret in ("api_key", "auth_key", "textbee_api", "phone_number", "password"):
            self.assertNotIn(secret, blob)
        for key in ("generated_at", "sensors", "sms", "live", "auth", "data", "flags"):
            self.assertIn(key, snap)
        self.assertIn("AQUA_FARM_TZ", snap["flags"])
        self.assertNotIn("last_entry", snap["sensors"])

    def test_diagnostics_is_public_in_full_auth(self):
        old = os.environ.get("AQUA_AUTH_MODE")
        os.environ["AQUA_AUTH_MODE"] = "full"
        try:
            c = TestClient(api.app)
            r = c.get("/api/diagnostics")
            self.assertEqual(r.status_code, 200)
            self.assertEqual(c.get("/api/alerts").status_code, 401)
        finally:
            if old is None:
                os.environ.pop("AQUA_AUTH_MODE", None)
            else:
                os.environ["AQUA_AUTH_MODE"] = old

    def test_active_session_count(self):
        tokens.clear_sessions()
        self.assertEqual(tokens.active_count(), 0)

    def test_export_route_returns_zip(self):
        (self.tmp / "sensors.jsonl").write_text('{"ok":1}\n', encoding="utf-8")
        with mock.patch.dict(os.environ, {"AQUA_EXPORT": "1"}):
            c = TestClient(api.app)
            r = c.get("/api/export/zip")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers["content-type"], "application/zip")
        with ZipFile(io.BytesIO(r.content)) as zf:
            self.assertIn("sensors.jsonl", zf.namelist())


if __name__ == "__main__":
    unittest.main()
