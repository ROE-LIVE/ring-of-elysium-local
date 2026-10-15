"""Контейнер: согласование ID, границы pickup и отсутствие повторной выдачи."""
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server/directory'))
from parcel_probe_2022 import ParcelFixture, ParcelState
from weapon_probe_2022 import WeaponFixture, WeaponState


class ParcelTests(unittest.TestCase):
    def setUp(self):
        self.parcel = ParcelState(ParcelFixture(456, 15520, 15521, 20, (100,200,300)))
        self.weapon = WeaponState(WeaponFixture(bytes(82), bytes(60)), 123)
        body = struct.pack('>QI', 456, 501) + bytes(105)
        self.parcel.register(0x654b, body)
        self.parcel.register(0x6571, struct.pack('>QI', 456, 15520))

    def request(self, parcel=15520, index=15521, x=100):
        return struct.pack('>IIQBHB3iB', parcel, index, 0, 0, 0, 1, x,200,300,0)

    def test_open_matches_model_and_link_and_addresses_component(self):
        self.assertEqual(self.parcel.handle(0x656f, struct.pack('>Q', 999), self.weapon)[0], [])
        self.parcel.linked = False
        self.assertEqual(self.parcel.handle(0x656f, struct.pack('>Q', 456), self.weapon)[0], [])
        self.parcel.linked = True
        packets, event = self.parcel.handle(0x656f, struct.pack('>Q', 456), self.weapon)
        self.assertEqual(packets[0][0], 0x3b61)
        self.assertEqual(len(packets[0][1]), 52)
        self.assertEqual(struct.unpack_from('>4I', packets[0][1]), (15520,1,15521,1))

    def test_pickup_conserves_inventory_and_empty_contents_on_reopen(self):
        self.assertEqual(self.parcel.handle(0x3b63, self.request(), self.weapon)[0], [])
        self.parcel.handle(0x656f, struct.pack('>Q', 456), self.weapon)
        for request in (self.request(parcel=15522), self.request(index=15522), self.request(x=850)):
            self.assertEqual(self.parcel.handle(0x3b63, request, self.weapon)[0], [])
        packets, event = self.parcel.handle(0x3b63, self.request(), self.weapon)
        self.assertEqual(self.weapon.reserve, 26)
        self.assertEqual([code for code, _ in packets], [0x3b64,0x5fb,0x3b61,0x6f5,0x4a0])
        self.assertEqual(dict(packets)[0x3b61], struct.pack('>III',15520,0,0))
        self.assertEqual(self.parcel.handle(0x3b63,self.request(),self.weapon)[1]['action'], 'parcel_duplicate_pickup')
        self.assertEqual(self.weapon.reserve, 26)
        packets, _ = self.parcel.handle(0x656f,struct.pack('>Q',456),self.weapon)
        self.assertEqual(packets[0][1], struct.pack('>III',15520,0,0))

    def test_state_is_per_session_and_malformed_request_rejected(self):
        with self.assertRaises(ValueError):
            self.parcel.handle(0x656f, bytes(7), self.weapon)
        self.assertFalse(ParcelState(self.parcel.fixture).opened)

    def test_removed_model_cannot_be_opened_or_picked(self):
        self.parcel.handle(0x656f, struct.pack('>Q', 456), self.weapon)
        self.parcel.register(0x654c, struct.pack('>Q', 999))
        self.assertTrue(self.parcel.spawned)
        self.parcel.register(0x654c, struct.pack('>Q', 456))
        self.assertEqual(self.parcel.handle(0x656f, struct.pack('>Q', 456), self.weapon)[0], [])
        self.assertEqual(self.parcel.handle(0x3b63, self.request(), self.weapon)[0], [])
        self.assertEqual(self.weapon.reserve, 6)

    def test_partial_parcel_pickup_preserves_remaining_rounds_and_bag_limit(self):
        self.weapon.reserve=75  # Базовая вместимость100: до80 патронов.
        self.parcel.handle(0x656f,struct.pack('>Q',456),self.weapon)
        replies,event=self.parcel.handle(0x3b63,self.request(),self.weapon)
        self.assertEqual((self.weapon.reserve,self.parcel.remaining,event['quantity']),(80,15,5))
        self.assertFalse(self.parcel.picked)
        self.assertEqual(struct.unpack('>I',dict(replies)[0x6f5])[0],100)
        _,event=self.parcel.handle(0x3b63,self.request(),self.weapon)
        self.assertEqual((event['quantity'],self.parcel.remaining,self.weapon.reserve),(0,15,80))
        self.weapon.reserve=60
        self.parcel.handle(0x3b63,self.request(),self.weapon)
        self.assertEqual((self.weapon.reserve,self.parcel.remaining),(75,0))

    def test_parcel_accounts_for_weight_of_other_ammunition(self):
        self.weapon.reserve = 60
        self.weapon.extra_ammunition[30001] = 40  # 75 + 20 единиц веса.
        self.parcel.handle(0x656f, struct.pack('>Q', 456), self.weapon)
        _, event = self.parcel.handle(0x3b63, self.request(), self.weapon)
        self.assertEqual((event['quantity'], self.parcel.remaining), (4, 16))
        self.assertEqual((self.weapon.reserve, self.weapon.extra_ammunition[30001]), (64, 40))
        self.assertEqual(self.weapon.bag_weight_hundredths(), 10000)
