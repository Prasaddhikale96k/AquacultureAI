"""G1 geometry filter + safety greps (farmer finalization, F1/G1)."""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["AQUA_SCHEDULER"] = "0"

import backend.main as api  # noqa: E402


class JunkGeometry(unittest.TestCase):
    def test_shell_is_rejected_as_vertical_blob(self):
        # Measured fish_tank box: aspect 0.68, area 0.099 (both rotations).
        self.assertEqual(api._junk_geometry([0.6425, 0.5725, 0.9015, 0.9535]), "vertical_blob")

    def test_fish_like_boxes_survive(self):
        # Real tilapia boxes measured in eval_ab/conf_floor.
        for b in ([0.0005, 0.4345, 0.7105, 0.6425], [0.4915, 0.5435, 0.9365, 0.6575],
                  [0.2015, 0.5655, 0.7985, 0.7215], [0.0135, 0.5145, 0.7075, 0.6665]):
            self.assertIsNone(api._junk_geometry(b), b)

    def test_full_frame_and_sliver_rejected(self):
        self.assertEqual(api._junk_geometry([0.0, 0.0, 1.0, 1.0]), "full_frame_blob")
        self.assertEqual(api._junk_geometry([0.0, 0.5, 0.9, 0.51]), "sliver")
        self.assertEqual(api._junk_geometry([0.2, 0.3, 0.2, 0.4]), "degenerate")

    def test_flag_is_off_by_default_and_env_rollback(self):
        with mock.patch.dict(os.environ, {"AQUA_JUNK_GEOM": "0"}):
            self.assertFalse(api.junk_geom_on())
        with mock.patch.dict(os.environ, {"AQUA_JUNK_GEOM": "1"}):
            self.assertTrue(api.junk_geom_on())


class SafetyGreps(unittest.TestCase):
    def test_no_hardware_control_and_no_telegram(self):
        patterns = ["telegram", "rpi.gpio", "gpiozero", "paho.mqtt", "digitalwrite",
                    "turn_on_pump", "turn_off_pump", "relay_on", "relay_off", "gpio.output"]
        roots = [ROOT / "backend", ROOT / "frontend" / "src"]
        hits = []
        for root in roots:
            for p in root.rglob("*"):
                if p.suffix not in (".py", ".ts", ".tsx", ".js") or not p.is_file():
                    continue
                text = p.read_text(encoding="utf-8", errors="ignore").lower()
                hits += [(str(p), pat) for pat in patterns if pat in text]
        self.assertEqual(hits, [], f"hardware-control or banned-provider references: {hits}")


if __name__ == "__main__":
    unittest.main()
