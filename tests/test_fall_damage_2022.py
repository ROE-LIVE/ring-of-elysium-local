"""Экспериментальный урон от падения: кривая по порогам CharacterTable и разбор событий0x2A."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'server/directory'))
from fall_damage_2022 import FallTracker, fall_damage


def point(z, event=0):
    return dict(position=(0, 0, z), bytes=(0, event, 0))


class FallDamageTests(unittest.TestCase):
    def test_curve_anchors(self):
        self.assertEqual(fall_damage(130), 0)          # обычный прыжок JumpHeight130
        self.assertEqual(fall_damage(153), 0)          # ≈ v700
        self.assertEqual(fall_damage(613), 500)        # ≈ v1400 → половина HP
        self.assertEqual(fall_damage(1379), 1000)      # ≈ v2100 → смерть
        self.assertEqual(fall_damage(5000), 1000)

    def test_walk_off_fall_from_session_log(self):
        # Сессия20261027T205950: FALL на z259340, FALL_LAND на258497 (8,4м).
        tracker = FallTracker()
        self.assertIsNone(tracker.observe([point(259340, 4), point(258900)]))
        height, damage = tracker.observe([point(258497, 29), point(258496, 1)])
        self.assertEqual(height, 843)
        self.assertTrue(400 < damage < 1000)

    def test_jump_peak_counts_and_cancel_events_skip_damage(self):
        tracker = FallTracker()
        self.assertEqual(tracker.observe([point(1000, 22), point(1130), point(1000, 4), point(1000, 1)]),
                         (130, 0))
        # Планер (FLY24) посреди падения отменяет подсчёт.
        self.assertIsNone(tracker.observe([point(5000, 4), point(4000, 24), point(1000, 1)]))
        # Лыжный прыжок (43) не считается пешим падением.
        self.assertIsNone(tracker.observe([point(5000, 43), point(1000, 40), point(1000, 1)]))


if __name__ == '__main__':
    unittest.main()
