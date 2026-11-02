"""Live sanitize filter + stateful live tracking + /api/live/track route.

Sanitize/tracker tests are pure unit tests (no weights, no network).
Route tests use the real YOLO weights on project test video frames and are
skipped when weights or video are missing. No real API keys are ever set;
key-dependent branches use mock.patch.dict with fake values.
"""
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["AQUA_BACKEND_DATA"] = tempfile.mkdtemp(prefix="aqua_livetrack_test_")

from starlette.testclient import TestClient  # noqa: E402
import backend.main as api  # noqa: E402
from backend import live_track as lt  # noqa: E402

client = TestClient(api.app)
VIDEO = ROOT / "test_videos" / "tilapia_clear.mp4"


def jpeg(img):
    return cv2.imencode(".jpg", img)[1].tobytes()


def box(cx, cy, s=0.1, conf=0.8):
    return {"box": [cx - s / 2, cy - s / 2, cx + s / 2, cy + s / 2], "confidence": conf}


def big_mask_box(conf=0.39):
    # a background-covering detection like the reported defect: huge outline
    return {"box": [0.05, 0.05, 0.95, 0.95], "confidence": conf,
            "outline": [[0.05, 0.05], [0.95, 0.05], [0.95, 0.95], [0.05, 0.95]]}


class Sanitize(unittest.TestCase):
    def test_giant_background_mask_rejected_with_reason(self):
        acc, rej, review = api._sanitize_live_detections(
            [big_mask_box(), box(0.3, 0.3, 0.08)])
        self.assertEqual(len(acc), 1)
        self.assertEqual(len(rej), 1)
        self.assertEqual(rej[0]["reason"], "mask_area_implausible")
        self.assertIn("rejected", review)

    def test_duplicate_masks_keep_higher_confidence(self):
        # Same mask region, different boxes (box IoU < 0.5 so box-dedup passes,
        # mask IoU ~1 so mask-dedup keeps the higher confidence one).
        inner = [[0.2, 0.2], [0.4, 0.2], [0.4, 0.4], [0.2, 0.4]]
        outer = [[0.19, 0.19], [0.41, 0.19], [0.41, 0.41], [0.19, 0.41]]
        lo = {"box": [0.10, 0.19, 0.32, 0.41], "confidence": 0.4, "outline": inner}
        hi = {"box": [0.20, 0.19, 0.42, 0.41], "confidence": 0.9, "outline": outer}
        acc, rej, _ = api._sanitize_live_detections([lo, hi])
        self.assertEqual([d["confidence"] for d in acc], [0.9])
        self.assertEqual(rej[0]["reason"], "duplicate_mask")

    def test_identical_boxes_dedup_before_masks(self):
        # Bit-identical boxes are one detection reported twice: box-dedup fires first.
        lo = {"box": [0.19, 0.19, 0.41, 0.41], "confidence": 0.4}
        hi = {"box": [0.19, 0.19, 0.41, 0.41], "confidence": 0.9}
        acc, rej, _ = api._sanitize_live_detections([lo, hi])
        self.assertEqual([d["confidence"] for d in acc], [0.9])
        self.assertEqual(rej[0]["reason"], "duplicate_box")

    def test_nonfinite_and_sliver_dropped_silently(self):
        acc, rej, review = api._sanitize_live_detections([
            {"box": [float("nan"), 0, 0.1, 0.1], "confidence": 0.9},
            {"box": [0.1, 0.1, 0.101, 0.101], "confidence": 0.9},
            box(0.5, 0.5, 0.1),
        ])
        self.assertEqual(len(acc), 1)
        self.assertEqual(rej, [])
        self.assertIsNone(review)

    def test_empty_input_is_clean(self):
        acc, rej, review = api._sanitize_live_detections([])
        self.assertEqual((acc, rej, review), ([], [], None))

    def test_union_review_flag(self):
        # Two fish-plausible boxes (area 0.30 <= 0.40 single-fish limit) whose
        # mask outlines are large and disjoint: each mask alone is plausible,
        # but their union exceeds the annotated max, so the frame is flagged.
        m1 = {"box": [0.02, 0.02, 0.57, 0.57], "confidence": 0.8,
              "outline": [[0.0, 0.0], [0.7, 0.0], [0.7, 0.7], [0.0, 0.7]]}
        m2 = {"box": [0.33, 0.33, 0.88, 0.88], "confidence": 0.7,
              "outline": [[0.3, 0.3], [1.0, 0.3], [1.0, 1.0], [0.3, 1.0]]}
        acc, rej, review = api._sanitize_live_detections([m1, m2])
        self.assertEqual(len(acc), 2)  # each mask alone is plausible: kept, but flagged
        self.assertIsNotNone(review)
        self.assertIn("needs review", review)

    def test_half_frame_slabs_rejected_as_not_fish(self):
        # Grounded in dataset/tilapia_yolo (test max single-fish area 0.275,
        # train p99.9 0.40): half-frame slabs like the live-model defect
        # (area 0.49) are rejected, never displayed as fish.
        m1 = {"box": [0.0, 0.0, 0.7, 0.7], "confidence": 0.8}
        m2 = {"box": [0.3, 0.3, 1.0, 1.0], "confidence": 0.7}
        acc, rej, review = api._sanitize_live_detections([m1, m2])
        self.assertEqual(len(acc), 0)
        self.assertTrue(all(r["reason"] == "box_area_implausible" for r in rej))
        self.assertIn("rejected", review)

    def test_max_fishes_cap_rejects_excess_detections(self):
        # When more than max_fishes (default 2) are detected, keep the top 2 by confidence
        b1 = {"box": [0.1, 0.1, 0.2, 0.2], "confidence": 0.95}
        b2 = {"box": [0.4, 0.4, 0.5, 0.5], "confidence": 0.85}
        b3 = {"box": [0.7, 0.7, 0.8, 0.8], "confidence": 0.75}
        b4 = {"box": [0.1, 0.7, 0.2, 0.8], "confidence": 0.65}
        acc, rej, _ = api._sanitize_live_detections([b1, b2, b3, b4])
        self.assertEqual(len(acc), 2)
        self.assertEqual([d["confidence"] for d in acc], [0.95, 0.85])
        cap_rejections = [r for r in rej if r["reason"] == "exceeds_max_fish_cap"]
        self.assertEqual(len(cap_rejections), 2)


class Tracker(unittest.TestCase):
    def setUp(self):
        self._saved = dict(lt._sessions)
        lt._sessions.clear()

    def tearDown(self):
        lt._sessions.clear()
        lt._sessions.update(self._saved)

    def img(self, w=320, h=240):
        return np.zeros((h, w, 3), np.uint8)

    def test_identities_persist_and_speed_needs_valid_dt(self):
        img = self.img()
        out1 = lt.update("u1", img, [box(0.3, 0.3)], now=1000.0)
        self.assertEqual([t["id"] for t in out1["tracks"]], [1])
        self.assertEqual(out1["movement"]["valid_speed_intervals"], 0)
        out2 = lt.update("u1", img, [box(0.31, 0.3)], now=1001.0)
        tr = {t["id"]: t for t in out2["tracks"]}
        self.assertIn(1, tr)
        self.assertEqual(tr[1]["observations"], 2)
        self.assertEqual(out2["movement"]["valid_speed_intervals"], 1)
        self.assertGreater(out2["movement"]["mean_speed_px_sec"], 0)

    def test_short_dt_does_not_invent_speed(self):
        img = self.img()
        lt.update("u2", img, [box(0.3, 0.3)], now=2000.0)
        # nearby move (matched) but dt below the floor: no speed, gap counted
        out = lt.update("u2", img, [box(0.31, 0.3)], now=2000.05)
        self.assertEqual(out["movement"]["valid_speed_intervals"], 0)
        self.assertEqual(out["movement"]["gaps_skipped"], 1)

    def test_far_jump_starts_new_track(self):
        img = self.img()
        lt.update("u2b", img, [box(0.3, 0.3)], now=2100.0)
        out = lt.update("u2b", img, [box(0.7, 0.7)], now=2101.0)
        ids = sorted(t["id"] for t in out["tracks"])
        self.assertEqual(ids, [1, 2])  # beyond the match gate: new identity, not a teleported fish
        self.assertEqual(out["movement"]["valid_speed_intervals"], 0)

    def test_long_gap_does_not_invent_speed(self):
        img = self.img()
        lt.update("u3", img, [box(0.3, 0.3)], now=3000.0)
        out = lt.update("u3", img, [box(0.31, 0.3)], now=3005.0)
        self.assertEqual(out["movement"]["valid_speed_intervals"], 0)

    def test_missed_tracks_expire(self):
        img = self.img()
        lt.update("u4", img, [box(0.3, 0.3)], now=4000.0)
        out = lt.update("u4", img, [], now=4001.0)
        self.assertEqual(out["tracks"][0]["observations"], 1)
        for i in range(5):
            out = lt.update("u4", img, [], now=4002.0 + i)
        self.assertEqual(out["tracks"], [])

    def test_sweep_expires_idle_sessions_with_summary(self):
        img = self.img()
        lt.update("u5", img, [box(0.3, 0.3)], now=5000.0)
        lt.update("u5", img, [box(0.3, 0.3)], now=5001.0)
        got = lt.sweep(now=5001.0 + lt.SESSION_TTL_SEC + 1)
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["frames"], 2)
        self.assertNotIn("u5", lt._sessions)

    def test_camera_unknown_without_previous_frame(self):
        out = lt.update("u6", self.img(), [box(0.3, 0.3)], now=6000.0)
        self.assertEqual(out["movement"]["camera"]["state"], "unknown")

    def test_confirm_requires_three_hits_in_window(self):
        img = self.img()
        out = lt.update("c1", img, [box(0.3, 0.3)], now=7000.0)
        self.assertIs(out["tracks"][0]["confirmed"], False)
        lt.update("c1", img, [box(0.301, 0.3)], now=7001.0)
        out = lt.update("c1", img, [box(0.302, 0.3)], now=7002.0)
        self.assertIs(out["tracks"][0]["confirmed"], True)
        self.assertEqual(out["tracks"][0]["box"], [0.252, 0.25, 0.352, 0.35])

    def test_static_track_marked_and_filter_can_be_disabled(self):
        img = self.img()
        with mock.patch.dict(os.environ, {"AQUA_MOTION_GATE": "0", "AQUA_STATIC_FILTER": "1",
                                          "AQUA_STATIC_PX": "20"}):
            for i in range(5):
                out = lt.update("st1", img, [box(0.3, 0.3)], now=8000.0 + i)
        self.assertTrue(out["tracks"][0]["static"])
        self.assertEqual(out["movement"]["static_tracks"], 1)
        self.assertEqual(out["movement"]["active_track_count"], 0)
        with mock.patch.dict(os.environ, {"AQUA_MOTION_GATE": "0", "AQUA_STATIC_FILTER": "0"}):
            out2 = lt.update("st1", img, [box(0.3, 0.3)], now=8006.0)
        self.assertFalse(out2["tracks"][0]["static"])

    def test_misses_unconfirm_but_keep_the_track_in_window(self):
        img = self.img()
        for i in range(3):
            lt.update("c2", img, [box(0.3, 0.3)], now=7100.0 + i)
        for i in range(3):
            out = lt.update("c2", img, [], now=7103.0 + i)
        # <= MAX_MISS misses: the track survives but is no longer confirmed
        self.assertEqual(len(out["tracks"]), 1)
        self.assertIs(out["tracks"][0]["confirmed"], False)


@unittest.skipUnless(Path(api.sm.DETECTOR).is_file() and VIDEO.is_file(), "weights or test video missing")
class LiveTrackRoute(unittest.TestCase):
    def setUp(self):
        for k in ("GROQ_API_KEY", "GEMINI_API_KEY", "AQUA_VISION_BACKEND",
                  "AQUA_SKIP_GROQ", "AQUA_LIVE_ALLOW_FALLBACK", "AQUA_LIVE_CAPTURE",
                  "AQUA_LIVE_ENGINE", "AQUA_WANT_MASKS", "AQUA_CONFIRM_HITS", "AQUA_CONFIRM_WINDOW"):
            os.environ.pop(k, None)
        os.environ["AQUA_LIVE_CAPTURE"] = "0"   # keep dataset/live_captures out of test runs

    def tearDown(self):
        for k in ("GROQ_API_KEY", "GEMINI_API_KEY", "AQUA_VISION_BACKEND",
                  "AQUA_SKIP_GROQ", "AQUA_LIVE_ALLOW_FALLBACK", "AQUA_LIVE_CAPTURE",
                  "AQUA_LIVE_ENGINE", "AQUA_WANT_MASKS", "AQUA_CONFIRM_HITS", "AQUA_CONFIRM_WINDOW"):
            os.environ.pop(k, None)

    def test_track_returns_detections_plus_tracks_and_movement(self):
        cap = cv2.VideoCapture(str(VIDEO))
        ok, img = cap.read()
        cap.release()
        self.assertTrue(ok)
        r = client.post("/api/live/track?session=routetest1", content=jpeg(img),
                        headers={"content-type": "image/jpeg"})
        self.assertEqual(r.status_code, 200, r.text)
        j = r.json()
        self.assertEqual(j["count"], len(j["detections"]))
        self.assertIn("tracks", j)
        self.assertIn("movement", j)
        self.assertIn("session", j)
        self.assertIs(j["validated"], False)
        self.assertIn(j["movement"]["camera"]["state"], ("still", "moving", "unknown"))

    def test_bad_and_missing_session_rejected(self):
        cap = cv2.VideoCapture(str(VIDEO))
        ok, img = cap.read()
        cap.release()
        self.assertTrue(ok)
        jb = jpeg(img)
        self.assertEqual(client.post("/api/live/track?session=../x", content=jb).status_code, 422)
        self.assertEqual(client.post("/api/live/track", content=jb).status_code, 422)
        self.assertEqual(client.post("/api/live/track?session=ok1", content=b"").status_code, 400)

    def test_history_route_serves(self):
        r = client.get("/api/history?limit=50")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIn("records", r.json())


class LiveTrackDegraded(unittest.TestCase):
    """B1: cloud API failure degrades to an honest 200 with an empty frame,
    instead of a 500 that kills the client session loop."""

    def setUp(self):
        for k in ("GROQ_API_KEY", "GEMINI_API_KEY", "AQUA_VISION_BACKEND",
                  "AQUA_SKIP_GROQ", "AQUA_LIVE_ALLOW_FALLBACK", "AQUA_LIVE_CAPTURE",
                  "AQUA_LIVE_ENGINE", "AQUA_WANT_MASKS", "AQUA_CONFIRM_HITS", "AQUA_CONFIRM_WINDOW"):
            os.environ.pop(k, None)
        os.environ["AQUA_LIVE_CAPTURE"] = "0"

    def tearDown(self):
        lt._sessions.pop("deg1", None)
        for k in ("GROQ_API_KEY", "GEMINI_API_KEY", "AQUA_VISION_BACKEND",
                  "AQUA_SKIP_GROQ", "AQUA_LIVE_ALLOW_FALLBACK", "AQUA_LIVE_CAPTURE",
                  "AQUA_LIVE_ENGINE", "AQUA_WANT_MASKS", "AQUA_CONFIRM_HITS", "AQUA_CONFIRM_WINDOW"):
            os.environ.pop(k, None)

    def test_cloud_down_returns_degraded_200_and_keeps_session(self):
        from backend.llm import LlmError
        img = np.zeros((64, 64, 3), np.uint8)
        with mock.patch.dict(os.environ, {"GROQ_API_KEY": "gsk_test_fake", "AQUA_VISION_BACKEND": "api"}):
            with mock.patch.object(api.api_vision, "detect_image",
                                   side_effect=LlmError("all", "all", "HTTP 429: quota exhausted")), \
                 mock.patch.object(api, "_live_predict",
                                   side_effect=AssertionError("no fallback unless AQUA_LIVE_ALLOW_FALLBACK=1")):
                r = client.post("/api/live/track?session=deg1", content=jpeg(img),
                                headers={"content-type": "image/jpeg"})
        self.assertEqual(r.status_code, 200, r.text)
        j = r.json()
        self.assertIs(j["degraded"], True)
        self.assertEqual(j["visionBackend"], "api")
        self.assertIn("429", j["degradedReason"])
        self.assertEqual(j["count"], 0)
        self.assertIn("tracks", j)          # tracker ran with the empty frame
        self.assertIn("deg1", lt._sessions)  # session survived for the next frame


class BehaviorInline(unittest.TestCase):
    def test_invalid_inline_track_rejected_without_keys(self):
        for k in ("GROQ_API_KEY", "GEMINI_API_KEY"):
            os.environ.pop(k, None)
        try:
            r = client.post("/api/behavior", json={"track": {"observations": 0}})
            self.assertEqual(r.status_code, 422)
            r = client.post("/api/behavior", json={"track": {"observations": "many"}})
            self.assertEqual(r.status_code, 422)
            r = client.post("/api/behavior", json={})
            self.assertEqual(r.status_code, 422)
        finally:
            for k in ("GROQ_API_KEY", "GEMINI_API_KEY"):
                os.environ.pop(k, None)

    def test_inline_track_reaches_llm_when_mocked(self):
        with mock.patch.dict(os.environ, {"GROQ_API_KEY": "gsk_test_fake"}):
            with mock.patch.object(api.llm, "observe_behavior",
                                   return_value={"provider": "groq", "model": "m", "observation": "o",
                                                 "fallback_used": False, "tried": [], "generated_at": "t"}) as m:
                r = client.post("/api/behavior", json={"track": {"track_id": 7, "observations": 12,
                                                                 "mean_speed_px_sec": 30.5}})
        self.assertEqual(r.status_code, 200, r.text)
        sent = m.call_args[0][0]
        self.assertEqual(sent["observations"], 12)
        self.assertEqual(sent["source"], "live_session")
        self.assertTrue(r.json()["experimental"])


if __name__ == "__main__":
    unittest.main()
