"""Structured explanation (§8.2/§8.3) + history store tests. All LLM calls mocked."""
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
_TMP = tempfile.mkdtemp(prefix="aqua_explain_test_")
os.environ["AQUA_BACKEND_DATA"] = _TMP
os.environ["EXPLAIN_COOLDOWN_S"] = "60"
# NOTE: never set GROQ_API_KEY/GEMINI_API_KEY at module level here — this file
# shares a process with the whole suite and leaked keys change backend selection
# in unrelated tests. Keys are set per-test below and always restored.

import unittest  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402
import backend.main as api  # noqa: E402
from backend import llm, history  # noqa: E402

client = TestClient(api.app)

EVIDENCE = {"risk_status": "WATCH", "water_risk": "warning", "readings": [],
            "triggered_rules": [], "data_quality": {}, "video": {"available": False},
            "behavior": "experimental", "uncertainty": []}

GOOD_JSON = json.dumps({
    "summary": "Warm water needs a re-check.",
    "water_quality_explanation": "Temperature above the provisional range.",
    "behavior_observations": "No validated behavior data.",
    "risk_factors": ["Warm water holds less oxygen"],
    "supporting_evidence": ["Temp 33 C (warning)"],
    "recommended_checks": ["Re-measure temperature"],
    "missing_information": ["Dissolved oxygen history"],
    "limitations": ["Provisional thresholds"],
})


def _mk_response(text):
    return ("gemini", "gemini-3.1-pro-preview", text, [])


class StructuredValidation(unittest.TestCase):
    def test_valid_json_accepted(self):
        with mock.patch.object(llm, "_run_text", return_value=_mk_response(GOOD_JSON)):
            exp, prov, model, tried = llm.explain_structured(EVIDENCE)
            self.assertEqual(exp["summary"], "Warm water needs a re-check.")
            self.assertEqual(exp["risk_factors"], ["Warm water holds less oxygen"])
            self.assertEqual(prov, "gemini")

    def test_missing_field_falls_to_next_provider_then_fails(self):
        bad = json.dumps({"summary": "only"})
        with mock.patch.object(llm, "_run_text", return_value=("groq", "m", bad, ["groq:m"])):
            with self.assertRaises(llm.LlmError):
                llm.explain_structured(EVIDENCE)

    def test_non_json_output_rejected(self):
        with mock.patch.object(llm, "_run_text", return_value=_mk_response("just some prose")):
            with self.assertRaises(llm.LlmError):
                llm.explain_structured(EVIDENCE)

    def test_no_keys_raises(self):
        saved = {k: os.environ.get(k) for k in ("GROQ_API_KEY", "GEMINI_API_KEY")}
        os.environ.pop("GROQ_API_KEY", None)
        os.environ.pop("GEMINI_API_KEY", None)
        try:
            with self.assertRaises(llm.NoKeysError):
                llm.explain_structured(EVIDENCE)
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v


class CacheCooldown(unittest.TestCase):
    def setUp(self):
        p = Path(_TMP) / "explanations.json"
        if p.is_file():
            p.unlink()

    def test_unchanged_evidence_reuses_cache_no_second_call(self):
        with mock.patch.object(llm, "_run_text", return_value=_mk_response(GOOD_JSON)) as m:
            r1, cached1 = llm.explain_cached("scope:A", EVIDENCE)
            r2, cached2 = llm.explain_cached("scope:A", EVIDENCE)
            self.assertFalse(cached1)
            self.assertTrue(cached2)
            self.assertEqual(m.call_count, 1)  # no duplicate LLM call
            self.assertEqual(r1["summary"], r2["summary"])
            self.assertIn("generated_at", r2)

    def test_changed_evidence_within_cooldown_raises_with_last(self):
        other = dict(EVIDENCE, risk_status="WARNING")
        with mock.patch.object(llm, "_run_text", return_value=_mk_response(GOOD_JSON)):
            llm.explain_cached("scope:B", EVIDENCE)
            with self.assertRaises(llm.CooldownError) as cm:
                llm.explain_cached("scope:B", other)
            self.assertGreater(cm.exception.retry_after_s, 0)
            self.assertIsNotNone(cm.exception.last)


class Endpoint(unittest.TestCase):
    def test_explanation_needs_evidence_first(self):
        self.assertEqual(client.post("/api/explanation", json={"tankId": "NoTank"}).status_code, 404)

    def test_explanation_end_to_end_mocked_llm(self):
        from datetime import datetime, timezone
        r = client.post("/api/water-readings", json={
            "tankId": "E-T1", "species": "tilapia", "lifeStage": "adult", "system": "ras",
            "timestamp": datetime.now(timezone.utc).isoformat(), "source": "manual",
            "measurements": {"temperature": {"value": 33, "unit": "C"},
                             "pH": {"value": 7.5, "unit": "pH"},
                             "dissolvedOxygen": {"value": 6, "unit": "mg/L"}}})
        self.assertEqual(r.status_code, 201)
        with mock.patch.object(api.llm, "_run_text", return_value=_mk_response(GOOD_JSON)):
            r = client.post("/api/explanation", json={"tankId": "E-T1"})
            self.assertEqual(r.status_code, 200, r.text)
            body = r.json()
            self.assertIn("summary", body)
            self.assertEqual(body["risk_status"], "WATCH")  # deterministic status travels along
            self.assertTrue(body["llm_generated"])
            # second call: cache reused, no new LLM call
            with mock.patch.object(api.llm, "_run_text",
                                   side_effect=AssertionError("must not call LLM")):
                r2 = client.post("/api/explanation", json={"tankId": "E-T1"})
                self.assertTrue(r2.json()["cached"])

    def test_deterministic_risk_available_when_llm_fails(self):
        from datetime import datetime, timezone
        r = client.post("/api/water-readings", json={
            "tankId": "E-T2", "species": "tilapia", "lifeStage": "adult", "system": "ras",
            "timestamp": datetime.now(timezone.utc).isoformat(), "source": "manual",
            "measurements": {"temperature": {"value": 29.5, "unit": "C"},
                             "pH": {"value": 7.5, "unit": "pH"},
                             "dissolvedOxygen": {"value": 6, "unit": "mg/L"}}})
        self.assertEqual(r.status_code, 201)
        with mock.patch.object(api.llm, "_run_text",
                               side_effect=llm.LlmError("all", "all", "down")):
            r = client.post("/api/explanation", json={"tankId": "E-T2"})
            self.assertEqual(r.status_code, 502)
            self.assertEqual(client.post("/api/risk", json={"tankId": "E-T2"}).status_code, 200)


class HistoryStore(unittest.TestCase):
    def test_record_and_query(self):
        history.record("video_analysis", job_id="abc", status="completed")
        history.record("water_reading", tank_id="T", water_risk="warning")
        recs, skipped = history.query(limit=10)
        self.assertGreaterEqual(len(recs), 2)
        self.assertEqual(recs[0]["ts"] >= recs[-1]["ts"], True)
        only_video, _ = history.query(event="video_analysis")
        self.assertTrue(all(r["event"] == "video_analysis" for r in only_video))

    def test_no_secrets_stored(self):
        history.record("explanation", api_key="SECRET", provider="gemini")
        recs, _ = history.query(limit=5)
        self.assertNotIn("SECRET", json.dumps(recs))

    def test_endpoint(self):
        r = client.get("/api/history?limit=5")
        self.assertEqual(r.status_code, 200)
        self.assertIn("records", r.json())
        self.assertEqual(client.get("/api/history?limit=nope").status_code, 422)


if __name__ == "__main__":
    unittest.main()
