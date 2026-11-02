"""API-first backend selection: LLM keys select the API vision path for live-cam
fish analysis even when local training weights are present on disk.

Uses fake keys via mock.patch.dict only (never real credentials) and mocks
api_vision.detect_image so no network calls are made. Training files
(weights/, runs/) are never read, modified, or deleted by these tests.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["AQUA_BACKEND_DATA"] = tempfile.mkdtemp(prefix="aqua_api_select_test_")

from starlette.testclient import TestClient  # noqa: E402
import backend.main as api  # noqa: E402

client = TestClient(api.app)

FAKE_KEYS = {"GROQ_API_KEY": "gsk_test_fake", "GEMINI_API_KEY": "AIza_test_fake"}


def jpeg(img):
    return cv2.imencode(".jpg", img)[1].tobytes()


def clear_llm_env():
    """Snapshot-free cleanup: drop any LLM/backend-selection vars the runner may carry."""
    for k in ("GROQ_API_KEY", "GEMINI_API_KEY", "AQUA_VISION_BACKEND",
              "AQUA_SKIP_GROQ", "AQUA_LIVE_ALLOW_FALLBACK",
              "AQUA_LIVE_ENGINE", "AQUA_WANT_MASKS", "AQUA_CONFIRM_HITS", "AQUA_CONFIRM_WINDOW"):
        os.environ.pop(k, None)


class BackendSelection(unittest.TestCase):
    def setUp(self):
        clear_llm_env()

    def tearDown(self):
        clear_llm_env()

    def test_keys_select_api_despite_weights_present(self):
        self.assertTrue(Path(api.sm.DETECTOR).is_file(), "precondition: trained weights on disk")
        with mock.patch.dict(os.environ, FAKE_KEYS):
            os.environ.pop("AQUA_VISION_BACKEND", None)
            self.assertEqual(api.vision_backend(), "api")

    def test_explicit_yolo_opt_out_wins_over_keys(self):
        with mock.patch.dict(os.environ, {**FAKE_KEYS, "AQUA_VISION_BACKEND": "yolo"}):
            self.assertEqual(api.vision_backend(), "yolo")

    def test_explicit_api_wins_without_keys(self):
        with mock.patch.dict(os.environ, {"AQUA_VISION_BACKEND": "api"}):
            self.assertEqual(api.vision_backend(), "api")

    def test_no_keys_no_explicit_uses_weights(self):
        self.assertEqual(api.vision_backend(), "yolo")

    def test_health_reports_api_backend_when_keys_set(self):
        with mock.patch.dict(os.environ, FAKE_KEYS):
            os.environ.pop("AQUA_VISION_BACKEND", None)
            j = client.get("/health").json()
            self.assertEqual(j["vision_backend"], "api")
            self.assertTrue(j["model_available"])


class LiveDetectApiPath(unittest.TestCase):
    def setUp(self):
        clear_llm_env()

    def tearDown(self):
        clear_llm_env()

    def test_live_detect_uses_llm_not_trained_weights(self):
        canned = {"detections": [{"box": [0.1, 0.2, 0.4, 0.5], "confidence": 0.81}],
                  "provider": "groq", "model": "test-vision-model",
                  "fallback_used": False, "tried": []}
        with mock.patch.dict(os.environ, FAKE_KEYS):
            os.environ.pop("AQUA_VISION_BACKEND", None)
            with mock.patch.object(api.api_vision, "detect_image", return_value=canned) as m_detect, \
                 mock.patch.object(api, "_live_predict",
                                   side_effect=AssertionError("trained YOLO path must not run")):
                r = client.post("/api/live/detect",
                                content=jpeg(np.zeros((240, 320, 3), np.uint8)),
                                headers={"content-type": "image/jpeg"})
        self.assertEqual(r.status_code, 200, r.text)
        j = r.json()
        self.assertEqual(m_detect.call_count, 1)
        self.assertEqual(j["count"], 1)
        self.assertEqual(j["vision"], {"backend": "api", "provider": "groq", "model": "test-vision-model"})
        self.assertIs(j["validated"], False)

    def test_explicit_api_without_keys_fails_closed(self):
        with mock.patch.dict(os.environ, {"AQUA_VISION_BACKEND": "api"}):
            r = client.post("/api/live/detect",
                            content=jpeg(np.zeros((32, 32, 3), np.uint8)),
                            headers={"content-type": "image/jpeg"})
        self.assertEqual(r.status_code, 503)
        self.assertIn("LLM key", r.json()["error"])

    def test_cloud_failure_degrades_to_200_not_500(self):
        from backend.llm import LlmError
        with mock.patch.dict(os.environ, {**FAKE_KEYS, "AQUA_VISION_BACKEND": "api"}):
            with mock.patch.object(api.api_vision, "detect_image",
                                   side_effect=LlmError("all", "all", "HTTP 429: quota exhausted")), \
                 mock.patch.object(api, "_live_predict",
                                   side_effect=AssertionError("no fallback unless AQUA_LIVE_ALLOW_FALLBACK=1")):
                r = client.post("/api/live/detect",
                                content=jpeg(np.zeros((32, 32, 3), np.uint8)),
                                headers={"content-type": "image/jpeg"})
        self.assertEqual(r.status_code, 200, r.text)
        j = r.json()
        self.assertIs(j["degraded"], True)
        self.assertEqual(j["visionBackend"], "api")
        self.assertIn("429", j["degradedReason"])
        self.assertEqual((j["count"], j["detections"]), (0, []))

    def test_fallback_flag_runs_labeled_local_yolo(self):
        from backend.llm import LlmError
        canned = {"detections": [{"box": [0.1, 0.1, 0.2, 0.2], "confidence": 0.5}],
                  "count": 1, "inferenceMs": 3}
        with mock.patch.dict(os.environ, {**FAKE_KEYS, "AQUA_VISION_BACKEND": "api",
                                          "AQUA_LIVE_ALLOW_FALLBACK": "1"}):
            with mock.patch.object(api.api_vision, "detect_image",
                                   side_effect=LlmError("all", "all", "HTTP 429: quota exhausted")), \
                 mock.patch.object(api, "_live_predict", return_value=dict(canned)) as m_fb:
                r = client.post("/api/live/detect",
                                content=jpeg(np.zeros((32, 32, 3), np.uint8)),
                                headers={"content-type": "image/jpeg"})
        self.assertEqual(r.status_code, 200, r.text)
        j = r.json()
        self.assertEqual(m_fb.call_count, 1)
        self.assertEqual(j["visionBackend"], "yolo-fallback(api-down)")
        self.assertIs(j["degraded"], True)
        self.assertEqual(j["count"], 1)


class ProviderHealth(unittest.TestCase):
    """A blocked (403) or quota-exhausted (429) provider is cooled down, not
    retried on every frame. No network calls; provider fns are mocked."""

    def setUp(self):
        clear_llm_env()
        api.api_vision._UNHEALTHY.clear()
        api.api_vision._TELEMETRY.clear()

    def tearDown(self):
        clear_llm_env()
        api.api_vision._UNHEALTHY.clear()
        api.api_vision._TELEMETRY.clear()

    def test_auth_blocked_groq_skipped_on_next_call(self):
        from backend.llm import LlmError
        with mock.patch.dict(os.environ, FAKE_KEYS):
            with mock.patch.object(api.api_vision, "_call_groq_vision",
                                   side_effect=LlmError("groq", "m", "HTTP 403: error code: 1010")) as m_groq, \
                 mock.patch.object(api.api_vision, "_call_gemini_vision",
                                   return_value=[{"box": [0, 0, 0.1, 0.1], "confidence": 0.9}]) as m_gem:
                out1 = api.api_vision.detect_image(b"fakejpeg")
                self.assertEqual(out1["provider"], "gemini")
                self.assertEqual(m_groq.call_count, 1)
                out2 = api.api_vision.detect_image(b"fakejpeg")
                self.assertEqual(m_groq.call_count, 1)  # still 1: cooling down, not retried
                self.assertEqual(m_gem.call_count, 2)
                self.assertIn("groq:skipped", out2["tried"])

    def test_quota_exhaustion_cools_down_and_hints(self):
        from backend.llm import LlmError
        err429 = LlmError("gemini", "m", "HTTP 429: quota exceeded")
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "AIza_test_fake"}):
            with mock.patch.object(api.api_vision, "_call_gemini_vision", side_effect=err429) as m_gem:
                with self.assertRaises(LlmError) as ctx:
                    api.api_vision.detect_image(b"fakejpeg")
                msg = str(ctx.exception)
                self.assertIn("429", msg)
                self.assertIn("quota", msg.lower())
                n1 = m_gem.call_count
                with self.assertRaises(LlmError):
                    api.api_vision.detect_image(b"fakejpeg")
                self.assertEqual(m_gem.call_count, n1)  # no new call while cooling down

    def test_skip_flag_bypasses_groq_without_calling_and_reports_telemetry(self):
        with mock.patch.dict(os.environ, {**FAKE_KEYS, "AQUA_SKIP_GROQ": "1"}):
            with mock.patch.object(api.api_vision, "_call_groq_vision",
                                   side_effect=AssertionError("must not be called")) as m_groq, \
                 mock.patch.object(api.api_vision, "_call_gemini_vision",
                                   return_value=[]) as m_gem:
                s = api.api_vision.status()
                self.assertIs(s["groq_skipped"], True)
                self.assertIsNone(s["groq_model"])
                out = api.api_vision.detect_image(b"fakejpeg")
                s2 = api.api_vision.status()
        self.assertEqual(m_groq.call_count, 0)
        self.assertEqual(m_gem.call_count, 1)
        self.assertEqual(out["provider"], "gemini")
        self.assertIn("groq:skipped(skip-flag)", out["tried"])
        self.assertEqual(s2["providers"]["gemini"]["calls"], 1)
        self.assertIn("down_until", s2["providers"]["gemini"])
        self.assertIn("skipped", s2["note"])


if __name__ == "__main__":
    unittest.main()
