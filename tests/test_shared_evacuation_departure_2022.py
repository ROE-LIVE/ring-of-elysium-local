"""Общая эвакуация: вертолёт ждёт последнего живого или 4 места; иначе улетает по пределу матча."""
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server/directory'))
from shared_evacuation_2022 import SharedEvacuationRooms, MATCH_SECONDS


def member(uid, seated, started=0):
    return dict(actor_uid=uid, room_uid=5, world=SimpleNamespace(dead=False),
                vehicles=SimpleNamespace(seated=seated),
                match_statistics=SimpleNamespace(started_at=started))


class DepartureTests(unittest.TestCase):
    def room(self, rooms, members, seats):
        rooms.rooms[5] = dict(members=members, seats=seats, helicopter=77, due=None,
                              reason=None, finished=False, boarded_at=100)

    def test_partial_boarding_waits_for_the_others(self):
        # Прежде вертолёт улетал через 60 с после первой посадки; теперь ждёт.
        rooms = SharedEvacuationRooms(8)
        self.room(rooms, {1: member(1, 77), 2: member(2, None)}, {1: 1})
        for now in (110, 160, 1000):
            self.assertEqual(rooms.poll(now)[0], [])

    def test_match_limit_departs_with_whoever_is_aboard(self):
        rooms = SharedEvacuationRooms(8)
        self.room(rooms, {1: member(1, 77, started=50), 2: member(2, None, started=40)}, {1: 1})
        self.assertEqual(rooms.poll(40 + MATCH_SECONDS - 1)[0], [])
        decisions, events = rooms.poll(40 + MATCH_SECONDS)
        self.assertEqual(events[0]['reason'], 'timeout')
        self.assertEqual(len(decisions), 1)
        self.assertEqual(decisions[0]['seats'], {1: 1})             # спасён тот, кто внутри
        self.assertEqual(set(decisions[0]['members']), {1, 2})      # итог у всех
        self.assertEqual(decisions[0]['ended_at'], 40 + MATCH_SECONDS)

    def test_match_limit_with_nobody_aboard_everyone_loses(self):
        rooms = SharedEvacuationRooms(8)
        self.room(rooms, {1: member(1, None), 2: member(2, None)}, {})
        decisions, _ = rooms.poll(MATCH_SECONDS)
        self.assertEqual(len(decisions), 1)
        self.assertEqual(decisions[0]['seats'], {})

    def test_everyone_aboard_still_leaves_early(self):
        rooms = SharedEvacuationRooms(8)
        self.room(rooms, {1: member(1, 77)}, {1: 1})
        rooms.poll(101)
        self.assertEqual(len(rooms.poll(109)[0]), 1)


if __name__ == '__main__':
    unittest.main()
