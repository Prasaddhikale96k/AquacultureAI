"""DO physics model unit tests (Track II D1).

All values are synthetic model inputs, not farm measurements.
"""
import math
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.services import do_model  # noqa: E402


class Saturation(unittest.TestCase):
    def test_benson_krause_anchors_at_sea_level(self):
        anchors = {0: 14.62, 10: 11.28, 20: 9.09, 25: 8.24, 28: 7.81, 30: 7.56, 35: 6.93}
        for temp, expected in anchors.items():
            got = do_model.do_saturation(temp, alt_m=0)
            self.assertAlmostEqual(got, expected, delta=0.05, msg=f"{temp} C")

    def test_altitude_310m_reduces_saturation_by_about_3_7_percent(self):
        sea = do_model.do_saturation(28, alt_m=0)
        alt = do_model.do_saturation(28, alt_m=310)
        self.assertAlmostEqual((sea - alt) / sea, 0.0367, delta=0.003)

    def test_temperature_outside_validity_is_clamped_and_finite(self):
        self.assertTrue(math.isfinite(do_model.do_saturation(-5, alt_m=0)))
        self.assertTrue(math.isfinite(do_model.do_saturation(55, alt_m=0)))


class Estimate(unittest.TestCase):
    def test_dawn_minimum_and_turbidity_amplitude(self):
        dawn = do_model.estimate_do(28, 10, 7.8, 5.5, 0.0)
        dusk = do_model.estimate_do(28, 10, 7.8, 17.3, 0.0)
        self.assertLess(dawn["s_factor"], dusk["s_factor"])
        self.assertAlmostEqual(do_model.estimate_do(28, 0, 7.8, 12, 0.0)["components"]["amp"], 0.12, places=4)
        self.assertAlmostEqual(do_model.estimate_do(28, 60, 7.8, 12, 0.0)["components"]["amp"], 0.32, places=4)

    def test_ph_correction_clamps(self):
        low = do_model.estimate_do(28, 10, 0.0, 12, 0.0)["components"]["s_ph"]
        high = do_model.estimate_do(28, 10, 14.0, 12, 0.0)["components"]["s_ph"]
        self.assertAlmostEqual(low, -0.12, places=4)
        self.assertAlmostEqual(high, 0.08, places=4)

    def test_s_total_and_do_clamps_and_no_nan_on_edges(self):
        edge = do_model.estimate_do(0.1, 500, None, 0.0, 0.0)
        for key in ("do_mgl", "band_low", "band_high", "percent_saturation", "do_sat_mgl", "s_factor"):
            self.assertIsNotNone(edge[key])
            self.assertTrue(math.isfinite(edge[key]))
        self.assertGreaterEqual(edge["s_factor"], do_model.S_MIN)
        self.assertLessEqual(edge["s_factor"], do_model.S_MAX)
        self.assertTrue(0 <= edge["do_mgl"] <= 20)
        forced = do_model.estimate_do(30, 60, 14.0, 5.5, 0.0, cal={"a": 100.0, "b": 100.0, "n": 20})
        self.assertEqual(forced["do_mgl"], 20.0)

    def test_risk_band_boundaries(self):
        self.assertEqual(do_model.risk_band(5.0), "safe")
        self.assertEqual(do_model.risk_band(4.9), "watch")
        self.assertEqual(do_model.risk_band(3.5), "watch")
        self.assertEqual(do_model.risk_band(3.4), "risk")
        self.assertEqual(do_model.risk_band(2.0), "risk")
        self.assertEqual(do_model.risk_band(1.9), "critical")

    def test_missing_ph_defaults_to_neutral(self):
        est = do_model.estimate_do(28, 10, None, 12, 0.0)
        self.assertEqual(est["components"]["ph_used"], 7.8)
        self.assertTrue(est["components"]["ph_defaulted"])
        self.assertEqual(est["confidence"], "low")

    def test_s_feed_default_zero_and_applied(self):
        plain = do_model.estimate_do(30, 60, 7.8, 5.5, 0.0)
        fed = do_model.estimate_do(30, 60, 7.8, 5.5, 0.0, s_feed=-0.08)
        self.assertEqual(plain["components"]["s_feed"], 0.0)
        self.assertAlmostEqual(fed["components"]["s_feed"], -0.08, places=4)
        self.assertAlmostEqual(plain["s_factor"] - fed["s_factor"], 0.08, places=2)

    def test_calibration_sets_medium_confidence(self):
        est = do_model.estimate_do(28, 10, 7.8, 12, 0.0, cal={"a": 1.1, "b": 0.2, "n": 20})
        self.assertEqual(est["confidence"], "medium")
        self.assertTrue(est["label_provisional"])
        self.assertTrue(est["components"]["cal_applied"])

    def test_missing_required_inputs_do_not_raise(self):
        self.assertEqual(do_model.estimate_do(None, 10, 7.8, 12, 0.0)["status"], "invalid_inputs")
        self.assertEqual(do_model.estimate_do(28, None, 7.8, 12, 0.0)["status"], "invalid_inputs")


if __name__ == "__main__":
    unittest.main()
