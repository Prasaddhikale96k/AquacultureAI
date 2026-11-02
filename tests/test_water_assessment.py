"""Water-quality validation, rule engine, combined assessment and API tests.
All measurement values below are SYNTHETIC TEST FIXTURES, not real readings."""
import copy
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("AQUA_BACKEND_DATA", tempfile.mkdtemp(prefix="aqua_water_test_"))

from starlette.testclient import TestClient  # noqa: E402
import backend.main as api  # noqa: E402
from backend import water  # noqa: E402

NOW = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)
RULES = water.load_rules()
TIL = RULES["profiles"]["tilapia"]


def iso(hours_ago=0.5):
    return (NOW - timedelta(hours=hours_ago)).isoformat()


def payload(meas, **kw):
    p = {"tankId": "T1", "species": "tilapia", "system": "ras", "lifeStage": "juvenile", "timestamp": iso(), "source": "manual", "measurements": meas}
    p.update(kw)
    return p


GOOD = {"temperature": {"value": 28, "unit": "C"}, "pH": {"value": 7.5}, "dissolvedOxygen": {"value": 6.5, "unit": "mg/L"}}


def rec(meas, hours_ago=0.5, **kw):
    return water.validate(payload(meas, timestamp=iso(hours_ago), **kw), RULES, NOW)


def assess(records):
    return water.assess_water(records, RULES, NOW)


def by(a, name):
    return next(m for m in a["measurements"] if m["parameter"] == name)


class Validation(unittest.TestCase):
    def fails(self, p, field):
        with self.assertRaises(water.ValidationError) as c:
            water.validate(p, RULES, NOW)
        self.assertIn(field, c.exception.errors, c.exception.errors)

    def test_required_context_and_timestamp(self):
        for k in ("tankId", "species", "system", "source", "timestamp"):
            p = payload(GOOD)
            p.pop(k)
            self.fails(p, k)
        self.fails(payload(GOOD, timestamp="2026-10-15T10:00:00"), "timestamp")           # no timezone
        self.fails(payload(GOOD, timestamp=(NOW + timedelta(hours=2)).isoformat()), "timestamp")   # future
        self.fails(payload(GOOD, tankId="../etc"), "tankId")
        self.fails(payload(GOOD, species="shark"), "species")

    def test_empty_optional_values_stay_missing_never_zero(self):
        r = rec({**GOOD, "nitrite": {"value": "", "unit": "mg/L-N"}, "salinity": {"value": None}})
        self.assertNotIn("nitrite", r["measurements"])
        self.assertNotIn("salinity", r["measurements"])
        self.fails(payload({"nitrite": {"value": ""}}), "measurements")                    # nothing measured at all

    def test_units_are_converted_and_unsupported_units_rejected(self):
        r = rec({"temperature": {"value": 86, "unit": "F"}, "ammonia": {"value": 1.2, "unit": "mg/L-NH3", "method": "photometer"},
                 "nitrite": {"value": 10, "unit": "umol/L"}, "nitrate": {"value": 44.27, "unit": "mg/L-NO3"}})
        m = r["measurements"]
        self.assertAlmostEqual(m["temperature"]["canonicalValue"], 30.0, places=6)
        self.assertAlmostEqual(m["ammonia"]["canonicalValue"], 1.2 * 0.8224, places=6)
        self.assertAlmostEqual(m["nitrite"]["canonicalValue"], 0.14007, places=6)
        self.assertAlmostEqual(m["nitrate"]["canonicalValue"], 44.27 * 0.2259, places=6)
        self.assertEqual(m["temperature"]["unit"], "F")                                     # entered unit preserved
        self.fails(payload({"pH": {"value": 7, "unit": "bananas"}}), "pH")
        self.fails(payload({"dissolvedOxygen": {"value": 6, "unit": "%"}}), "dissolvedOxygen")

    def test_ammonia_requires_method_and_values_must_be_plausible_numbers(self):
        self.fails(payload({"ammonia": {"value": 0.5, "unit": "mg/L-N"}}), "ammonia")
        for bad in ("abc", float("nan"), float("inf"), True):
            self.fails(payload({"pH": {"value": bad}}), "pH")
        self.fails(payload({"pH": {"value": 15}}), "pH")
        self.fails(payload({"temperature": {"value": 500, "unit": "F"}}), "temperature")
        self.fails(payload({"dissolvedOxygen": {"value": -1}}), "dissolvedOxygen")
        self.fails(payload({"mystery": {"value": 1}}), "mystery")


class Thresholds(unittest.TestCase):
    def test_every_configured_band_boundary(self):
        for system in ("ras", "pond", "biofloc"):
            prof = TIL
            for key, rule in prof["parameters"].items():
                r = water._rule_for(prof, system, key)
                if r is None:
                    continue
                n, b = r["normal"], r["bands"]
                eps = 1e-6
                if n.get("min") is not None:
                    self.assertEqual(water.evaluate(n["min"], r)[0], "normal", key)             # inclusive
                    self.assertEqual(water.evaluate(n["min"] - eps, r)[0], "warning", key)
                if n.get("max") is not None:
                    self.assertEqual(water.evaluate(n["max"], r)[0], "normal", key)
                    self.assertEqual(water.evaluate(n["max"] + eps, r)[0], "warning", key)
                for lvl in ("high_concern", "critical_concern"):
                    for direction, sign in (("below", -1), ("above", 1)):
                        if direction in b.get(lvl, {}):
                            t = b[lvl][direction]
                            self.assertNotEqual(water.evaluate(t, r)[0], lvl, f"{key} {lvl} boundary is exclusive")
                            got = water.evaluate(t + sign * eps, r)
                            self.assertEqual((got[0], got[1], got[2]), (lvl, direction, t), key)

    def test_config_normal_ranges_come_from_project_config(self):
        base = json.loads((ROOT / "water_quality_config.json").read_text())
        self.assertEqual(TIL["parameters"]["temperature"]["normal"], base["temperature_C"])
        self.assertEqual(TIL["parameters"]["dissolvedOxygen"]["normal"], base["DO_mgL"])

    def test_ammonia_is_assessed_as_unionized_from_same_reading(self):
        self.assertAlmostEqual(water.unionized_fraction(8.0, 25.0), 0.054, places=3)          # published Emerson table: ~5.4% at pH 8, 25 °C
        self.assertAlmostEqual(water.unionized_fraction(7.0, 25.0), 0.0057, delta=0.0002)
        f = water.unionized_fraction(8.0, 30.0)
        for target, level in ((0.04, "normal"), (0.1, "warning"), (0.3, "high_concern"), (0.7, "critical_concern")):
            tan = target / f
            a = assess([rec({"temperature": {"value": 30}, "pH": {"value": 8.0}, "ammonia": {"value": tan, "unit": "mg/L-N", "method": "photometer"}})])
            self.assertEqual(by(a, "ammonia")["level"], level, target)
        a = assess([rec({"ammonia": {"value": 5, "unit": "mg/L-N", "method": "photometer"}})])    # no pH/temperature
        self.assertEqual(by(a, "ammonia")["level"], "insufficient_data")

    def test_triggered_rule_is_explained(self):
        a = assess([rec({**GOOD, "dissolvedOxygen": {"value": 2.5}})])
        m = by(a, "dissolvedOxygen")
        self.assertEqual(m["level"], "high_concern")
        self.assertEqual((m["rule"]["id"], m["rule"]["direction"], m["rule"]["threshold"]), ("dissolvedOxygen.high_concern.below", "below", 3.0))
        self.assertIn("2.5", m["message"])
        self.assertIn("mg/L", m["message"])
        self.assertTrue(m["check"] and m["actions"])
        self.assertTrue(m["rule"]["provisional"])


class MissingStaleContradictory(unittest.TestCase):
    def test_missing_measurements_are_not_safe_and_not_fabricated(self):
        a = assess([rec({"temperature": {"value": 28}})])
        self.assertEqual(a["waterRisk"], "insufficient_data")
        for p in ("pH", "dissolvedOxygen", "ammonia"):
            m = by(a, p)
            self.assertEqual((m["dataQuality"], m["level"], m["value"]), ("missing", "insufficient_data", None))
        self.assertIn("pH", a["dataQuality"]["coreMissingOrUnusable"])

    def test_only_complete_fresh_core_data_can_report_no_rule_triggered(self):
        a = assess([rec(GOOD)])
        self.assertEqual(a["waterRisk"], "no_rule_triggered")
        self.assertIn("not a statement that conditions are safe", a["summary"])

    def test_stale_values_are_not_treated_as_current(self):
        a = assess([rec(GOOD, hours_ago=48)])
        self.assertEqual(a["waterRisk"], "insufficient_data")
        self.assertEqual(by(a, "pH")["dataQuality"], "stale")
        self.assertEqual(by(a, "pH")["level"], "insufficient_data")
        bad_but_stale = assess([rec({**GOOD, "dissolvedOxygen": {"value": 1.0}}, hours_ago=48)])
        self.assertNotIn(bad_but_stale["waterRisk"], ("critical_concern",))

    def test_contradictory_oxygen_is_flagged_and_ignored(self):
        a = assess([rec({"temperature": {"value": 28}, "pH": {"value": 7.5}, "dissolvedOxygen": {"value": 20}})])
        self.assertEqual(by(a, "dissolvedOxygen")["dataQuality"], "contradictory")
        self.assertEqual(a["waterRisk"], "insufficient_data")

    def test_latest_reading_per_parameter_is_used(self):
        a = assess([rec({"pH": {"value": 5.0}}, hours_ago=5), rec({"pH": {"value": 7.2}}, hours_ago=1)])
        self.assertEqual(by(a, "pH")["value"], 7.2)


class Concerns(unittest.TestCase):
    def test_multiple_concerns_and_no_double_counting(self):
        a = assess([rec({"temperature": {"value": 36}, "pH": {"value": 9.2}, "dissolvedOxygen": {"value": 1.5},
                         "ammonia": {"value": 5, "unit": "mg/L-N", "method": "test_kit_colorimetric"}, "nitrite": {"value": 3}})])
        self.assertEqual(a["waterRisk"], "critical_concern")
        groups = {g["group"]: g for g in a["concernGroups"]}
        self.assertEqual(set(groups), {"thermal", "acid_base", "oxygen", "nitrogen_cycle"})
        self.assertEqual(sorted(groups["nitrogen_cycle"]["parameters"]), ["ammonia", "nitrite"])   # one issue, two parameters
        self.assertTrue(len(a["concerns"]) >= 5)
        self.assertTrue(any("pH raises" in n for n in a["notes"]))
        self.assertTrue(any("oxygen" in n for n in a["notes"]))

    def test_single_high_reading_is_unconfirmed_and_repeat_confirms(self):
        one = assess([rec({**GOOD, "dissolvedOxygen": {"value": 2.5}})])
        self.assertIs(by(one, "dissolvedOxygen")["confirmed"], False)
        self.assertIn("single reading", by(one, "dissolvedOxygen")["message"])
        two = assess([rec({**GOOD, "dissolvedOxygen": {"value": 2.8}}, hours_ago=3), rec({**GOOD, "dissolvedOxygen": {"value": 2.5}}, hours_ago=1)])
        m = by(two, "dissolvedOxygen")
        self.assertIs(m["confirmed"], True)
        self.assertEqual(m["persistence"], 1)

    def test_species_and_system_specific_rules(self):
        self.assertEqual(by(assess([rec({"turbidity": {"value": 70}}, system="ras")]), "turbidity")["level"], "high_concern")
        self.assertEqual(by(assess([rec({"turbidity": {"value": 70}}, system="pond")]), "turbidity")["level"], "warning")
        self.assertEqual(by(assess([rec({"turbidity": {"value": 700}}, system="biofloc")]), "turbidity")["level"], "not_assessed")
        other = assess([rec(GOOD, species="other")])
        self.assertEqual(other["waterRisk"], "insufficient_data")
        self.assertIn("No rules are configured", by(other, "pH")["message"])

    def test_rules_can_be_changed_without_touching_the_engine(self):
        edited = copy.deepcopy(json.loads(water.RULES_PATH.read_text()))
        edited["profiles"]["tilapia"]["parameters"]["dissolvedOxygen"]["bands"]["high_concern"]["below"] = 5.5
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "rules.json"
            p.write_text(json.dumps(edited))
            with mock.patch.object(water, "RULES_PATH", p):
                rules = water.load_rules()
        a = water.assess_water([rec({**GOOD, "dissolvedOxygen": {"value": 5.2}})], rules, NOW)
        self.assertEqual(by(a, "dissolvedOxygen")["level"], "high_concern")


class Combined(unittest.TestCase):
    UNRELIABLE = {"videoName": "x.mp4", "reliability": {"detections": "unreliable", "movement": "unreliable", "tracking": "unavailable"},
                  "processing": {"framesProcessed": 288, "framesTotal": 288, "sampling": "every frame, no sampling"},
                  "detections": {"reasons": ["bad masks"]}, "movement": {"reasons": []}}

    def test_video_never_changes_water_risk(self):
        w = assess([rec({**GOOD, "dissolvedOxygen": {"value": 4.0}})])
        before = json.dumps(w, sort_keys=True)
        c1 = water.combine(w, water.video_summary(None))
        c2 = water.combine(w, water.video_summary(self.UNRELIABLE))
        self.assertEqual(json.dumps(w, sort_keys=True), before)
        self.assertEqual((c1["water"]["waterRisk"], c2["water"]["waterRisk"]), ("warning", "warning"))
        self.assertIs(c2["video"]["usedInRisk"], False)
        self.assertTrue(c2["crossNotes"])                                   # explains video cannot confirm anything
        self.assertTrue(any("not reliable" in u for u in c2["uncertainty"]))

    def test_overall_status_never_says_safe_and_reflects_data_quality(self):
        ok = water.combine(assess([rec(GOOD)]), water.video_summary(None))
        self.assertEqual(ok["overallStatus"], "no_rule_triggered")
        self.assertTrue(any("No analysed video" in u for u in ok["uncertainty"]))
        self.assertEqual(water.combine(None, water.video_summary(None))["overallStatus"], "insufficient_data")
        self.assertEqual(water.combine(assess([rec({"temperature": {"value": 28}})]), water.video_summary(None))["overallStatus"], "insufficient_data")
        high = water.combine(assess([rec({**GOOD, "dissolvedOxygen": {"value": 2.5}})]), water.video_summary(None))
        self.assertEqual(high["overallStatus"], "action_recommended")
        self.assertIn("not a diagnosis", " ".join(ok["uncertainty"]))

    def test_video_summary_states_frame_level_counts(self):
        s = water.video_summary(self.UNRELIABLE)
        txt = " ".join(s["observations"])
        self.assertIn("not unique fish", txt)
        self.assertIn("Processed 288 of 288", txt)
        self.assertFalse(water.video_summary(None, "Video analysis is failed.")["available"])


class Api(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="aqua_water_api_")
        cls.old = water._ctx["data"]
        water.init(cls.tmp, api._video_result)
        cls.c = TestClient(api.app)

    @classmethod
    def tearDownClass(cls):
        water.init(cls.old, api._video_result)

    def post(self, meas, **kw):
        p = payload(meas, **kw)
        p["timestamp"] = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        return self.c.post("/api/water-readings", json=p)

    def test_config_and_validation_errors(self):
        cfg = self.c.get("/api/water-config").json()
        self.assertIn("tilapia", cfg["options"]["species"])
        self.assertIn("mg/L-NH3", cfg["units"]["ammonia"])
        r = self.c.post("/api/water-readings", json={"tankId": "", "measurements": {}})
        self.assertEqual(r.status_code, 422)
        self.assertIn("tankId", r.json()["fields"])
        self.assertEqual(self.c.post("/api/water-readings", content=b"nope").status_code, 400)
        self.assertEqual(self.c.get("/api/water-assessment?tankId=../x").status_code, 422)
        self.assertEqual(self.c.get("/api/water-assessment?tankId=NoSuchTank").status_code, 404)
        self.assertEqual(self.c.get("/api/assessment?jobId=zz").status_code, 422)

    def test_submit_edit_history_and_assessment(self):
        r = self.post({**GOOD, "dissolvedOxygen": {"value": 2.5}}, tankId="TA")
        self.assertEqual(r.status_code, 201)
        body = r.json()
        self.assertEqual(body["assessment"]["waterRisk"], "high_concern")
        first = body["reading"]["id"]
        fix = self.post({**GOOD, "dissolvedOxygen": {"value": 6.5}}, tankId="TA", supersedes=first)       # corrected entry
        self.assertEqual(fix.status_code, 201)
        self.assertEqual(fix.json()["assessment"]["waterRisk"], "no_rule_triggered")
        hist = self.c.get("/api/water-readings?tankId=TA").json()
        self.assertEqual(len(hist["readings"]), 2)                                                      # history keeps the old reading
        self.assertEqual({h["id"]: h["superseded"] for h in hist["readings"]}[first], True)
        self.assertIn("TA", hist["tanks"])
        self.assertEqual(self.c.get("/api/water-assessment?tankId=TA").json()["waterRisk"], "no_rule_triggered")
        bad = self.post(GOOD, tankId="TA", supersedes="0" * 32)
        self.assertEqual(bad.status_code, 422)
        self.assertIn("supersedes", bad.json()["fields"])

    def test_storage_is_append_only_and_other_tanks_untouched(self):
        self.post(GOOD, tankId="TB")
        f = Path(self.tmp) / "water_readings.jsonl"
        before = f.read_text()
        self.post({"pH": {"value": 7.0}}, tankId="TC")
        self.assertTrue(f.read_text().startswith(before))
        self.assertEqual(len(self.c.get("/api/water-readings?tankId=TB").json()["readings"]), 1)

    def test_combined_uses_real_job_results_and_preserves_them(self):
        jid = "ab" * 16
        d = api.JOBS / jid
        d.mkdir(parents=True)
        try:
            (d / "job.json").write_text(json.dumps({"id": jid, "state": "completed", "filename": "t.mp4", "video": "video.mp4", "createdAt": "x", "error": None}))
            res = json.dumps(Combined.UNRELIABLE)
            (d / "result.json").write_text(res)
            self.post(GOOD, tankId="TD")
            c = self.c.get(f"/api/assessment?tankId=TD&jobId={jid}").json()
            self.assertTrue(c["video"]["available"])
            self.assertIs(c["video"]["usedInRisk"], False)
            self.assertEqual(c["water"]["waterRisk"], "no_rule_triggered")
            self.assertEqual((d / "result.json").read_text(), res)                                      # previous output preserved
            self.assertFalse(self.c.get("/api/assessment?tankId=TD&jobId=" + "cd" * 16).json()["video"]["available"])
        finally:
            for p in d.glob("*"):
                p.unlink()
            d.rmdir()


if __name__ == "__main__":
    unittest.main()
