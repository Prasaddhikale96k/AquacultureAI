"""Run: .venv/Scripts/python.exe -m unittest discover -s tests -v   (from the project root)"""
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import behavior_live as bl  # noqa: E402

TABLE = ROOT / "dataset" / "zebrafish_behavior_prepared" / "behavior_features.csv"


class FeatureContract(unittest.TestCase):
    def test_columns_and_order_match_training_table_and_model(self):
        table_cols = [c for c in pd.read_csv(TABLE, nrows=0).columns if c in bl.EXPECTED_FEATURES]
        self.assertEqual(table_cols, bl.EXPECTED_FEATURES)
        bundle, err = bl.load_model()
        self.assertIsNone(err)
        self.assertEqual(list(bundle["feature_columns"]), bl.EXPECTED_FEATURES)
        self.assertEqual(len(bl.EXPECTED_FEATURES), 20)

    def test_known_samples_reproduce_training_table(self):
        t = pd.read_csv(TABLE)
        for i in (0, len(t) // 2, len(t) - 1):
            a = np.load(ROOT / t.loc[i, "feature_path"]).astype(np.float64)
            got = bl.keypoint_features(a)
            for k in bl.EXPECTED_FEATURES:
                self.assertAlmostEqual(got[k], t.loc[i, k], places=5, msg=f"row {i} {k}")

    def test_centroid_subset_equals_training_values_when_centroid_is_keypoint_mean(self):
        t = pd.read_csv(TABLE)
        a = np.load(ROOT / t.loc[3, "feature_path"]).astype(np.float64)
        part = bl.centroid_features(a.mean(axis=1))
        self.assertEqual(sorted(part), sorted(bl.CENTROID_FEATURES))
        for k, v in part.items():
            self.assertAlmostEqual(v, t.loc[3, k], places=5, msg=k)
        self.assertEqual(len(bl.KEYPOINT_ONLY_FEATURES), 12)


class Classification(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle, err = bl.load_model()
        assert err is None, err
        cls.t = pd.read_csv(TABLE)

    def full_feats(self, i=0):
        return {k: float(self.t.loc[i, k]) for k in bl.EXPECTED_FEATURES}

    def test_complete_valid_window_predicts_with_probabilities(self):
        r = bl.classify_features(self.bundle, self.full_feats())
        self.assertEqual(r["status"], "ok")
        self.assertIn(r["prediction"], self.bundle["classes"])
        self.assertAlmostEqual(sum(r["probabilities"].values()), 1.0, places=6)

    def test_incomplete_window_no_prediction(self):
        r = bl.classify_features(self.bundle, self.full_feats(), n_obs=59)
        self.assertEqual((r["status"], r["prediction"]), ("insufficient_window", None))

    def test_missing_features_no_prediction_and_no_imputation(self):
        f = self.full_feats()
        del f["spread_mean"]
        r = bl.classify_features(self.bundle, f)
        self.assertEqual((r["status"], r["prediction"]), ("features_incompatible", None))
        self.assertEqual(r["missing_features"], ["spread_mean"])

    def test_nan_features_rejected(self):
        f = self.full_feats()
        f["path_length"] = float("nan")
        self.assertEqual(bl.classify_features(self.bundle, f)["status"], "invalid_features")

    def test_live_centroid_window_is_refused_not_guessed(self):
        xy = np.cumsum(np.random.default_rng(1).normal(size=(60, 2)), axis=0)
        r = bl.classify_centroid_window(self.bundle, xy)
        self.assertEqual((r["status"], r["prediction"], r["probabilities"]), ("features_incompatible", None, None))
        self.assertEqual(sorted(r["missing_features"]), sorted(bl.KEYPOINT_ONLY_FEATURES))
        self.assertEqual(sorted(r["partial_features"]), sorted(bl.CENTROID_FEATURES))

    def test_live_incomplete_centroid_window(self):
        r = bl.classify_centroid_window(self.bundle, np.zeros((10, 2)))
        self.assertEqual(r["status"], "insufficient_window")

    def test_no_model(self):
        r = bl.classify_features(None, {})
        self.assertEqual(r["status"], "model_unavailable")


class Windows(unittest.TestCase):
    def test_gap_resets_window_and_tracks_do_not_mix(self):
        b = bl.TrackWindowBuffer()
        for f in range(0, 30):
            b.update(1, f, f, 0)
            b.update(2, f, 0, f)
        self.assertEqual((b.n_obs(1), b.n_obs(2)), (30, 30))
        b.update(1, 32, 99, 99)                    # frames 30,31 missing -> restart for ID 1 only
        self.assertEqual((b.n_obs(1), b.n_obs(2), b.resets.get(1)), (1, 30, 1))
        self.assertTrue((b.window_xy(2)[:, 0] == 0).all())
        for f in range(30, 95):
            b.update(2, f, 0, f)
        self.assertTrue(b.is_complete(2))
        self.assertEqual(b.window_xy(2).shape, (60, 2))
        self.assertEqual(b.n_obs(999), 0)           # new/unknown track ID

    def test_duplicate_or_backwards_frame_resets(self):
        b = bl.TrackWindowBuffer()
        for f in range(5):
            b.update(7, f, 0, 0)
        b.update(7, 4, 0, 0)
        self.assertEqual(b.n_obs(7), 1)


class ModelLoading(unittest.TestCase):
    def test_missing_file(self):
        self.assertIsNotNone(bl.load_model(ROOT / "no_such_model.joblib")[1])

    def test_corrupt_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "bad.joblib"
            p.write_bytes(b"not a model")
            b, err = bl.load_model(p)
        self.assertIsNone(b)
        self.assertIn("could not be loaded", err)

    def test_wrong_structure_and_feature_mismatch(self):
        import joblib
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "w.joblib"
            joblib.dump({"foo": 1}, p)
            self.assertIn("unexpected structure", bl.load_model(p)[1])
            real, _ = bl.load_model()
            bad = dict(real, feature_columns=list(reversed(real["feature_columns"])))
            joblib.dump(bad, p)
            self.assertIn("do not match", bl.load_model(p)[1])


if __name__ == "__main__":
    unittest.main()
