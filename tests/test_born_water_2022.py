"""Nascimento sem escolha de célula: o sorteio evita as células sobre a água (water_cells)."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server/directory'))
from winter_selection_2022 import load_water_cells
from game_endpoint_probe_2022 import Endpoint


class BornWaterTests(unittest.TestCase):
    def test_water_cells_are_read_and_random_birth_avoids_them(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'cells.json'
            path.write_text(json.dumps({'water_cells': [[1, 1], [2, 2]], 'points': []}), encoding='utf-8')
            water = load_water_cells(path)
        self.assertEqual(water, {(1, 1), (2, 2)})
        self.assertEqual(load_water_cells(None), frozenset())
        e = Endpoint.__new__(Endpoint)
        e.spawn_points = ((1, 1, 10, 10, 100), (2, 2, 20, 20, 100), (3, 3, 30, 30, 500))
        e.water_cells = water
        e.shared_loot = None
        e.live_room_accounts = lambda state: set()
        e.capture = type('C', (), {'record': staticmethod(lambda *a, **k: None)})()
        for _ in range(30):
            state = dict(actor_uid=7)
            self.assertEqual(e.ensure_born_point(state)[:2], (3, 3))


if __name__ == '__main__':
    unittest.main()
