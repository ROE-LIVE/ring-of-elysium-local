"""Общая комната с каталогом точек: подбор виден всем, остаток общий, AOI у каждого свой."""
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server/directory'))
from loot_catalog_2022 import LootCatalog, LootCatalogState
from shared_loot_2022 import SharedLootRooms
from weapon_probe_2022 import LootFixture, WeaponFixture, WeaponState


class SharedCatalogTests(unittest.TestCase):
    def setUp(self):
        self.template = bytes(100)
        self.fixed = LootFixture(1, 1, 1, (0, 0, 0), bytes(45), 30004, self.template)

    def build(self, quantity=10):
        rows = [dict(index=100 + n, entity_uid=1000 + n, item_id=30004,
                     quantity=quantity, position=[n * 10, 0, 0]) for n in range(2)]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'catalog.json'
            path.write_text(json.dumps(dict(radius_cm=100, visible_limit=128, batch_limit=16, entities=rows)))
            catalog = LootCatalog.load(path, self.template)
        rooms = SharedLootRooms(WeaponFixture(bytes(82), bytes(60), loot=self.fixed), catalog=catalog)
        return catalog, rooms

    def member(self, catalog, rooms, actor):
        state = dict(actor_uid=actor, room_uid=1,
                     weapon=WeaponState(WeaponFixture(bytes(82), bytes(60), loot=self.fixed), actor))
        self.assertTrue(rooms.attach(state))
        state['loot_catalog'] = LootCatalogState(catalog, state['weapon'], shared=True)
        state['weapon'].update_position((0, 0, 0))
        state['loot_catalog'].poll()
        return state

    def request(self, index=100):
        return struct.pack('>IIQBHB3iB', index, 0, 0, 0, 0, 1, 0, 0, 0, 0)

    def test_full_pickup_removes_point_for_everyone_and_blocks_second_pickup(self):
        catalog, rooms = self.build()
        a, b = self.member(catalog, rooms, 42), self.member(catalog, rooms, 43)
        self.assertIn(100, b['loot_catalog'].visible)
        _, event, outputs = rooms.handle(a, 0x3b63, self.request())
        self.assertEqual(event['action'], 'pickup')
        self.assertEqual(outputs, [(b, [(0x82b, struct.pack('>Q', 1000))])])
        self.assertNotIn(100, b['loot_catalog'].visible)
        self.assertIn(100, b['weapon'].picked_loot)
        # Точка не возвращается при повторном AOI у второго участника.
        b['weapon'].update_position((5000, 0, 0)); b['loot_catalog'].poll()
        b['weapon'].update_position((0, 0, 0))
        packets, _ = b['loot_catalog'].poll()
        self.assertNotIn((0x821, catalog.items[0].entity), packets)
        replies, event, outputs = rooms.handle(b, 0x3b63, self.request())
        self.assertEqual(event['reason'], 'shared_loot_consumed')
        self.assertEqual(outputs, [])

    def test_partial_pickup_shares_remainder_and_late_member_sees_it(self):
        catalog, rooms = self.build(quantity=90)
        a, b = self.member(catalog, rooms, 42), self.member(catalog, rooms, 43)
        _, event, outputs = rooms.handle(a, 0x3b63, self.request())
        self.assertEqual((event['quantity'], event['remaining']), (74, 16))
        self.assertEqual([code for code, _ in outputs[0][1]], [0x82b, 0x821])
        self.assertEqual(struct.unpack_from('>I', outputs[0][1][1][1], 67)[0], 16)
        late = self.member(catalog, rooms, 44)
        self.assertEqual(late['weapon'].loot_registry[100].quantity, 16)
        _, event, _ = rooms.handle(b, 0x3b63, self.request())
        self.assertEqual((event['quantity'], event['remaining']), (16, 0))
        replies, event, _ = rooms.handle(late, 0x3b63, self.request())
        self.assertEqual(event['reason'], 'shared_loot_consumed')

    def test_member_joining_after_consumption_never_sees_point(self):
        catalog, rooms = self.build()
        a = self.member(catalog, rooms, 42)
        rooms.handle(a, 0x3b63, self.request())
        late = self.member(catalog, rooms, 44)
        self.assertNotIn(100, late['loot_catalog'].visible)
        self.assertIn(101, late['loot_catalog'].visible)

    def test_catalog_index_overlap_with_fixture_is_rejected(self):
        rows = [dict(index=1, entity_uid=1000, item_id=30004, quantity=10, position=[0, 0, 0])]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'catalog.json'
            path.write_text(json.dumps(dict(radius_cm=100, visible_limit=128, batch_limit=16, entities=rows)))
            with self.assertRaises(ValueError):
                catalog = LootCatalog.load(path, self.template)
                SharedLootRooms(WeaponFixture(bytes(82), bytes(60), loot=self.fixed), catalog=catalog)


if __name__ == '__main__':
    unittest.main()
