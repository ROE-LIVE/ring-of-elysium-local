"""Экспериментальный урон от падения: скорость снижения по точкам0x2A, пороги CharacterTable."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'server/directory'))
from fall_damage_2022 import FallTracker, fall_damage, speed_damage, ski_hurt


def point(z, ms, event=0):
    return dict(position=(0, 0, z), value=ms//40, bytes=(0, event, ms % 40))


class FallDamageTests(unittest.TestCase):
    def test_curve_anchors(self):
        self.assertEqual(fall_damage(640), 0)            # 6,4м — без урона (пользователь)
        self.assertTrue(80 < fall_damage(1000) < 130)    # 10м — урон должен быть
        self.assertEqual(speed_damage(2500), 500)
        self.assertEqual(speed_damage(3400), 1000)
        # Видео оригинала: сноуборд с ~30м (≈3100 см/с) оставил18 HP.
        self.assertEqual(speed_damage(3100), 833)
        self.assertEqual(fall_damage(130), 0)          # обычный прыжок JumpHeight130

    def test_downhill_jump_from_session_log_is_harmless(self):
        # 20261027T212632, Дудеска21:29:44.78..45.77: вершина290208, приземление289958 (2,5м),
        # но снижение не быстрее ~575 см/с — бег под гору, а не падение.
        tracker = FallTracker()
        self.assertIsNone(tracker.observe([point(290186, 0, 22), point(290208, 220), point(290205, 320, 4)]))
        height, speed, damage = tracker.observe([point(290096, 540), point(289958, 780), point(289958, 990, 1)])
        self.assertEqual((height, damage), (250, 0))
        self.assertLess(speed, 700)

    def test_real_fall_from_session_log(self):
        # Jogador1 21:32:40.75..42.18: 14м за ~1,4с; последний отрезок ~1790 см/с.
        tracker = FallTracker()
        samples = [(261405, 0, 4), (261295, 200, 0), (261103, 440, 0), (260826, 680, 0),
                   (260432, 930, 0), (260020, 1160, 0), (260019, 1430, 1)]
        height, speed, damage = tracker.observe([point(z, ms, e) for z, ms, e in samples])
        self.assertEqual(height, 1386)
        self.assertTrue(1700 < speed < 1900)
        self.assertTrue(200 < damage < 400)   # 13,9м по высоте

    def test_ski_hurt_request(self):
        self.assertEqual(ski_hurt(bytes.fromhex('00000c1c')), (3100, 833, (0x100b, bytes(4))))
        self.assertEqual(ski_hurt((1000).to_bytes(4, 'big'))[1], 0)
        with self.assertRaises(ValueError):
            ski_hurt(bytes(3))

    def test_cancel_events_skip_damage(self):
        tracker = FallTracker()
        self.assertIsNone(tracker.observe([point(5000, 0, 4), point(4000, 200, 24), point(1000, 400, 1)]))
        self.assertIsNone(tracker.observe([point(5000, 0, 43), point(1000, 200, 40), point(1000, 400, 1)]))


if __name__ == '__main__':
    unittest.main()
