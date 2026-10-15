"""Инварианты смешанной сумки: ёмкость, два стэка, магазин и смена набора."""
from dataclasses import replace
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server/directory'))
from weapon_probe_2022 import LootFixture, WeaponFixture, WeaponState, GUN_PROFILES


class InventoryConservationTests(unittest.TestCase):
    def state(self):
        gun = bytearray(82)
        gun[:4] = bytes((1, 1, 1, 0))
        struct.pack_into('>IQ', gun, 4, 10402, 101)
        struct.pack_into('>H', gun, 80, 1)
        ammo = bytearray(60)
        ammo[:4] = bytes((2, 1, 2, 0))
        struct.pack_into('>IQ', ammo, 4, 30004, 102)
        struct.pack_into('>H', ammo, 58, 100)
        state = WeaponState(WeaponFixture(bytes(gun), bytes(ammo), reserve=100,
            starting_equipment=(200907, 201001, 200101), weapon_slots=2,
            inventory_update='delta', reload_update='delta'), 42)
        state.update_position((100, 200, 300))
        return state

    def add(self, state, index, definition, quantity=1):
        body = bytearray(100)
        uid = 100000 + index
        struct.pack_into('>IQI', body, 0, 30201002, uid, 13)
        struct.pack_into('>3i', body, 29, 100, 200, 300)
        struct.pack_into('>I', body, 46, 1)
        body[62] = 2
        struct.pack_into('>III', body, 63, definition, quantity, index)
        item = LootFixture(uid, index, quantity, (100, 200, 300),
                           bytes(45), definition, bytes(body))
        state.loot_registry[index] = item
        state.available_loot.add(uid)
        state.ground_template = item.entity
        return item

    def pickup(self, state, index):
        return state.handle(0x3b63,
            struct.pack('>IIQBHB3iB', index, 0, 0, 0, 0, 1, 100, 200, 300, 0))

    def rounds(self, state, definition):
        return (state.ammunition_quantity(definition)
            + sum(gun.clip for gun in state.guns.values()
                  if GUN_PROFILES[gun.definition][0] == definition)
            + sum(item.quantity for index, item in state.loot_registry.items()
                  if index not in state.picked_loot and item.definition == definition))

    def test_two_stacks_full_bag_reload_drop_and_repick_conserve_each_ammunition(self):
        state = self.state()
        for index, definition, quantity in [(92000, 10201, 1),
                (92001, 30001, 100), (92002, 30001, 100), (92003, 30004, 100)]:
            self.add(state, index, definition, quantity)
        expected = {30001: 200, 30004: 202}
        def conserved():
            self.assertEqual({d: self.rounds(state, d) for d in expected}, expected)
            self.assertLessEqual(state.bag_weight_hundredths(), 15000)
        conserved()
        self.pickup(state, 92000)
        for index in (92001, 92002, 92003, 92001):
            self.pickup(state, index)
            conserved()
        self.assertEqual((state.extra_ammunition[30001], state.loot_registry[92001].quantity), (50, 50))
        self.assertEqual(state.loot_registry[92002].quantity, 100)
        state.handle(0x49e, struct.pack('>I', 2))
        state.handle(0x49c, struct.pack('>I', 2))
        conserved()
        self.assertEqual((state.guns[2].clip, state.extra_ammunition[30001]), (30, 20))
        self.pickup(state, 92003)
        conserved()
        self.assertEqual(state.reserve, 112)
        request = struct.pack('>BBHHQB', 2, 2, 2, 15, 0, 1)
        _, event = state.handle(0x3e80, request)
        self.assertEqual(event['action'], 'discard')
        conserved()
        dropped = event['index']
        for index in (92002, dropped, 92001, 92003):
            self.pickup(state, index)
            conserved()
        before = dict(expected)
        fire = struct.pack('>6fIBIIfII', 1,2,3,4,5,6,1,0,100,4,1,64,0)
        self.assertEqual(state.handle(0x11da, fire)[1]['action'], 'fire')
        expected[30001] -= 1
        conserved()
        self.assertEqual(state.handle(0x11da, fire)[1]['action'], 'duplicate_fire')
        conserved()
        self.assertEqual(before[30004], expected[30004])

    def test_three_kit_swaps_keep_nonempty_inventory_and_overweight_contents(self):
        state = self.state()
        self.add(state, 92000, 10201)
        self.pickup(state, 92000)
        state.extra_ammunition[30001] = 100
        # Смена на меньший набор не должна молча уничтожать уже выданные вещи.
        before = (state.reserve, dict(state.extra_ammunition),
                  [(s, g.uid, g.clip) for s, g in state.guns.items()],
                  dict(state.equipment_durability))
        for index, definition, selected, capacity in (
                (93000, 200904, 4, 300), (93001, 200906, 3, 225), (93002, 200907, 2, 150)):
            self.add(state, index, definition)
            replies, event = self.pickup(state, index)
            self.assertEqual(event['action'], 'pickup')
            self.assertEqual([struct.unpack('>II', b) for c,b in replies if c == 0x10d0],
                             [(i, int(i == selected)) for i in (2,3,4)])
            self.assertEqual(state.bag_capacity, capacity)
            self.assertEqual((state.reserve, state.extra_ammunition,
                [(s,g.uid,g.clip) for s,g in state.guns.items()],
                state.equipment_durability | {11: before[3][11]}), before)
        self.assertEqual(state.bag_weight_hundredths(), 17500)
        self.add(state, 94000, 30001, 20)
        self.assertEqual(self.pickup(state, 94000)[1]['quantity'], 0)
        self.assertEqual(state.extra_ammunition[30001], 100)


if __name__ == '__main__':
    unittest.main()
