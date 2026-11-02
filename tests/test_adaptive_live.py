"""Adaptive live detection (T2/T3) + motion gate (T4) contract tests.

Uses the real YOLO weights on project test-video frames where weights are
needed (skipped otherwise); motion-gate and edge tests are pure unit tests
(no weights, no network, no keys).
"""
import logging
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
os.environ["AQUA_BACKEND_DATA"] = tempfile.mkdtemp(prefix="aqua_adaptive_test_")

from backend.live_detect import predict_tiled as pt  # noqa: E402
from backend import live_track as lt  # noqa: E402

VIDEO = ROOT / "test_videos" / "tilapia_clear.mp4"
WEIGHTS = ROOT / "runs" / "segment" / "runs" / "aquaculture" / "tilapia_seg" / "weights" / "best.pt"


def frame_at(video, idx):
    cap = cv2.VideoCapture(str(video))
    cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
    ok, img = cap.read()
    cap.release()
    assert ok, f"could not read frame {idx} of {video}"
    return img


@unittest.skipUnless(WEIGHTS.is_file() and VIDEO.is_file(), "weights or test video missing")
class DetectAdaptive(unittest.TestCase):
    def test_returns_dicts_with_required_keys_and_logs_latency(self):
        from ultralytics import YOLO
        import torch
        model = YOLO(str(WEIGHTS))
        dev = 0 if torch.cuda.is_available() else "cpu"
        with self.assertLogs("aqua.live_detect", level="INFO") as logs:
            dets = pt.detect_adaptive(model, frame_at(VIDEO, 0), conf=0.20,
                                      trigger=0.25, mode="auto", device=dev)
        self.assertIsInstance(dets, list)
        for d in dets:
            self.assertTrue({"box", "conf", "area_frac", "source"} <= set(d))
            self.assertIn(d["source"], ("single", "tile"))
        self.assertTrue(any("detect_adaptive" in m and "ms=" in m
                            for m in logs.output))


class AdaptiveSanitize(unittest.TestCase):
    def test_flat_slab_dropped(self):
        flat = np.full((240, 320), 120, np.uint8)
        self.assertFalse(pt.adaptive_sanitize([0.1, 0.1, 0.9, 0.9], flat, 0.10))

    def test_textured_region_kept(self):
        yy, xx = np.indices((240, 320))
        checker = (((xx // 8) + (yy // 8)) % 2 * 255).astype(np.uint8)
        self.assertTrue(pt.adaptive_sanitize([0.1, 0.1, 0.9, 0.9], checker, 0.10))


class MotionGate(unittest.TestCase):
    def setUp(self):
        self._saved = dict(lt._sessions)
        lt._sessions.clear()
        os.environ.pop("AQUA_MOTION_GATE", None)

    def tearDown(self):
        lt._sessions.clear()
        lt._sessions.update(self._saved)
        os.environ.pop("AQUA_MOTION_GATE", None)

    def img(self, w=320, h=240):
        return np.zeros((h, w, 3), np.uint8)

    def test_static_detections_gated_after_history_builds(self):
        det = [{"box": [0.25, 0.25, 0.40, 0.40], "confidence": 0.9}]
        last = None
        for i in range(6):
            last = lt.update("static1", self.img(), [dict(d) for d in det],
                             now=1000.0 + i)
        self.assertGreater(last["movement"]["motion_gated"], 0)
        # track froze once the gate kicked in (3 obs while history built up)
        self.assertEqual(last["tracks"][0]["observations"], 3)

    def test_gate_off_passes_static(self):
        with mock.patch.dict(os.environ, {"AQUA_MOTION_GATE": "0"}):
            det = [{"box": [0.25, 0.25, 0.40, 0.40], "confidence": 0.9}]
            last = None
            for i in range(6):
                last = lt.update("static2", self.img(), [dict(d) for d in det],
                                 now=2000.0 + i)
        self.assertEqual(last["movement"]["motion_gated"], 0)
        self.assertEqual(last["tracks"][0]["observations"], 6)

    def test_moving_detection_passes(self):
        last = None
        for i in range(6):
            img = np.zeros((240, 320, 3), np.uint8)
            x = 20 + i * 30
            img[100:130, x:x + 30] = 255
            cx = (x + 15) / 320
            det = [{"box": [cx - 0.075, 0.40, cx + 0.075, 0.55],
                    "confidence": 0.9}]
            last = lt.update("moving1", img, det, now=3000.0 + i)
        self.assertTrue(last["tracks"])
        self.assertGreaterEqual(last["tracks"][0]["observations"], 4)


if __name__ == "__main__":
    unittest.main()
