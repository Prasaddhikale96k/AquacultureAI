"""Live single-frame detection endpoint. Uses the real weights on one frame of a project test video (CPU is fine)."""
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
os.environ["AQUA_BACKEND_DATA"] = tempfile.mkdtemp(prefix="aqua_live_test_")

from starlette.testclient import TestClient  # noqa: E402
import backend.main as api  # noqa: E402

client = TestClient(api.app)
VIDEO = ROOT / "test_videos" / "tilapia_clear.mp4"


def jpeg(img):
    return cv2.imencode(".jpg", img)[1].tobytes()


_LLM_ENV_VARS = ("GROQ_API_KEY", "GEMINI_API_KEY", "AQUA_VISION_BACKEND",
                 "AQUA_SKIP_GROQ", "AQUA_LIVE_ALLOW_FALLBACK",
                 "AQUA_LIVE_ENGINE", "AQUA_WANT_MASKS", "AQUA_CONFIRM_HITS", "AQUA_CONFIRM_WINDOW")


def _clear_llm_env():
    """Snapshot ambient LLM/backend-selection vars so yolo-path tests are
    hermetic (a real user .env must not flip backend selection under tests)."""
    return {k: os.environ.pop(k, None) for k in _LLM_ENV_VARS}


def _restore_llm_env(saved):
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


class LiveEngineSelection(unittest.TestCase):
    """AQUA_LIVE_ENGINE parsing (Phase 2): default friend; an unknown value must
    never select an engine (falls back to friend); explicit values pass through."""

    def setUp(self):
        self._saved = _clear_llm_env()

    def tearDown(self):
        _restore_llm_env(self._saved)

    def test_default_unknown_and_explicit_values(self):
        self.assertEqual(api.live_engine(), "friend")          # unset -> friend
        for val, want in [("WORLD", "world"), (" world ", "world"),
                          ("florence", "florence"), ("ollama", "friend"),
                          ("", "friend"), ("bogus", "friend")]:
            os.environ["AQUA_LIVE_ENGINE"] = val
            self.assertEqual(api.live_engine(), want, val)
        os.environ.pop("AQUA_LIVE_ENGINE")
        self.assertEqual(api.live_engine(), "friend")


@unittest.skipUnless(Path(api.sm.DETECTOR).is_file() and VIDEO.is_file(), "weights or test video missing")
class LiveDetect(unittest.TestCase):
    def setUp(self):
        self._llm_env = _clear_llm_env()

    def tearDown(self):
        _restore_llm_env(self._llm_env)

    def test_real_frame_returns_well_formed_frame_level_result(self):
        cap = cv2.VideoCapture(str(VIDEO))
        ok, img = cap.read()
        cap.release()
        self.assertTrue(ok)
        r = client.post("/api/live/detect", content=jpeg(img), headers={"content-type": "image/jpeg"})
        self.assertEqual(r.status_code, 200, r.text)
        j = r.json()
        self.assertEqual(j["count"], len(j["detections"]))
        self.assertIs(j["validated"], False)
        self.assertNotIn("uniqueFish", j)
        self.assertGreater(j["inferenceMs"], 0)
        for d in j["detections"]:
            x1, y1, x2, y2 = d["box"]
            self.assertTrue(0 <= x1 <= x2 <= 1 and 0 <= y1 <= y2 <= 1)
            self.assertTrue(0 < d["confidence"] <= 1)
            self.assertLessEqual(len(d.get("outline", [])), 80)

    def test_blank_frame_is_not_given_invented_detections(self):
        r = client.post("/api/live/detect", content=jpeg(np.zeros((240, 320, 3), np.uint8)))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["count"], len(r.json()["detections"]))

    def test_bad_input_is_rejected(self):
        self.assertEqual(client.post("/api/live/detect", content=b"").status_code, 400)
        self.assertEqual(client.post("/api/live/detect", content=b"not an image").status_code, 415)
        self.assertEqual(client.post("/api/live/detect", content=b"x" * (api.MAX_FRAME_BYTES + 1)).status_code, 413)
        self.assertEqual(client.get("/api/live/detect").status_code, 405)

    def test_missing_weights_gives_503_and_no_path_leak(self):
        with mock.patch.object(api.sm, "DETECTOR", str(ROOT / "nope.pt")):
            r = client.post("/api/live/detect", content=b"abc")
        self.assertEqual(r.status_code, 503)
        self.assertNotIn(str(ROOT), r.text)

    def test_model_failure_is_reported_without_paths(self):
        with mock.patch.object(api, "_live_predict", side_effect=RuntimeError(f"boom {ROOT}\\x.pt")):
            r = client.post("/api/live/detect", content=jpeg(np.zeros((32, 32, 3), np.uint8)))
        self.assertEqual(r.status_code, 500)
        self.assertNotIn(str(ROOT), r.text)


if __name__ == "__main__":
    unittest.main()
