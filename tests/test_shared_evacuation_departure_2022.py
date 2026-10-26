"""Общая эвакуация: вертолёт улетает через depart_after после первой посадки, не ждёт всех."""
from pathlib import Path
import struct
import sys
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server/directory'))
from shared_evacuation_2022 import SharedEvacuationRooms


class DepartureTests(unittest.TestCase):
    def test_departure_ends_room_for_everyone_after_timer(self):
        rooms = SharedEvacuationRooms(8, depart_after=60)
        world = lambda: SimpleNamespace(dead=False)
        a = dict(actor_uid=1, room_uid=5, world=world(), vehicles=SimpleNamespace(seated=77))
        b = dict(actor_uid=2, room_uid=5, world=world(), vehicles=SimpleNamespace(seated=None))
        rooms.rooms[5] = dict(members={1: a, 2: b}, seats={1: 1}, helicopter=77, due=None,
                              reason=None, finished=False, boarded_at=100)
        decisions, events = rooms.poll(110)
        self.assertEqual(decisions, [])
        self.assertEqual(events[0]['reason'], 'departure')
        decisions, _ = rooms.poll(160)
        self.assertEqual(len(decisions), 1)
        self.assertEqual(set(decisions[0]['members']), {1, 2})
        self.assertEqual(decisions[0]['seats'], {1: 1})

    def test_everyone_aboard_still_leaves_early(self):
        rooms = SharedEvacuationRooms(8, depart_after=60)
        a = dict(actor_uid=1, room_uid=5, world=SimpleNamespace(dead=False), vehicles=SimpleNamespace(seated=77))
        rooms.rooms[5] = dict(members={1: a}, seats={1: 1}, helicopter=77, due=None,
                              reason=None, finished=False, boarded_at=100)
        rooms.poll(101)
        self.assertEqual(len(rooms.poll(109)[0]), 1)


if __name__ == '__main__':
    unittest.main()
