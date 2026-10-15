"""Календарь дропа/эвакуации обязан сохранять фазу относительно зон."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from match_pacing_2022 import paced_match


class MatchPacingTests(unittest.TestCase):
    def test_scene_and_world_share_scale_but_spawn_and_damage_do_not(self):
        world = dict(hazard=dict(damage=50), region_grid=dict(damage=150, interval_seconds=1),
                     stages=[dict(at_seconds=18.3, duration=42, elapsed_seconds=0)],
                     warnings=[dict(at_seconds=6.3, duration=12)])
        scene = [dict(after_selection=True, after_selection_delay_seconds=t) for t in (0, 3, 60, 115.8, 127.8, 220)]
        w, s = paced_match(world, scene, 3)
        self.assertEqual([x['after_selection_delay_seconds'] for x in s], [0, 3, 180, 347.4, 383.4, 660])
        self.assertEqual(w['stages'][0]['duration'], 126)
        self.assertAlmostEqual(w['stages'][0]['at_seconds'], 54.9)
        self.assertEqual(w['warnings'][0]['duration'], 36)
        self.assertEqual(w['region_grid'], world['region_grid'])
        self.assertFalse(w['hazard']['enabled'])
        self.assertNotIn('enabled', world['hazard'])
        self.assertEqual(scene[2]['after_selection_delay_seconds'], 60)
        self.assertTrue(paced_match(world, scene, diagnostic_hazard=True)[0]['hazard']['enabled'])

    def test_invalid_pacing_rejected_before_mutation(self):
        for value in (True, 0, 11, 1.5, '3'):
            with self.assertRaises(ValueError):
                paced_match({}, [], value)
        with self.assertRaises(ValueError):
            paced_match({}, [], 1, 1)
