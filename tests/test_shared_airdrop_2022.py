"""Аирдроп по таблице «空投»: оружие в контейнере и общий остаток на комнату (два участника)."""
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server/directory'))
from parcel_catalog_2022 import ParcelCatalogState, load_parcel_fixture
from weapon_probe_2022 import GUN_PROFILES, AMMUNITION_SLOTS, LootFixture, WeaponFixture, WeaponState


class SharedAirdropTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        template = bytearray(100)
        struct.pack_into('>Q', template, 4, 999)
        ground = LootFixture(999, 15510, 1, (100, 200, 300), bytes(45), 30004, bytes(template))
        self.fixture = WeaponFixture(bytes(82), bytes(60), loot=ground)
        body = bytearray(117)
        struct.pack_into('>QI', body, 0, 456, 501)
        struct.pack_into('>3i', body, 20, 100, 200, 300)
        (root / 'box.bin').write_bytes(body)
        self.box = bytes(body)
        items = [(15521, 10307, 1), (15522, 30008, 50), (15523, 201004, 1), (15524, 70003, 1)]
        config = dict(parcels=[dict(entity_file='box.bin', parcel_id=15520,
                                    items=[dict(item_index=i, definition=d, quantity=q) for i, d, q in items])])
        (root / 'parcels.json').write_text(json.dumps(config))
        self.parcels = ParcelCatalogState(load_parcel_fixture(root / 'parcels.json', self.fixture))
        self.parcels.register(0x654b, self.box)
        self.parcels.register(0x6571, struct.pack('>QI', 456, 15520))
        self.a, self.b = WeaponState(self.fixture, 42), WeaponState(self.fixture, 43)
        for weapon in (self.a, self.b):
            self.parcels.handle(0x656f, struct.pack('>Q', 456), weapon)

    def pick(self, weapon, index):
        return self.parcels.handle(0x3b63, struct.pack('>IIQBHB3iB', 15520, index, 0, 0, 0, 1, 100, 200, 300, 0), weapon)

    def test_airdrop_guns_and_ammo_are_known(self):
        for gun in (10108, 10207, 10602, 10106, 10307):
            self.assertIn(gun, GUN_PROFILES)
        self.assertEqual((AMMUNITION_SLOTS[30007], AMMUNITION_SLOTS[30008]), (14, 15))

    def test_gun_from_box_goes_to_one_player_only(self):
        _, event = self.pick(self.a, 15521)
        self.assertEqual((event['action'], event['definition']), ('parcel_pickup', 10307))
        self.assertIn(10307, [gun.definition for gun in self.a.guns.values()])
        packets, event = self.pick(self.b, 15521)
        self.assertEqual((event['action'], event['reason']), ('parcel_pick_rejected', 'container_item_taken'))
        self.assertNotIn(10307, [gun.definition for gun in self.b.guns.values()])
        # Список коробки у второго игрока уже без оружия.
        self.assertEqual(struct.unpack_from('>I', packets[-1][1], 4)[0], 3)

    def test_ammo_and_gear_are_shared_once(self):
        _, event = self.pick(self.b, 15522)
        self.assertEqual(event['action'], 'parcel_pickup')
        self.assertEqual(self.b.ammunition_quantity(30008), 50)
        _, event = self.pick(self.a, 15522)
        self.assertEqual(event['reason'], 'container_item_taken')
        self.assertEqual(self.a.ammunition_quantity(30008), 0)
        self.assertEqual(self.pick(self.a, 15523)[1]['action'], 'parcel_pickup')
        self.assertEqual(self.pick(self.b, 15523)[1]['reason'], 'container_item_taken')


if __name__ == '__main__':
    unittest.main()
