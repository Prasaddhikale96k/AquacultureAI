import sys
import unittest
from pathlib import Path

import cv2
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import school_movement_metrics as sm  # noqa: E402

VIDEOS = ["tilapia_clear", "fish_tank"]


class Units(unittest.TestCase):
    def test_overlapping_polygons_counted_once(self):
        a = np.array([[0, 0], [50, 0], [50, 50], [0, 50]], float)
        b = a + 25                                    # overlaps a by 25x25
        frac, _ = sm.union_mask_fraction([a, b], (100, 100, 3))
        single, _ = sm.union_mask_fraction([a], (100, 100, 3))
        self.assertGreater(frac, single)
        self.assertLess(frac, 2 * single)
        self.assertEqual(sm.union_mask_fraction([], (100, 100, 3))[0], 0.0)

    def test_fps_not_guessed(self):
        self.assertEqual(sm.validated_fps(30), 30.0)
        for bad in (0, -5, None, float("nan")):
            with self.assertRaises(RuntimeError):
                sm.validated_fps(bad)

    def test_global_shift_estimated_and_compensated(self):
        rng = np.random.default_rng(0)
        img = cv2.GaussianBlur((rng.random((180, 320)) * 255).astype(np.uint8), (0, 0), 3)
        shifted = np.roll(img, (2, 5), axis=(0, 1))   # camera moves: dy=2, dx=5
        dx, dy, resp = sm.camera_shift(img, shifted)
        self.assertAlmostEqual(dx, 5, delta=0.5)
        self.assertAlmostEqual(dy, 2, delta=0.5)
        region = np.ones_like(img)
        region[:, :10] = 0                            # ignore wrapped-around columns
        region[:, -10:] = 0
        region[:5] = 0
        region[-5:] = 0
        pure_camera = sm.motion_energy(img, shifted, dx, dy, region)
        changed = shifted.copy()
        changed[60:120, 100:200] = 255 - changed[60:120, 100:200]   # real content change
        real = sm.motion_energy(img, changed, dx, dy, region)
        self.assertLess(pure_camera, 0.02)
        self.assertGreater(real, 5 * pure_camera)

    def test_summarize_flags_implausible_and_passes_plausible(self):
        n = 50
        ok = pd.DataFrame({"fps": 30.0, "detections": 5, "mask_area_frac": 0.3, "delta_mask_area_frac": 0.01,
                           "camera_shift_frac": 0.0005, "camera_moving": False, "motion_energy": 0.01}, index=range(n))
        self.assertEqual(sm.summarize(ok, expected_frames=n)["reliability_reasons"], [])
        bad = ok.assign(mask_area_frac=0.8)
        self.assertTrue(sm.summarize(bad)["reliability_reasons"])
        self.assertTrue(sm.summarize(ok, expected_frames=n + 5)["reliability_reasons"])


class Outputs(unittest.TestCase):
    def test_csvs_match_video_and_are_well_formed(self):
        for v in VIDEOS:
            d = pd.read_csv(ROOT / f"school_movement_{v}.csv")
            cap = cv2.VideoCapture(str(ROOT / "test_videos" / f"{v}.mp4"))
            fps, n = cap.get(cv2.CAP_PROP_FPS), int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            cap.release()
            self.assertEqual(len(d), n, v)                                  # no missing frames
            self.assertTrue((d["fps"] == fps).all(), v)
            np.testing.assert_allclose(d["time_sec"], d["frame"] / fps)
            self.assertTrue(d["frame"].is_monotonic_increasing and d["frame"].is_unique)
            self.assertTrue(d["mask_area_frac"].between(0, 1).all())
            self.assertTrue((d["detections"] >= 0).all())
            self.assertTrue(d["motion_energy"].dropna().between(0, 1).all())
            # area change only when both this and the previous frame have detections
            had = (d["detections"] > 0) & (d["detections"].shift(1) > 0)
            self.assertTrue(d.loc[~had, "delta_mask_area_frac"].isna().all(), v)
            # no motion energy while the camera is moving
            self.assertTrue(d.loc[d["camera_moving"] == True, "motion_energy"].isna().all(), v)  # noqa: E712

    def test_known_limitations_are_flagged_for_both_test_videos(self):
        for v in VIDEOS:
            self.assertTrue(sm.summarize(pd.read_csv(ROOT / f"school_movement_{v}.csv"))["reliability_reasons"], v)


class Dashboard(unittest.TestCase):
    def test_school_section_present_with_warning_and_tabs_intact(self):
        from streamlit.testing.v1 import AppTest
        at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=90).run()
        self.assertEqual(len(at.exception), 0)
        self.assertEqual(len(at.tabs), 3)
        self.assertIn("Mean detections / frame", [m.label for m in at.metric])
        self.assertTrue(any("Not reliable for this video" in w.value for w in at.warning))
        self.assertIn("Water records", [m.label for m in at.metric])


if __name__ == "__main__":
    unittest.main()
