"""Комната: два участника не получают одну клетку рождения."""
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server/directory'))
from winter_selection_2022 import choose_cell

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


if __name__ == '__main__':
    unittest.main()
