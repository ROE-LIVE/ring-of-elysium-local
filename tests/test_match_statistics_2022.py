"""Учёт принятых действий, переноса позиции и терминального состояния."""
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).parents[1]/'server/directory'))
from match_statistics_2022 import MatchStatistics


class MatchStatisticsTests(unittest.TestCase):
    def test_initial_spawn_and_server_transfer_do_not_count_as_walking(self):
        stats = MatchStatistics()
        stats.reset_anchor((1000, 2000, 3000))
        stats.begin(10)
        stats.move([(1003, 2004, 3000), (1003, 2004, 3012)])
        stats.reset_anchor((900000, 800000, 700000))
        stats.move([(900000, 800000, 700005)])
        self.assertEqual(stats.snapshot(20)['distance_cm'], 22)

    def test_rejected_hits_and_duplicate_pickups_do_not_inflate_statistics(self):
        stats = MatchStatistics()
        stats.begin(10)
        stats.observe(dict(action='hit_rejected', damage=1000, hp=0, target='A'))
        stats.observe(dict(action='hit_damage', damage=200, hp=100, target='A'))
        stats.observe(dict(action='hit_damage', damage=100, hp=0, target='A'))
        stats.observe(dict(action='area_damage', damage=50, hp=0, target='A'))
        stats.observe(dict(action='duplicate_pickup', quantity=100))
        stats.observe(dict(action='pickup', quantity=2))
        stats.observe(dict(action='parcel_pickup', quantity=0))
        stats.observe(dict(action='parcel_pickup', quantity=20))
        report = stats.snapshot(20)
        self.assertEqual((report['kills'], report['damage_raw']), (1, 350))
        self.assertEqual((report['loot_actions'], report['loot_quantity']), (2, 22))

    def test_terminal_death_is_not_replaced_by_late_rescue_or_actions(self):
        stats = MatchStatistics()
        stats.begin(10)
        first = stats.finish(15, rescued=False)
        stats.move([(1, 2, 3)])
        stats.observe(dict(action='pickup', quantity=1))
        self.assertEqual(stats.finish(100, rescued=True), first)
        self.assertEqual((first['survival_seconds'], first['rescued']), (5, 0))

    def test_begin_is_idempotent_for_handoff(self):
        stats = MatchStatistics()
        stats.begin(10)
        stats.begin(100)
        self.assertEqual(stats.finish(120, True)['survival_seconds'], 110)


if __name__ == '__main__':
    unittest.main()
