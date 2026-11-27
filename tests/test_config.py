from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from smart_fan.config import load_config  # noqa: E402


class TestSampleConfig(unittest.TestCase):
    def test_camera_settings_use_the_active_vision_section(self):
        raw = json.loads((ROOT / "config" / "smart_fan.json").read_text(encoding="utf-8"))
        cfg = load_config(ROOT / "config" / "smart_fan.json")

        self.assertNotIn("camera", raw)
        self.assertEqual(cfg["vision"]["device"], raw["vision"]["device"])
        self.assertEqual(cfg["vision"]["width"], raw["vision"]["width"])
        self.assertEqual(cfg["vision"]["height"], raw["vision"]["height"])
        self.assertEqual(cfg["vision"]["fps"], raw["vision"]["fps"])
        self.assertEqual(cfg["vision"]["infer_fps"], raw["vision"]["infer_fps"])


if __name__ == "__main__":
    unittest.main()
