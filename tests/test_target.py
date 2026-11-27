from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from smart_fan.config import DEFAULTS
from smart_fan.target import Person, StableTargetSelector, choose_target, parse_people
from smart_fan.vision import VisionReader


def person(x1, y1, x2, y2, score=0.9):
    return Person(x1=x1, y1=y1, x2=x2, y2=y2, score=score)


class TestTargetSelection(unittest.TestCase):
    def test_group_count_wins(self):
        one = person(0.10, 0.10, 0.25, 0.80)
        two_a = person(0.62, 0.20, 0.70, 0.70)
        two_b = person(0.72, 0.22, 0.80, 0.75)
        choice = choose_target([one, two_a, two_b], group_distance=0.12)
        self.assertTrue(choice.valid)
        self.assertEqual(choice.group_count, 2)
        self.assertGreater(choice.x, 0.6)
        self.assertEqual(choice.direction, "right")

    def test_nearest_breaks_equal_group_count(self):
        far = person(0.15, 0.15, 0.25, 0.50)
        near = person(0.65, 0.10, 0.83, 0.90)
        choice = choose_target([far, near], group_distance=0.12)
        self.assertEqual(choice.group_count, 1)
        self.assertGreater(choice.x, 0.6)
        self.assertGreater(choice.person.height, 0.5)

    def test_empty(self):
        self.assertFalse(choose_target([]).valid)

    def test_parse_people_ignores_invalid(self):
        people = parse_people([
            {"x1": 0.1, "y1": 0.1, "x2": 0.4, "y2": 0.8},
            {"x1": "broken"},
        ])
        self.assertEqual(len(people), 1)

    def test_large_new_target_waits_for_confirmation(self):
        selector = StableTargetSelector({
            "min_height": 0.18,
            "min_area": 0.01,
            "max_center_jump": 0.22,
            "switch_confirm_sec": 0.8,
        })
        left = person(0.10, 0.20, 0.25, 0.85)
        right = person(0.72, 0.20, 0.92, 0.88)
        first = selector.update([left], 1.0)
        self.assertTrue(first.valid)
        self.assertLess(first.x, 0.3)
        pending = selector.update([right], 1.1)
        self.assertTrue(pending.valid)
        self.assertEqual(pending.reason, "switch_pending")
        self.assertFalse(pending.followable)
        self.assertGreater(pending.x, 0.7)
        pending = selector.update([right], 1.7)
        self.assertTrue(pending.valid)
        self.assertFalse(pending.followable)
        switched = selector.update([right], 1.95)
        self.assertTrue(switched.valid)
        self.assertTrue(switched.followable)
        self.assertGreater(switched.x, 0.7)

    def test_short_detection_gap_uses_cached_target(self):
        selector = StableTargetSelector({
            "min_height": 0.12,
            "min_area": 0.008,
            "detection_hold_sec": 1.0,
        })
        p = person(0.55, 0.20, 0.72, 0.85)
        self.assertTrue(selector.update([p], 1.0).valid)
        cached = selector.update([], 1.5)
        self.assertTrue(cached.valid)
        self.assertEqual(cached.reason, "cached")
        expired = selector.update([], 2.2)
        self.assertFalse(expired.valid)

    def test_small_person_is_not_followed(self):
        selector = StableTargetSelector({
            "min_height": 0.18,
            "min_area": 0.01,
        })
        tiny = person(0.40, 0.40, 0.45, 0.52)
        choice = selector.update([tiny], 1.0)
        self.assertFalse(choice.valid)
        self.assertEqual(choice.reason, "no_size_qualified_person")

    def test_existing_target_keeps_continuity(self):
        selector = StableTargetSelector({
            "min_height": 0.18,
            "min_area": 0.01,
            "max_center_jump": 0.22,
            "switch_confirm_sec": 0.8,
        })
        left = person(0.10, 0.20, 0.25, 0.85)
        selector.update([left], 1.0)
        shifted = person(0.18, 0.20, 0.34, 0.86)
        choice = selector.update([shifted], 1.1)
        self.assertTrue(choice.valid)
        self.assertEqual(choice.reason, "continuity")

    def test_vision_reader_uses_cluster_selection(self):
        cfg = dict(DEFAULTS["vision"])
        reader = VisionReader(cfg)
        payload = {
            "width": 640,
            "height": 480,
            "valid": True,
            "count": 3,
            "frame": 12,
            "people": [
                {"cx": 0.18, "cy": 0.5, "x1": 80, "y1": 100, "x2": 150, "y2": 400, "score": 0.9},
                {"cx": 0.70, "cy": 0.5, "x1": 430, "y1": 100, "x2": 480, "y2": 380, "score": 0.9},
                {"cx": 0.76, "cy": 0.5, "x1": 470, "y1": 100, "x2": 520, "y2": 390, "score": 0.9},
            ],
        }
        reader._consume(json.dumps(payload))
        obs = reader.latest()
        self.assertTrue(obs.valid)
        self.assertEqual(obs.group_count, 2)
        self.assertGreater(obs.x, 0.6)

    def test_vision_reader_reports_pending_switch_as_person_presence(self):
        cfg = dict(DEFAULTS["vision"])
        reader = VisionReader(cfg)
        base = {
            "width": 640,
            "height": 480,
            "valid": True,
            "count": 1,
            "frame": 1,
        }
        reader._consume(json.dumps({
            **base,
            "people": [
                {"x1": 300, "y1": 100, "x2": 380, "y2": 400, "score": 0.9},
            ],
        }))
        reader._consume(json.dumps({
            **base,
            "frame": 2,
            "people": [
                {"x1": 540, "y1": 100, "x2": 620, "y2": 400, "score": 0.9},
            ],
        }))
        obs = reader.latest()
        self.assertTrue(obs.valid)
        self.assertFalse(obs.followable)
        self.assertEqual(obs.selection["reason"], "switch_pending")
        self.assertGreater(obs.x, 0.8)


if __name__ == "__main__":
    unittest.main()
