"""Комната: два участника не получают одну клетку рождения."""
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server/directory'))
from winter_selection_2022 import choose_cell
from types import SimpleNamespace
from game_endpoint_probe_2022 import Endpoint, shared_selection_deadline

POINTS = ((10, 10, 100, 100, 50), (11, 10, 200, 100, 50), (20, 20, 900, 900, 50))


def request(uid, x, y):
    return struct.pack('>IQIII', 2, uid, x, y, 0)


class RoomBornCellTests(unittest.TestCase):
    def test_occupied_cell_moves_second_player_to_nearest_free(self):
        point, _, event = choose_cell(request(7, 10, 10), 7, 1, 60, False, POINTS, frozenset({(10, 10)}))
        self.assertEqual(point[:2], (11, 10))
        self.assertTrue(event['occupied_by_other'])

    def test_free_cell_and_no_room_keep_previous_behaviour(self):
        point, _, event = choose_cell(request(7, 10, 10), 7, 1, 60, False, POINTS)
        self.assertEqual(point[:2], (10, 10))
        self.assertFalse(event['occupied_by_other'])

    def test_all_taken_falls_back_to_requested(self):
        taken = frozenset(p[:2] for p in POINTS)
        point, _, _ = choose_cell(request(7, 20, 20), 7, 1, 60, False, POINTS, taken)
        self.assertEqual(point[:2], (20, 20))

    def test_snapshot_lists_own_cell_first_then_other_members(self):
        fake = SimpleNamespace(shared_loot=SimpleNamespace(epochs={1: 2}),
                               room_born_cells={(1, 2): {9: (11, 10), 7: (10, 10)}})
        fake.born_cells = lambda state: Endpoint.born_cells(fake, state)
        # Ambos presentes na sala (live_room_accounts filtra células de quem saiu).
        fake.live_room_accounts = lambda state: {7, 9}
        body = Endpoint.born_snapshot(fake, dict(room_uid=1, actor_uid=7))
        self.assertEqual(struct.unpack_from('>II', body), (2, 2))
        self.assertEqual(struct.unpack_from('>QIII', body, 8), (7, 10, 10, 0))
        self.assertEqual(struct.unpack_from('>QIII', body, 28), (9, 11, 10, 0))
        self.assertEqual(len(body), 8 + 20 * 2)
        solo = SimpleNamespace(shared_loot=None, room_born_cells={})
        solo.born_cells = lambda state: Endpoint.born_cells(solo, state)
        solo.live_room_accounts = lambda state: {7}
        self.assertEqual(Endpoint.born_snapshot(solo, dict(room_uid=1, actor_uid=7)), struct.pack('>II', 0, 2))

    def test_room_selection_countdown_is_shared(self):
        table = {}
        self.assertEqual(shared_selection_deadline(table, (1, 1), 100, 47), (147, 47))
        self.assertEqual(shared_selection_deadline(table, (1, 1), 114, 47), (147, 33))
        self.assertEqual(shared_selection_deadline(table, (1, 1), 143, 47), (190, 47))
        self.assertEqual(shared_selection_deadline(table, (2, 1), 114, 47), (161, 47))


if __name__ == '__main__':
    unittest.main()
