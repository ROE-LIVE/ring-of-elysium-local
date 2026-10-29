"""Кислород под водой и удушье: скорости buff3/buff4, формат0x1069, вызов из конечной точки."""
import struct
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'server/directory'))
import drowning_2022 as drowning
from drowning_2022 import BreathTracker, encode_power
from game_endpoint_probe_2022 import Endpoint
from world_probe_2022 import encode_health


def point(z, event=0):
    return dict(position=(0, 0, z), bytes=(0, event, 0), value=0)


class BreathTrackerTests(unittest.TestCase):
    def dive(self, surface=36670, bottom=36148):
        # 20261029T021955: поверхность ~36670, нырок до36148.
        tracker = BreathTracker()
        tracker.observe([point(surface, 23), point(surface, 7)])
        self.assertTrue(tracker.in_water)
        self.assertFalse(tracker.underwater)
        tracker.observe([point(surface-60, 6), point(bottom)])
        self.assertTrue(tracker.underwater)
        return tracker

    def test_surface_swim_is_not_underwater(self):
        # Та же сессия: FLOAT7 на37363, SWIN6 у поверхности до37345.
        tracker = BreathTracker()
        tracker.observe([point(37363, 7), point(37345, 6), point(37358)])
        self.assertFalse(tracker.underwater)
        self.assertIsNone(tracker.poll(0))

    def test_oxygen_drains_then_asphyxia_damages_forty_per_second(self):
        tracker = self.dive()
        oxygen, damage, statuses = tracker.poll(0)
        self.assertEqual((oxygen, damage, statuses), (100, 0, [(0x2b, drowning.ST_SWIM_BREATH)]))
        self.assertEqual(tracker.poll(1)[:2], (97, 0))           # buff3: −3 в секунду
        total = 0
        for second in range(2, 34):
            total += tracker.poll(second)[1]
        self.assertEqual((tracker.oxygen, total), (1, 0))
        oxygen, damage, statuses = tracker.poll(34)
        self.assertEqual((oxygen, damage, statuses), (0, 0, [(0x2b, drowning.ST_ASPHYXIA)]))
        self.assertEqual(tracker.poll(35)[1:], (40, []))           # buff4: −40 HP в секунду
        self.assertEqual(tracker.poll(37.5)[1], 80)                # пропущенные heartbeat

    def test_surfacing_leaves_statuses_and_recovers(self):
        tracker = self.dive()
        for second in range(0, 36):
            tracker.poll(second)
        tracker.observe([point(36670, 7)])
        oxygen, damage, statuses = tracker.poll(36)
        self.assertEqual(statuses, [(0x2c, drowning.ST_SWIM_BREATH), (0x2c, drowning.ST_ASPHYXIA)])
        self.assertEqual((oxygen, damage), (20, 0))               # над водой: +20 в секунду
        self.assertEqual(tracker.poll(37)[:2], (40, 0))
        for second in range(38, 41):
            tracker.poll(second)
        self.assertEqual(tracker.oxygen, 100)
        self.assertIsNone(tracker.poll(50))

    def test_leaving_water_by_other_event_resets_surface(self):
        tracker = self.dive()
        tracker.observe([point(36148, 1)])                         # STAND_UP: вышел из воды
        self.assertFalse(tracker.in_water)
        tracker.observe([point(30000, 6)])                         # новый водоём: своя поверхность
        self.assertFalse(tracker.underwater)

    def test_reset_on_death_leaves_active_statuses(self):
        tracker = self.dive()
        tracker.poll(0)
        self.assertEqual(tracker.reset(), [(0x2c, drowning.ST_SWIM_BREATH)])
        self.assertEqual((tracker.oxygen, tracker.in_water), (100, False))

    def test_power_update_layout_matches_health(self):
        self.assertEqual(encode_power(42, 0, [(0, 700, 1000)]), encode_health(42, 700))
        body = encode_power(42, 7, [(14, 97, 100)])
        self.assertEqual(struct.unpack('>QBBBII', body), (42, 7, 1, 14, 97, 100))
        with self.assertRaises(ValueError):
            encode_power(42, 0, [])


class EndpointDrowningTests(unittest.TestCase):
    def endpoint(self):
        e = Endpoint.__new__(Endpoint)
        e.records, e.out = [], []
        e.peer_avatars = None
        e.capture = SimpleNamespace(record=lambda kind, **kw: e.records.append((kind, kw)))
        e.send_application_batch = lambda d, remote, st, packets: e.out.extend(packets)
        e.emit_own_death_inventory = lambda *args: None
        e.cancel_dead_actions = lambda *args: None
        return e

    def world(self):
        world = SimpleNamespace(dead=False, hp=1000)
        def apply_damage(damage, source):
            world.hp -= damage
            return [(0x1069, encode_health(42, world.hp))], dict(damage=damage, hp=world.hp)
        world.apply_damage = apply_damage
        return world

    def test_heartbeat_keeps_damaging_still_diver_with_drown_reason(self):
        e, world = self.endpoint(), self.world()
        state = dict(actor_uid=42, world=world)
        clock = mock.patch('game_endpoint_probe_2022.time.monotonic')
        with clock as now:
            now.return_value = 0
            e.apply_drowning(None, None, state, dict(points=[point(36670, 7), point(36148, 6)]))
            self.assertIn((0x2b, struct.pack('>QI', 42, 67)), e.out)
            self.assertEqual(e.out[-1], (0x1069, encode_power(42, 0x07, [(14, 100, 100)])))
            for second in range(1, 36):                           # parado: só heartbeat1f49
                now.return_value = second
                e.apply_drowning(None, None, state)
        self.assertEqual(world.hp, 960)
        self.assertEqual(e.out[-1], (0x1069, struct.pack('>QBBBII', 42, 7, 1, 0, 960, 1000)))
        hit = [kw for kind, kw in e.records if kw.get('action') == 'drowning_damage']
        self.assertEqual((hit[-1]['damage'], hit[-1]['hp'], hit[-1]['depth_cm']), (40, 960, 522))

    def test_seated_vehicle_is_out_of_water_and_death_clears_status(self):
        e, world = self.endpoint(), self.world()
        state = dict(actor_uid=42, world=world)
        with mock.patch('game_endpoint_probe_2022.time.monotonic', return_value=0):
            e.apply_drowning(None, None, state, dict(points=[point(36670, 7), point(36148, 6)]))
            e.out.clear()
            world.dead = True
            e.apply_drowning(None, None, state)
            self.assertEqual(e.out, [(0x2c, struct.pack('>QI', 42, 67))])
            e.out.clear()
            world.dead = False
            state['vehicles'] = SimpleNamespace(seated=7)
            e.apply_drowning(None, None, state, dict(points=[point(36148, 6)]))
            self.assertFalse(state['breath_tracker'].in_water)


if __name__ == '__main__':
    unittest.main()
