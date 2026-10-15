"""Выбор через UI: дедлайн, отказ, сохранение исходного пресета и способностей."""
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server/directory'))
from weapon_probe_2022 import WeaponFixture, WeaponState
from winter_selection_2022 import choose, default_choice, selected_fixture, choose_cell, load_spawn_points


class WinterSelectionTests(unittest.TestCase):
    def test_cell_trailing_zero_selects_and_marker_matches_position(self):
        points = ((12, 26, 365100, 544000, 259407), (13, 26, 377600, 544000, 258793))
        point, replies, event = choose_cell(struct.pack('>IQIII', 2, 42, 13, 26, 0), 42, 1, 2, False, points)
        self.assertEqual(point, points[1])
        self.assertEqual(replies, [(0x11e0, struct.pack('>IIQIII', 1, 2, 42, 13, 26, 0))])
        self.assertEqual(event['request_flag'], 0)
        point, replies, event = choose_cell(struct.pack('>IQIII', 2, 42, 31, 26, 1), 42, 1, 2, False, points)
        self.assertEqual(point, points[1])
        self.assertTrue(event['snapped'])

    def test_foreign_invalid_late_cell_does_not_move_player(self):
        points = ((12, 26, 365100, 544000, 259407),)
        for uid, x, flag, now, started in ((43,12,0,1,False), (42,32,0,1,False),
                                          (42,12,2,1,False), (42,12,0,2,False), (42,12,0,1,True)):
            point, packets, event = choose_cell(struct.pack('>IQIII', 2, uid, x, 26, flag),42,now,2,started,points)
            self.assertIsNone(point)
            self.assertEqual(packets, [])
        self.assertEqual(len(load_spawn_points()), 660)

    def test_three_choices_grant_one_ability_and_preserve_armor_and_weapon(self):
        fixture = WeaponFixture(bytes(82), bytes(60), starting_equipment=(201001, 200101, 200906))
        for choice, capacity in ((1, 150), (2, 225), (3, 300)):
            with self.subTest(choice=choice):
                selected = selected_fixture(fixture, choice)
                weapon = WeaponState(selected, 42)
                flags = [struct.unpack('>II', payload) for code, payload in weapon.kit_sync() if code == 0x10d0]
                self.assertEqual(sum(value for _, value in flags), 1)
                self.assertEqual(weapon.bag_capacity, capacity)
                self.assertEqual(weapon.equipment[12], 201001)
                self.assertEqual(weapon.equipment[10], 200101)
                self.assertEqual(weapon.guns[1].definition, 10402)
        self.assertEqual(default_choice(fixture), 2)
        self.assertEqual(fixture.starting_equipment, (201001, 200101, 200906))

    def test_raw_ack_and_legacy_ack_have_different_shapes(self):
        choice, packets, event = choose(0x10cc, struct.pack('>II', 1, 3), 10, 11, False)
        self.assertEqual(choice, 3)
        self.assertEqual(packets, [(0x10d0, struct.pack('>II', 1, 3)), (0x10cd, struct.pack('>III', 1, 3, 0))])
        choice, packets, event = choose(0xbfc, struct.pack('>I', 1), 10, 11, False)
        self.assertEqual(packets[-1], (0xbfd, struct.pack('>II', 0, 1)))

    def test_resource_starters_follow_selected_choice_without_extra_citori_ammunition(self):
        fixture = WeaponFixture(bytes(82), bytes(60), weapon_slots=3,
            starting_equipment=(201001, 200101, 200906), winter_starter_inventory=True)
        for choice, definition, ammunition, quantity, magazine in (
                (1, 20002, 30003, 15, 17), (2, 20003, 30006, 10, 7),
                (3, 10402, 30004, 10, 2)):
            with self.subTest(choice=choice):
                state = WeaponState(selected_fixture(fixture, choice), 42)
                self.assertEqual((state.guns[1].definition, state.clip), (definition, magazine))
                self.assertEqual(state.ammunition_quantity(ammunition), quantity)
                self.assertEqual(state.reserve, 10 if choice == 3 else 0)
                self.assertEqual(state.medical, {70001: 5})
                self.assertEqual(set(state.equipment), {11})
                self.assertEqual(len(state.guns), 1)
        self.assertEqual(WeaponState(selected_fixture(fixture, None), 42).guns[1].definition, 20003)
        self.assertEqual(fixture.reserve, 6)

    def test_invalid_and_closed_requests_cannot_grant_kit(self):
        for value, now, deadline, started in ((0, 10, 11, False), (4, 10, 11, False),
                                             (1, 11, 11, False), (1, 10, None, False), (1, 10, 11, True)):
            with self.subTest(value=value, started=started, deadline=deadline):
                choice, packets, event = choose(0x10cc, struct.pack('>II', 1, value), now, deadline, started)
                self.assertIsNone(choice)
                self.assertEqual(packets, [(0x10cd, struct.pack('>III', 1, value, 1))])

    def test_other_attributes_and_truncated_records_are_not_accepted(self):
        self.assertIsNone(choose(0x10cc, struct.pack('>II', 20, 1), 10, 11, False))
        for code, body in ((0x10cc, bytes(7)), (0xbfc, bytes(5))):
            with self.assertRaises(ValueError):
                choose(code, body, 10, 11, False)
