"""Gap handling, FPS validation and dashboard data-source consistency."""
import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import analyze_video as av  # noqa: E402

FEATURES = ROOT / "fish_movement_features_bytetrack_corrected.csv"
SUMMARY = ROOT / "fish_track_quality_summary_corrected.csv"


class LegacyAnalysis(unittest.TestCase):
    def test_speed_over_consecutive_frames(self):
        d, s = av.movement_step({"frame": 10, "x": 0, "y": 0}, 12, 3, 4, 30.0)
        self.assertAlmostEqual(d, 5.0)
        self.assertAlmostEqual(s, 5.0 / (2 / 30.0))

    def test_gap_of_exactly_3_frames_is_valid_and_4_is_not(self):
        old = {"frame": 10, "x": 0, "y": 0}
        self.assertTrue(np.isfinite(av.movement_step(old, 13, 9, 0, 30.0)[1]))
        d, s = av.movement_step(old, 14, 9, 0, 30.0)
        self.assertTrue(np.isnan(d) and np.isnan(s))

    def test_first_observation_and_non_increasing_frames_have_no_speed(self):
        self.assertTrue(np.isnan(av.movement_step(None, 5, 1, 1, 30.0)[1]))
        self.assertTrue(np.isnan(av.movement_step({"frame": 5, "x": 0, "y": 0}, 5, 1, 1, 30.0)[1]))

    def test_fps_is_validated_not_guessed(self):
        self.assertEqual(av.validated_fps(29.97), 29.97)
        for bad in (0, -1, None, float("nan"), float("inf")):
            with self.assertRaises(RuntimeError):
                av.validated_fps(bad)


class CorrectedOutputs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.f = pd.read_csv(FEATURES)
        cls.s = pd.read_csv(SUMMARY)

    def test_no_speed_across_long_gaps(self):
        long_gap = self.f["frame_gap"] > 3
        self.assertGreater(long_gap.sum(), 0)
        self.assertFalse(self.f.loc[long_gap, "speed_valid"].any())
        self.assertTrue(self.f.loc[long_gap, "speed_px_sec"].isna().all())

    def test_speed_uses_real_fps(self):
        v = self.f[self.f["speed_valid"]]
        np.testing.assert_allclose(v["speed_px_sec"], v["displacement_px"] * self.s["fps_used"].iloc[0] / v["frame_gap"], rtol=1e-6)


class DashboardSource(unittest.TestCase):
    def test_fish_tab_matches_corrected_dataset_and_shows_no_legacy_predictions(self):
        from streamlit.testing.v1 import AppTest
        at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60).run()
        self.assertEqual(len(at.exception), 0)
        s = pd.read_csv(SUMMARY)
        f = pd.read_csv(FEATURES)
        self.assertEqual(s["track_id"].nunique(), f["track_id"].nunique())
        metrics = {m.label: m.value for m in at.metric}
        self.assertEqual(metrics["Fish tracks"], str(len(s)))
        self.assertEqual(metrics["Tracks needing review"], str(int(s["review_tracking"].sum())))
        self.assertNotIn("Provisional predictions", metrics)
        page = " ".join(c.value for c in at.caption)
        self.assertNotIn("predicted_behavior", page)
        for df in at.dataframe:
            self.assertNotIn("predicted_behavior", df.value.columns)


if __name__ == "__main__":
    unittest.main()
