"""Сохранение стопок/HP при завершении, отмене и повторных запросах лечения."""
import struct
import sys
from pathlib import Path
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server/directory'))
from medical_probe_2022 import MedicalState
from weapon_probe_2022 import LootFixture, WeaponFixture, WeaponState, medical_record


class MedicalTests(unittest.TestCase):
    def setUp(self):
        self.weapon = WeaponState(WeaponFixture(bytes(82), bytes(60)), 42)
        self.weapon.medical[70001] = 2
        self.world = SimpleNamespace(hp=500)
        self.medical = MedicalState(self.weapon, self.world)
        self.request = struct.pack('>BBHIBB', 3, 2, 3, 0x8000, 0, 1)

    def test_complete_once_preserves_weapon_and_updates_health_and_stack(self):
        replies, events = self.medical.handle(0x3e80, self.request, 10)
        self.assertEqual(replies, [(0x3e81, struct.pack('>BIIB', 3, 0, 70001, 1))])
        self.assertEqual(self.medical.poll(12.99), ([], []))
        replies, events = self.medical.poll(13)
        self.assertEqual((self.world.hp, self.weapon.medical[70001]), (600, 1))
        self.assertEqual([code for code, body in replies], [0x3e82, 0x6f5, 0x1069, 0x2b])
        self.assertEqual(replies[-1], (0x2b, struct.pack('>QI', 42, 27)))
        self.assertEqual((self.weapon.clip, self.weapon.reserve), (2, 6))
        self.assertEqual(self.medical.poll(20), ([], []))

    def test_cancel_and_duplicate_start_do_not_spend_or_heal(self):
        self.medical.handle(0x3e80, self.request, 10)
        _, events = self.medical.handle(0x3e80, self.request, 11)
        self.assertEqual(events[0]['reason'], 'action_in_progress')
        replies, events = self.medical.handle(0x536, struct.pack('>I', 20), 11)
        self.assertEqual(replies, [(0x537, struct.pack('>II', 0, 20)),
                                  (0x2b, struct.pack('>QI', 42, 27))])
        self.assertEqual(self.medical.poll(20), ([], []))
        self.assertEqual((self.world.hp, self.weapon.medical[70001]), (500, 2))

    def test_full_hp_missing_item_and_malformed_requests_do_not_start(self):
        self.world.hp = 1000
        _, events = self.medical.handle(0x3e80, self.request, 0)
        self.assertEqual(events[0]['reason'], 'dead_or_full_hp')
        self.world.hp = 500
        self.weapon.medical.clear()
        _, events = self.medical.handle(0x3e80, self.request, 0)
        self.assertEqual(events[0]['reason'], 'no_item')
        for payload in (self.request[:-1], self.request[:-1] + b'\0', b'\x03'):
            _, events = self.medical.handle(0x3e80, payload, 0)
            self.assertEqual(events[0]['action'], 'medical_rejected')
        self.assertIsNone(self.medical.pending)

    def test_cancel_after_completion_and_invalid_clock_do_not_repeat_healing(self):
        self.medical.handle(0x3e80, self.request, 0)
        self.assertEqual(self.medical.poll(float('nan')), ([], []))
        self.assertEqual(self.medical.poll(float('inf')), ([], []))
        self.medical.poll(3)
        replies, _ = self.medical.handle(0x536, struct.pack('>I', 20), 4)
        self.assertEqual(replies, [(0x2b, struct.pack('>QI', 42, 27))])
        self.assertEqual((self.world.hp, self.weapon.medical[70001]), (600, 1))

    def test_native_hotkey_extension_does_not_select_or_duplicate_item(self):
        request = bytes.fromhex('03020003009c00000001')
        _, events = self.medical.handle(0x3e80, request, 0)
        self.assertEqual(events[0]['definition'], 70001)
        self.medical.poll(3)
        self.assertEqual((self.world.hp, self.weapon.medical[70001]), (600, 1))
        malformed = bytearray(request)
        malformed[4] = 1
        _, events = self.medical.handle(0x3e80, malformed, 4)
        self.assertEqual(events[0]['reason'], 'unsupported_variant')

    def test_last_item_clears_slot_and_clamps_hp(self):
        self.weapon.medical[70001] = 1
        self.world.hp = 990
        self.medical.handle(0x3e80, self.request, 0)
        replies, events = self.medical.poll(3)
        self.assertEqual(self.world.hp, 1000)
        self.assertNotIn(70001, self.weapon.medical)
        self.assertEqual(len(replies[0][1]), 50)
        self.assertEqual(events[0]['healed_raw'], 10)

    def test_partial_pickup_drop_repick_conserves_medical_weight_and_ammo(self):
        body = bytearray(100)
        struct.pack_into('>IQI', body, 0, 30201002, 999, 13)
        struct.pack_into('>3i', body, 29, 100, 200, 300)
        struct.pack_into('>I', body, 46, 1)
        body[62] = 2
        struct.pack_into('>III', body, 63, 70001, 5, 15510)
        item = LootFixture(999, 15510, 5, (100, 200, 300), bytes(45), 70001, bytes(body))
        weapon = WeaponState(WeaponFixture(bytes(82), bytes(60), loot=item), 42)
        weapon.reserve = 77  # 96.25 веса, помещается только один бинт весом2.
        weapon.available_loot.add(999)
        weapon.update_position((100, 200, 300))
        request = struct.pack('>IIQBHB3iB', 15510, 0, 0, 0, 0, 1, 100, 200, 300, 0)
        _, event = weapon.handle(0x3b63, request)
        self.assertEqual((event['quantity'], event['remaining'], weapon.medical[70001]), (1, 4, 1))
        _, event = weapon.handle(0x3e80, struct.pack('>BBBBHIIB', 2, 2, 0, 3, 1, 0, 0, 1))
        self.assertNotIn(70001, weapon.medical)
        request = struct.pack('>IIQBHB3iB', event['index'], 0, 0, 0, 0, 1, 100, 200, 300, 0)
        weapon.handle(0x3b63, request)
        self.assertEqual((weapon.medical[70001], weapon.reserve, weapon.clip), (1, 77, 2))
        self.assertEqual(len(medical_record(70001, 1)), 80)
