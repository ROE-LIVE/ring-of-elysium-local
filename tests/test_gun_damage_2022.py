"""Урон по таблице оружия клиента: падение по дистанции и множитель головы."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'server/directory'))
from gun_damage_2022 import GunDamageTable, DEFAULT_PATH
from shared_combat_2022 import SharedCombatRooms


class GunDamageTests(unittest.TestCase):
    def setUp(self):
        # TAC-50 и дробовик из EquipmentTableEuropa: dmg, min, dropStart, dropEnd, range, head%.
        self.table = GunDamageTable({10111: [2000, 1800, 15000, 80000, 100000, 150],
                                     10402: [260, 0, 400, 25000, 39900, 50]})

    def test_head_ratio_and_body(self):
        self.assertEqual(self.table.damage(10111, 1000, 3), 2000)
        self.assertEqual(self.table.damage(10111, 1000, 1), 3000)
        self.assertEqual(self.table.damage(10111, 1000, 2), 2000)

    def test_linear_dropoff_and_range(self):
        self.assertEqual(self.table.damage(10111, 47500, 3), 1900)
        self.assertEqual(self.table.damage(10111, 90000, 3), 1800)
        self.assertEqual(self.table.damage(10111, 100001, 3), 0)
        self.assertEqual(self.table.damage(10402, 25000, 3), 0)
        self.assertEqual(self.table.reach(10402), 39900)

    def test_unknown_gun_and_invalid_rows(self):
        self.assertIsNone(self.table.damage(1, 0, 3))
        with self.assertRaises(ValueError):
            GunDamageTable({1: [100, 200, 0, 0, 1, 100]})

    def test_pvp_uses_table_and_falls_back_to_training_damage(self):
        combat = SharedCombatRooms(None, 100, self.table)
        self.assertEqual(combat.hit_damage(10111, (0, 0, 0), (0, 10000, 0), 1), (3000, 100000))
        self.assertEqual(combat.hit_damage(20001, (0, 0, 0), (0, 100, 0), 3), (100, 10000))
        self.assertEqual(SharedCombatRooms(None, 100).hit_damage(10111, (0, 0, 0), (0, 1, 0), 1), (100, 10000))

    def test_generated_config_loads_when_present(self):
        if not DEFAULT_PATH.exists():
            self.skipTest('config/gun-damage-2022.json не сгенерирован')
        table = GunDamageTable.load()
        self.assertEqual(table.damage(10201, 0, 3), 400)


if __name__ == '__main__':
    unittest.main()
