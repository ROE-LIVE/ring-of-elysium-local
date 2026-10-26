"""Комната: внешность второго участника хранится отдельно от профиля хоста."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from local_cosmetics_2022 import LocalCosmetics


class RoomCosmeticsTests(unittest.TestCase):
    def test_second_account_uses_separate_state_file(self):
        catalog = json.loads((ROOT / 'config' / 'cosmetics.json').read_text())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'cosmetics.json'
            catalog['state_file'] = 'state/cosmetics.json'
            path.write_text(json.dumps(catalog))
            host = LocalCosmetics(path)
            guest = LocalCosmetics(path, state_file='cosmetics-515bb18e59c77c.json')
            self.assertEqual(host.state_path, Path(directory) / 'state' / 'cosmetics.json')
            self.assertEqual(guest.state_path, Path(directory) / 'state' / 'cosmetics-515bb18e59c77c.json')
            guest.save()
            self.assertFalse(host.state_path.exists())
            self.assertTrue(guest.state_path.exists())


if __name__ == '__main__':
    unittest.main()
