"""Согласованность ограниченного сценария стрельбы и перезарядки."""
from pathlib import Path
import struct
import sys
import tempfile
import json
import unittest
from dataclasses import replace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'server/directory'))
from weapon_probe_2022 import GUN_PROFILES, GunInstance, LootFixture, WeaponFixture, WeaponState, equipment_record
from attachment_probe_2022 import AttachmentInstance


class WeaponStateTests(unittest.TestCase):
    def test_gameplay_delta_keeps_native_own_inventory_branch(self):
        from inventory_codec_2022 import decode_delta
        state = WeaponState(WeaponFixture(bytes(82), bytes(60), reserve=6), 42)
        code, body = state.item_delta(2, 13, state.ammunition_record(30004))
        decoded = decode_delta(body)
        self.assertEqual(code, 0x3e82)
        self.assertEqual((decoded.own, decoded.actor_uid), (1, 42))

    def test_each_gun_inventory_advertises_its_capacity_independently_of_clip(self):
        state = WeaponState(WeaponFixture(bytes(82), bytes(60), weapon_slots=3), 42)
        for definition, (_, capacity) in GUN_PROFILES.items():
            with self.subTest(definition=definition):
                state.guns = {1: GunInstance(definition, max(0, capacity - 1), 123)}
                record = next(r for r in state.inventory_records() if r[:2] == b'\x01\x01')
                self.assertEqual(struct.unpack_from('>I', record, 56)[0], capacity)
                self.assertEqual(state.guns[1].clip, max(0, capacity - 1))
                self.assertEqual(state.magazine_capacity, capacity)

    def test_inventory_capacity_tracks_extended_magazine_on_every_slot(self):
        state = WeaponState(WeaponFixture(bytes(82), bytes(60), weapon_slots=3), 42)
        state.guns = {1: GunInstance(20002, 17, 100),
                      2: GunInstance(10201, 23, 101, {3: AttachmentInstance(40403, 200)}),
                      3: GunInstance(10202, 7, 102)}
        def capacities():
            return {r[1]: struct.unpack_from('>I', r, 56)[0]
                    for r in state.inventory_records() if r[0] == 1 and r[1] in (1, 2, 3)}
        self.assertEqual(capacities(), {1: 17, 2: 40, 3: 30})
        state.guns[3].parts[3] = state.guns[2].parts.pop(3)
        self.assertEqual(capacities(), {1: 17, 2: 30, 3: 40})
        state.guns[3].parts.clear()
        self.assertEqual(capacities(), {1: 17, 2: 30, 3: 30})
        self.assertEqual([g.clip for g in state.guns.values()], [17, 23, 7])

    def test_full_or_no_reserve_reload_is_noop_without_ack_or_ammo_change(self):
        for clip, reserve, reason in ((2, 6, 'magazine_full'), (1, 0, 'reserve_empty')):
            with self.subTest(reason=reason):
                state = WeaponState(WeaponFixture(bytes(82), bytes(60)), 42)
                state.hand_slot = 1
                state.clip, state.reserve = clip, reserve
                packets, event = state.handle(0x49c, struct.pack('>I', 1))
                self.assertEqual(packets, [])
                self.assertEqual((event['action'],event['reason'],event['amount']), ('reload_noop', reason, 0))
                self.assertEqual((state.clip,state.reserve,state.pending_reload), (clip,reserve,None))

    def test_ground_drag_selects_requested_slot_and_keeps_other_guns(self):
        state = self.recycling_state(definition=10201, quantity=1)
        state.fixture = replace(state.fixture, weapon_slots=3, inventory_update='delta')
        initial = state.guns[1]
        request = struct.pack('>IIQBHB3iB',15510,0,0,1,3,0,100,200,300,0)
        _, event = state.handle(0x3b63, request)
        self.assertEqual(event['action'],'pickup')
        self.assertIs(state.guns[1],initial)
        self.assertEqual(state.guns[3].definition,10201)
        self.assertNotIn(2,state.guns)
        uid = state.guns[3].uid
        _, repeated = state.handle(0x3b63, request)
        self.assertEqual(repeated['action'],'duplicate_pickup')
        self.assertEqual(state.guns[3].uid,uid)

    def test_ground_drag_rejects_unknown_reference_and_non_weapon_without_mutation(self):
        for definition,container,slot,flag in ((10201,1,4,0),(10201,2,2,0),
                                               (10201,1,2,1),(30004,1,2,0)):
            state = self.recycling_state(definition=definition, quantity=1)
            state.fixture = replace(state.fixture,weapon_slots=3)
            request = struct.pack('>IIQBHB3iB',15510,0,0,container,slot,flag,100,200,300,0)
            before=(dict(state.guns),set(state.available_loot),set(state.picked_loot))
            _,event=state.handle(0x3b63,request)
            self.assertEqual(event['failed_checks'],['destination_variant'])
            self.assertEqual((state.guns,state.available_loot,state.picked_loot),before)

    def test_three_common_slots_keep_instances_on_pickup_swap_and_resume(self):
        state = self.recycling_state(definition=10201, quantity=1)
        state.fixture = replace(state.fixture, weapon_slots=3, inventory_update='delta')
        state.handle(0x3b63, self.pickup_request(15510))
        third = state.spawn_discard(10403, 1, (100, 200, 300), clip=4)
        _, event = state.handle(0x3b63, self.pickup_request(third.index))
        self.assertEqual(event['action'], 'pickup')
        self.assertIsNone(event['discarded_index'])
        self.assertEqual({s:g.definition for s,g in state.guns.items()}, {1:10402,2:10201,3:10403})
        state.guns[2].clip = 17
        state.handle(0x49e, struct.pack('>I', 3))
        original = dict(state.guns)
        replies, event = state.handle(0x3e80, struct.pack('>BBHBHHB',1,1,3,1,1,1,1))
        self.assertEqual(event['action'], 'move_gun')
        self.assertIs(state.guns[1], original[3])
        self.assertIs(state.guns[3], original[1])
        self.assertIs(state.guns[2], original[2])
        self.assertEqual((state.hand_slot,state.selected_slot,state.clip), (1,1,4))
        magazines = [struct.unpack('>QIII',b)[1:3] for c,b in state.reconcile_inventory() if c==0x4a0]
        self.assertEqual(magazines, [(1,4),(2,17),(3,2)])
        self.assertEqual(len({g.uid for g in state.guns.values()}),3)

    def test_legacy_two_primary_slots_reject_third_with_specific_guard(self):
        state = self.recycling_state()
        state.fixture = replace(state.fixture, weapon_slots=2, handgun_slot=True)
        gun = state.guns[1]
        _, event = state.handle(0x3e80, struct.pack('>BBHBHHB',1,1,1,1,3,1,1))
        self.assertEqual(event['failed_checks'], ['destination_slot'])
        self.assertEqual((event['source_slot'],event['target_slot']), (1,3))
        self.assertIs(state.guns[1],gun)
        self.assertNotIn(3,state.guns)

    def test_m4_fire_reports_556_reserve_separately_from_legacy_12ga(self):
        state = self.recycling_state(definition=10201, quantity=1)
        state.fixture = replace(state.fixture, weapon_slots=2)
        state.extra_ammunition[30001] = 50
        state.handle(0x3b63, self.pickup_request(15510))
        state.handle(0x49e, struct.pack('>I', 2))
        state.clip = 30
        body = struct.pack('>6fIBIIfII', 0, 0, 0, 0, 0, 0, 1, 0, 1, 0, 0, 0, 0)
        packets, event = state.handle(0x11da, body)
        self.assertEqual(event['action'], 'fire')
        self.assertEqual((event['slot'], event['clip'], event['ammunition_definition'],
                          event['ammunition_quantity'], event['reserve']), (2, 29, 30001, 50, 6))
        self.assertEqual(struct.unpack('>QIII', packets[0][1])[1:], (2, 29, 1))

    def test_pickup_rejection_identifies_slot_guard_without_mutating_loot(self):
        state = self.recycling_state()
        body = bytearray(self.pickup_request(15510))
        struct.pack_into('>I', body, 4, 2)
        before = (dict(state.guns), set(state.available_loot), set(state.picked_loot))
        packets, event = state.handle(0x3b63, bytes(body))
        self.assertEqual(packets, [])
        self.assertEqual(event['reason'], 'pickup_fixture_or_distance')
        self.assertEqual(event['failed_checks'], ['slot_zero'])
        self.assertEqual(event['requested_slot'], 2)
        self.assertEqual((dict(state.guns), set(state.available_loot), set(state.picked_loot)), before)

    def test_own_combat_armor_breaks_without_resetting_guns_or_reserve(self):
        state = self.recycling_state()
        state.fixture = replace(state.fixture, combat_armor_absorb_percent=50)
        state.equipment[12] = 201001
        state.equipment_durability[12] = 1
        state.hand_slot = 1
        gun, ammunition = state.guns[1], state.reserve
        damage, packets, event = state.absorb_combat_damage(50)
        self.assertEqual((damage, event['absorbed'], event['armor_durability']), (49, 1, 0))
        self.assertEqual([code for code, _ in packets], [0x3e82])
        # Остаток0 остаётся тем же предметом, а не новым с полным durable.
        self.assertEqual(state.equipment[12], 201001)
        self.assertEqual((state.hand_slot, state.reserve), (1, ammunition))
        self.assertIs(state.guns[1], gun)
        damage, packets, event = state.absorb_combat_damage(50)
        self.assertEqual((damage, packets, event['absorbed']), (50, [], 0))
        self.assertEqual(state.equipment_durability[12], 0)

    def test_own_combat_armor_conserves_damage_and_only_consumes_body_vest(self):
        state = self.recycling_state()
        state.fixture = replace(state.fixture, combat_armor_absorb_percent=50)
        state.equipment.update({10: 200101, 12: 201001})
        state.equipment_durability.update({10: 800, 12: 2000})
        before = state.equipment_durability[12]
        damage, packets, event = state.absorb_combat_damage(51)
        self.assertEqual((damage, event['absorbed']), (26, 25))
        self.assertEqual(damage + before - state.equipment_durability[12], 51)
        self.assertEqual(state.equipment_durability[10], 800)
        state.equipment.pop(12)
        damage, packets, event = state.absorb_combat_damage(51)
        self.assertEqual((damage, packets, event['absorbed']), (51, [], 0))

    def test_own_combat_armor_is_disabled_by_default_and_reconciles_latest_value(self):
        state = self.recycling_state()
        state.equipment[12] = 201001
        state.equipment_durability[12] = 2000
        self.assertEqual(state.absorb_combat_damage(50)[:2], (50, []))
        self.assertEqual(state.equipment_durability[12], 2000)
        state.fixture = replace(state.fixture, combat_armor_absorb_percent=100)
        damage, packets, event = state.absorb_combat_damage(50)
        self.assertEqual((damage, event['absorbed']), (0, 50))
        record = next(r for r in state.inventory_records() if r[0:2] == bytes((1, 12)))
        self.assertEqual(struct.unpack_from('>I', record, 32)[0], 1950)
        self.assertIn(packets[0], state.reconcile_inventory())
        before = dict(state.equipment_durability)
        for invalid in (True, -1, 101, 1.5):
            with self.assertRaises(ValueError): state.absorb_combat_damage(invalid)
        self.assertEqual(state.equipment_durability, before)

    def test_weapon_families_use_matching_ammunition_and_table_magazines(self):
        for definition, ammunition, capacity, duration in (
                (10101, 30001, 5, 3.933), (10102, 30002, 5, 3.170),
                (10202, 30002, 30, 3.070), (20001, 30005, 12, 1.500),
                (10303, 30003, 19, 2.770), (20003, 30006, 7, 2.240),
                (10601, 30002, 100, 10.400), (10605, 30009, 1, 3.133)):
            with self.subTest(definition=definition):
                state = self.recycling_state(definition=definition, quantity=1)
                state.fixture = replace(state.fixture, weapon_slots=2, handgun_slot=True,
                                        reload_update='delta', timed_reload=True)
                state.set_ammunition_quantity(ammunition, capacity + 2)
                state.handle(0x3b63, self.pickup_request(15510))
                slot = 3 if definition in (20001, 20003) else 2
                state.handle(0x49e, struct.pack('>I', slot))
                _, event = state.handle(0x49c, struct.pack('>I', slot), now=10)
                self.assertEqual(event['action'], 'reload_started')
                self.assertEqual(state.poll(10 + duration - .001), ([], []))
                state.poll(10 + duration)
                self.assertEqual((state.clip, state.ammunition_quantity(ammunition), state.reserve),
                                 (capacity, 2, 6))
                self.assertEqual((state.guns[1].definition, state.guns[1].clip), (10402, 2))

    def test_9mm_half_hundredth_weight_partial_pickup_and_drop_conserve_units(self):
        state = self.recycling_state(definition=30003, quantity=300)
        state.equipment.pop(11)
        state.reserve = 1
        # Стандартная сумка100: (10000-125)/37.5 позволяет ровно263патрона.
        _, event = state.handle(0x3b63, self.pickup_request(15510))
        self.assertEqual((event['quantity'], event['remaining']), (263, 37))
        self.assertEqual(state.ammunition_quantity(30003), 263)
        self.assertEqual(struct.unpack('>I', state.capacity_sync()[1])[0], 99)
        discard = struct.pack('>BBHHQB', 2, 2, 7, 3, 0, 1)
        _, event = state.handle(0x3e80, discard)
        self.assertEqual(event['action'], 'discard')
        dropped = state.loot_registry[event['index']]
        self.assertEqual((dropped.definition, dropped.quantity), (30003, 3))
        self.assertEqual(state.ammunition_quantity(30003) + dropped.quantity +
                         state.loot_registry[15510].quantity, 300)

    def test_primary_pickup_while_pistol_active_does_not_replace_handgun(self):
        state = self.recycling_state(definition=20001, quantity=1)
        state.fixture = replace(state.fixture, handgun_slot=True)
        state.handle(0x3b63, self.pickup_request(15510))
        pistol = state.guns[3]
        state.handle(0x49e, struct.pack('>I', 3))
        extra = replace(state.fixture.loot, definition=10102, index=15511, entity_uid=998)
        state.loot_registry[extra.index] = extra
        state.available_loot.add(extra.entity_uid)
        state.handle(0x3b63, self.pickup_request(extra.index))
        self.assertIs(state.guns[3], pistol)
        self.assertEqual(state.guns[1].definition, 10102)
        self.assertEqual(set(state.guns), {1, 3})

    def test_move_gun_swaps_instances_preserves_magazines_and_active_hand(self):
        state = self.recycling_state(definition=10201, quantity=1)
        state.fixture = replace(state.fixture, weapon_slots=2, inventory_update='delta')
        state.handle(0x3b63, self.pickup_request(15510))
        state.handle(0x49e, struct.pack('>I', 2))
        state.guns[2].clip = 17
        citori, m4 = state.guns[1], state.guns[2]
        before = (state.reserve, state.bag_weight_hundredths(), dict(state.equipment))
        request = bytes.fromhex('01010001010002000101')
        replies, event = state.handle(0x3e80, request)
        self.assertEqual(event['action'], 'move_gun')
        self.assertIs(state.guns[1], m4)
        self.assertIs(state.guns[2], citori)
        self.assertEqual((state.hand_slot, state.selected_slot, state.clip), (1, 1, 17))
        self.assertEqual((state.reserve, state.bag_weight_hundredths(), state.equipment), before)
        self.assertEqual([c for c, _ in replies], [0x3e81, 0x3e82, 0x3e82, 0x4a0, 0x4a0, 0x49f])
        self.assertEqual(struct.unpack('>II', replies[-1][1]), (1, 0))
        # Обратный обмен возвращает те же экземпляры, без нового UID/лут-сущности.
        state.handle(0x3e80, request)
        self.assertIs(state.guns[1], citori)
        self.assertIs(state.guns[2], m4)
        self.assertEqual((state.hand_slot, state.guns[2].clip, state.drop_counter), (2, 17, 0))

    def test_move_gun_empty_slot_and_invalid_requests_do_not_duplicate_items(self):
        state = self.recycling_state()
        state.fixture = replace(state.fixture, weapon_slots=2)
        gun = state.guns[1]
        state.hand_slot = 1
        request = bytes.fromhex('01010001010002000101')
        replies, event = state.handle(0x3e80, request)
        self.assertEqual(set(state.guns), {2})
        self.assertIs(state.guns[2], gun)
        self.assertEqual((state.hand_slot, state.selected_slot), (2, 2))
        self.assertEqual(len(replies[1][1]), 50)
        for invalid in (request, request[:-1], bytes.fromhex('01020001010002000101'),
                        bytes.fromhex('01010002010001000201'),
                        bytes.fromhex('01010002010001000100')):
            responses, result = state.handle(0x3e80, invalid)
            self.assertEqual(result['action'], 'rejected')
            self.assertEqual(set(state.guns), {2})
            self.assertIs(state.guns[2], gun)
        state.pending_reload = {'slot': 2}
        _, result = state.handle(0x3e80, bytes.fromhex('01010002010001000101'))
        self.assertEqual(result['reason'], 'move_reload_pending')
        self.assertIs(state.guns[2], gun)

    def test_pickup_replacing_reload_instance_cancels_before_deadline(self):
        state = self.recycling_state(definition=10201, quantity=1)
        state.fixture = replace(state.fixture, inventory_update='delta', reload_update='delta', timed_reload=True)
        state.hand_slot = 1
        state.clip = 1
        state.extra_ammunition[30001] = 20
        state.handle(0x49c, struct.pack('>I',1), now=10)
        self.assertIsNotNone(state.pending_reload)
        _, event = state.handle(0x3b63, self.pickup_request(15510))
        self.assertTrue(event['reload_cancelled_on_replace'])
        self.assertIsNone(state.pending_reload)
        self.assertEqual((state.guns[1].definition,state.clip,state.reserve,state.extra_ammunition[30001]),
                         (10201,0,6,20))
        old = state.loot_registry[event['discarded_index']]
        self.assertEqual((old.definition,old.clip), (10402,1))
        self.assertEqual(state.poll(20), ([],[]))
        _, event = state.handle(0x49c, struct.pack('>I',1), now=20)
        self.assertEqual(event['action'], 'reload_started')
        state.poll(22.567)
        self.assertEqual((state.clip,state.reserve,state.extra_ammunition.get(30001,0)), (20,6,0))

    def test_timed_reload_commits_once_and_switch_cancels_without_spending(self):
        state = self.recycling_state(definition=10201, quantity=1)
        state.fixture = replace(state.fixture, weapon_slots=2, reload_update='delta', timed_reload=True)
        state.extra_ammunition[30001] = 50
        state.handle(0x3b63, self.pickup_request(15510))
        state.handle(0x49e, struct.pack('>I', 2))
        replies, event = state.handle(0x49c, struct.pack('>I', 2), now=10)
        self.assertEqual(event['action'], 'reload_started')
        self.assertEqual((state.clip, state.extra_ammunition[30001]), (0, 50))
        self.assertEqual(state.poll(12.5), ([], []))
        state.handle(0x49c, struct.pack('>I', 2), now=12)
        replies, events = state.poll(12.567)
        self.assertEqual((state.clip, state.extra_ammunition[30001], events[0]['amount']), (30, 20, 30))
        self.assertEqual(state.poll(13), ([], []))
        state.clip = 29
        state.handle(0x49c, struct.pack('>I', 2), now=20)
        state.handle(0x49e, struct.pack('>I', 1))
        self.assertEqual(state.poll(25), ([], []))
        self.assertEqual((state.guns[2].clip, state.extra_ammunition[30001]), (29, 20))

    def test_reload_delta_preserves_hand_and_updates_only_matching_ammunition(self):
        state = self.recycling_state(definition=10201, quantity=1)
        state.fixture = replace(state.fixture, weapon_slots=2, reload_update='delta')
        state.extra_ammunition[30001] = 31
        state.handle(0x3b63, self.pickup_request(15510))
        state.handle(0x49e, struct.pack('>I', 2))
        replies, event = state.handle(0x49c, struct.pack('>I', 2))
        self.assertEqual([c for c, b in replies], [0x49d, 0x3e82, 0x4a0, 0x6f5])
        delta = dict(replies)[0x3e82]
        self.assertEqual((len(delta), delta[:4]), (71, bytes.fromhex('01000202')))
        self.assertEqual(struct.unpack_from('>I', delta, 6)[0], 30001)
        self.assertEqual(struct.unpack_from('>H', delta, len(delta)-11)[0], 1)
        self.assertEqual(struct.unpack('>QIII', dict(replies)[0x4a0]), (42, 2, 30, 0))
        self.assertEqual((state.hand_slot, state.guns[1].clip, state.reserve), (2, 2, 6))
        state.guns[2].clip = 29
        replies, _ = state.handle(0x49c, struct.pack('>I', 2))
        self.assertEqual(len(dict(replies)[0x3e82]), 50)
        self.assertEqual((state.clip, state.ammunition_quantity(30001)), (30, 0))

    def test_two_slots_alternate_reload_discard_repick_preserving_instances(self):
        state = self.recycling_state(definition=10201, quantity=1)
        state.fixture = replace(state.fixture, weapon_slots=2)
        state.extra_ammunition[30001] = 50
        state.guns[1].clip = 1
        original_uid = state.guns[1].uid
        replies, event = state.handle(0x3b63, self.pickup_request(15510))
        self.assertIsNone(event['discarded_index'])
        self.assertEqual(set(state.guns), {1, 2})
        self.assertEqual([(g.definition, g.clip) for g in state.guns.values()], [(10402, 1), (10201, 0)])
        self.assertEqual([struct.unpack('>QIII', b)[1:3] for c, b in replies if c == 0x4a0], [(1, 1), (2, 0)])
        state.handle(0x49e, struct.pack('>I', 2))
        state.handle(0x49c, struct.pack('>I', 2))
        self.assertEqual((state.guns[2].clip, state.extra_ammunition[30001], state.reserve), (30, 20, 6))
        state.handle(0x49e, struct.pack('>I', 1))
        state.handle(0x49c, struct.pack('>I', 1))
        self.assertEqual((state.guns[1].clip, state.guns[2].clip, state.reserve), (2, 30, 5))
        # Выброс неактивной M4 не меняет Citori в руках.
        uid = state.guns[2].uid
        _, event = state.handle(0x3e80, struct.pack('>BBBBHIIB', 2, 1, 0, 2, 1, 0, 0, 1))
        dropped = state.loot_registry[event['index']]
        self.assertEqual((dropped.clip, dropped.instance_uid, state.hand_slot), (30, uid, 1))
        state.handle(0x3b63, self.pickup_request(dropped.index))
        self.assertEqual((state.guns[2].clip, state.guns[2].uid, state.guns[1].uid), (30, uid, original_uid))
        # Fire выбирает руку, а не последнюю поднятую пушку.
        shot = struct.pack('>6fIBIIfII', 1,2,3,4,5,6,1,0,100,4,1,64,0)
        state.handle(0x11da, shot)
        self.assertEqual((state.guns[1].clip, state.guns[2].clip), (1, 30))
        state.handle(0x49e, struct.pack('>I', 2))
        self.assertEqual(state.handle(0x11da, shot)[1]['action'], 'duplicate_fire')

    def setUp(self):
        self.weapon = WeaponState(WeaponFixture(bytes(82), bytes(60)), 42)

    def test_m4_pickup_reload_drop_repick_preserves_magazine_and_ammunition_type(self):
        state = self.recycling_state(definition=10201, quantity=1)
        state.gun_owned = False
        state.extra_ammunition[30001] = 50
        request = struct.pack('>IIQBHB3iB', 15510, 0, 0, 0, 0, 1, 100, 200, 300, 0)
        _, event = state.handle(0x3b63, request)
        self.assertEqual(event['action'], 'pickup')
        self.assertEqual((state.gun_definition, state.clip, state.reserve), (10201, 0, 6))
        self.assertEqual(struct.unpack_from('>I', state.inventory(), 8)[0], 10201)
        state.handle(0x49e, struct.pack('>I', 1))
        state.handle(0x49c, struct.pack('>I', 1))
        self.assertEqual((state.clip, state.extra_ammunition[30001], state.reserve), (30, 20, 6))
        fire = struct.pack('>6fIBIIfII', 1, 2, 3, 4, 5, 6, 1, 0, 100, 4, 1, 64, 0)
        state.handle(0x11da, fire)
        discard = struct.pack('>BBBBHIIB', 2, 1, 0, 1, 1, 0, 0, 1)
        _, event = state.handle(0x3e80, discard)
        dropped = state.loot_registry[event['index']]
        self.assertEqual((dropped.definition, dropped.clip), (10201, 29))
        self.assertFalse(state.gun_owned)
        pickup = struct.pack('>IIQBHB3iB', dropped.index, 0, 0, 0, 0, 1, 100, 200, 300, 0)
        state.handle(0x3b63, pickup)
        self.assertEqual((state.gun_definition, state.clip, state.reserve), (10201, 29, 6))
        state.handle(0x49e, struct.pack('>I', 1))
        state.handle(0x49c, struct.pack('>I', 1))
        self.assertEqual((state.clip, state.extra_ammunition[30001], state.reserve), (30, 19, 6))

    def test_m4_cannot_reload_from_12ga_and_replaces_previous_gun_without_refilling(self):
        state = self.recycling_state(definition=10201, quantity=1)
        state.clip = 1
        request = struct.pack('>IIQBHB3iB', 15510, 0, 0, 0, 0, 1, 100, 200, 300, 0)
        replies, _ = state.handle(0x3b63, request)
        previous = state.loot_registry[70001]
        self.assertEqual((previous.definition, previous.clip), (10402, 1))
        self.assertIn(0x821, dict(replies))
        state.handle(0x49e, struct.pack('>I', 1))
        state.handle(0x49c, struct.pack('>I', 1))
        self.assertEqual((state.clip, state.reserve), (0, 6))

    def test_damaged_armor_survives_drop_repick_and_same_definition_replacement(self):
        for durability in (0, 1, 1230):
            with self.subTest(durability=durability):
                state = self.recycling_state(definition=201004, quantity=1)
                item = replace(state.fixture.loot, durability=durability)
                state.loot_registry[item.index] = item
                state.handle(0x3b63, self.pickup_request(item.index))
                self.assertEqual(state.equipment_durability[12], durability)
                discard = struct.pack('>BBBBHIIB', 2, 1, 0, 12, 1, 0, 0, 1)
                _, event = state.handle(0x3e80, discard)
                dropped = state.loot_registry[event['index']]
                self.assertEqual((dropped.definition, dropped.durability), (201004, durability))
                state.handle(0x3b63, self.pickup_request(dropped.index))
                self.assertEqual(state.equipment_durability[12], durability)
                new_item = replace(item, index=16000, entity_uid=1234, durability=500)
                state.loot_registry[new_item.index] = new_item
                state.available_loot.add(new_item.entity_uid)
                _, event = state.handle(0x3b63, self.pickup_request(new_item.index))
                self.assertEqual(state.equipment_durability[12], 500)
                old = state.loot_registry[70003]
                self.assertEqual((old.definition, old.durability), (201004, durability))
                drops = state.drop_counter
                state.handle(0x3b63, self.pickup_request(new_item.index))
                self.assertEqual((state.drop_counter, state.equipment_durability[12]), (drops, 500))
                record = equipment_record(bytes(82), 201004, 500)
                self.assertEqual(struct.unpack_from('>I', record, 32)[0], 500)

    def test_armor_pickup_replaces_slot_without_creating_ammunition(self):
        item=LootFixture(999,15510,1,(100,200,300),bytes(45),201003)
        state=WeaponState(WeaponFixture(bytes(82),bytes(60),loot=item,
                          starting_equipment=(200907,201001,200101)),42)
        state.loot_available=True
        request=struct.pack('>IIQBHB3iB',15510,0,0,0,0,1,100,200,300,0)
        replies,event=state.handle(0x3b63,request)
        self.assertEqual(event['action'],'pickup')
        self.assertEqual(state.equipment,{11:200907,12:201003,10:200101})
        self.assertEqual(state.reserve,6)
        self.assertEqual(state.handle(0x3b63,request)[1]['action'],'duplicate_pickup')
        self.assertEqual(state.reserve,6)
        inventory=dict(replies)[0x5fb]
        self.assertEqual(struct.unpack_from('>I',inventory)[0],5)
        record=equipment_record(bytes([255])*82,201003)
        self.assertEqual(record[:4],bytes((1,12,1,0)))
        self.assertEqual(record[16:32],bytes(16))
        self.assertEqual(struct.unpack_from('>I',record,32)[0],2500)
        self.assertEqual(record[36:80],bytes(44))
        self.assertEqual(struct.unpack_from('>H',record,80)[0],1)

    def test_each_winter_kit_enables_only_its_ability_and_own_capacity(self):
        # Три разных RAW_ATR, несмотря на другой порядок E_ABILITY в таблице.
        for definition, selected, capacity in [(200906,3,225),(200907,2,150),(200904,4,300)]:
            state = WeaponState(WeaponFixture(bytes(82),bytes(60),
                                starting_equipment=(definition,)),42)
            replies = state.kit_sync()
            raw = [struct.unpack('>II', body) for code, body in replies if code == 0x10d0]
            self.assertEqual(raw, [(i,int(i == selected)) for i in (2,3,4)])
            self.assertEqual(struct.unpack('>HBII', dict(replies)[0x516]), (1,5,capacity,capacity))
        self.assertEqual(self.weapon.kit_sync(), [])

    def test_pack_pickup_switches_capacity_and_disables_previous_ability_once(self):
        loot = LootFixture(999,15510,1,(100,200,300),bytes(45),200904)
        state = WeaponState(WeaponFixture(bytes(82),bytes(60),loot=loot,
                            starting_equipment=(200906,)),42)
        state.loot_available = True
        request = struct.pack('>IIQBHB3iB',15510,0,0,0,0,1,100,200,300,0)
        replies,event = state.handle(0x3b63,request)
        self.assertEqual(state.equipment[11],200904)
        self.assertEqual([struct.unpack('>II',b) for c,b in replies if c == 0x10d0],
                         [(2,0),(3,0),(4,1)])
        self.assertEqual(struct.unpack('>HBII',dict(replies)[0x516]),(1,5,300,300))
        duplicate,event = state.handle(0x3b63,request)
        self.assertEqual(event['action'],'duplicate_pickup')
        self.assertNotIn(0x10d0,dict(duplicate))
        self.assertEqual(state.reserve,6)

    def fire(self, counter, mode=0):
        return self.weapon.handle(0x11da, struct.pack('>6fIBIIfII',
                                  1, 2, 3, 4, 5, 6, counter, mode, 100, 4, 1, 64, 0))

    def test_fire_finish_duplicate_empty_and_reload_conserve_ammunition(self):
        self.weapon.handle(0x49e, struct.pack('>I', 1))
        _, event = self.fire(1)
        self.assertEqual((event['action'], self.weapon.clip), ('fire', 1))
        self.assertEqual(self.fire(2, 1)[1]['action'], 'fire_finish')
        self.assertEqual(self.fire(1)[1]['action'], 'duplicate_fire')
        modified_tick = struct.pack('>6fIBIIfII', 1,2,3,4,5,6,1,0,101,4,1,64,0)
        self.assertEqual(self.weapon.handle(0x11da, modified_tick)[1]['action'], 'duplicate_fire')
        self.fire(2)
        self.assertEqual(self.weapon.clip, 0)
        self.assertEqual(self.fire(3)[1]['action'], 'empty')
        replies, event = self.weapon.handle(0x49c, struct.pack('>I', 1))
        self.assertEqual((event['amount'], self.weapon.clip, self.weapon.reserve), (2, 2, 4))
        self.assertEqual([code for code, _ in replies], [0x49d, 0x5fb, 0x4a0, 0x49f, 0x6f5])
        self.assertEqual(struct.unpack('>I',dict(replies)[0x6f5])[0],5)
        inventory = replies[1][1]
        self.assertEqual(struct.unpack_from('>H', inventory, len(inventory)-11)[0], 4)
        self.assertEqual(struct.unpack('>QB', inventory[-9:]), (42, 1))
        self.assertEqual(struct.unpack('>QIII', replies[2][1]), (42, 1, 2, 0))
        self.assertEqual(self.weapon.handle(0x49c, struct.pack('>I', 1))[1]['amount'], 0)

    def test_wrong_slot_unarmed_and_malformed_do_not_change_ammunition(self):
        self.assertEqual(self.fire(1)[1]['action'], 'rejected')
        for command, payload in [(0x49e, struct.pack('>I', 2)),
                                 (0x49c, struct.pack('>I', 1)),
                                 (0x11da, bytes(48))]:
            self.assertEqual(self.weapon.handle(command, payload)[1]['action'], 'rejected')
        self.assertEqual((self.weapon.clip, self.weapon.reserve, self.weapon.hand_slot), (2, 6, 0))

    def test_last_shell_partial_reload_and_empty_bag(self):
        self.weapon.hand_slot = 1
        self.weapon.clip = 0
        self.weapon.reserve = 1
        self.weapon.handle(0x49c, struct.pack('>I', 1))
        self.assertEqual((self.weapon.clip, self.weapon.reserve), (1, 0))
        self.assertEqual(struct.unpack_from('>I', self.weapon.inventory())[0], 1)

    def test_ground_gun_is_unavailable_until_pickup(self):
        loot = LootFixture(999, 15530, 1, (100, 200, 300),
                           struct.pack('>IIIBI', 15530, 0, 1, 1, 10402) + bytes(28), 10402)
        state = WeaponState(WeaponFixture(bytes(82), bytes(60), loot=loot,
                                          gun_on_start=False), 42)
        self.assertFalse(state.gun_owned)
        self.assertEqual(struct.unpack_from('>I', state.inventory())[0], 1)
        state.hand_slot = 1
        self.assertEqual(state.handle(0x49c, struct.pack('>I', 1))[0], [])
        state.loot_available = True
        request = struct.pack('>IIQBHB3iB', 15530, 0, 0, 0, 0, 1, 100, 200, 300, 0)
        replies, event = state.handle(0x3b63, request)
        self.assertTrue(state.gun_owned)
        self.assertEqual((state.clip, state.reserve), (2, 6))
        state.clip = 1
        state.handle(0x3b63, request)
        self.assertEqual(state.clip, 1)

    def test_pickup_requires_spawn_proximity_and_matching_item_and_is_idempotent(self):
        loot = LootFixture(999, 15510, 10, (100, 200, 300),
                           struct.pack('>IIIBI', 15510, 0, 10, 1, 30004) + bytes(28))
        state = WeaponState(WeaponFixture(bytes(82), bytes(60), loot=loot), 42)
        def request(index=15510, position=(100, 200, 300), **changes):
            fields = {'slot':0, 'target':0, 'flag':1}; fields.update(changes)
            return struct.pack('>IIQBHB3iB', index, fields['slot'], fields['target'],
                               0, 0, fields['flag'], *position, 0)
        self.assertEqual(state.handle(0x3b63, request())[1]['action'], 'rejected')
        state.loot_available = True
        for bad in (request(index=15511), request(position=(850,200,300)),
                    request(slot=1), request(target=123), request(flag=0), request()[:-1]):
            self.assertEqual(state.handle(0x3b63, bad)[1]['action'], 'rejected')
            self.assertEqual(state.reserve, 6)
        replies, event = state.handle(0x3b63, request())
        self.assertEqual((event['action'], state.reserve), ('pickup', 16))
        self.assertEqual([code for code, _ in replies], [0x3b64, 0x5fb, 0x6f5, 0x4a0, 0x82b])
        self.assertEqual(replies[0][1], loot.acknowledgement)
        self.assertEqual(struct.unpack('>Q', dict(replies)[0x82b]), (999,))
        self.assertEqual(state.handle(0x3b63, request())[1]['action'], 'duplicate_pickup')
        self.assertEqual(state.reserve, 16)

    def test_fixture_loader_validates_variant_and_reads_quantity(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            gun = bytearray(95); gun[:8] = bytes.fromhex('0000000101010100')
            struct.pack_into('>I', gun, 8, 10402); gun[-1] = 1
            ammo = bytearray(73); ammo[:8] = bytes.fromhex('0000000102010200')
            struct.pack_into('>I', ammo, 8, 30004); ammo[-1] = 1
            struct.pack_into('>H', ammo, len(ammo)-11, 17)
            (folder/'gun.bin').write_bytes(gun); (folder/'ammo.bin').write_bytes(ammo)
            path = folder/'config.json'
            path.write_text(json.dumps({'gun_inventory_file':'gun.bin',
                                        'ammunition_inventory_file':'ammo.bin'}))
            fixture = WeaponFixture.load(path)
            self.assertEqual((len(fixture.gun),len(fixture.ammunition),fixture.reserve), (82,60,17))
            ammo[11] ^= 1; (folder/'ammo.bin').write_bytes(ammo)
            with self.assertRaises(ValueError):
                WeaponFixture.load(path)

    def test_distinct_loot_points_have_independent_spawn_and_pickup_state(self):
        def item(uid, index, quantity, x):
            return LootFixture(uid, index, quantity, (x, 0, 0),
                               struct.pack('>IIIBI', index, 0, quantity, 1, 30004) + bytes(28))
        first, second = item(900, 15510, 10, 0), item(901, 15511, 5, 2000)
        state = WeaponState(WeaponFixture(bytes(82), bytes(60), loot=first,
                                        additional_loot=(second,)), 42)
        def request(index, x):
            return struct.pack('>IIQBHB3iB', index, 0, 0, 0, 0, 1, x, 0, 0, 0)
        state.available_loot.add(second.entity_uid)
        self.assertEqual(state.handle(0x3b63, request(first.index, 0))[1]['action'], 'rejected')
        replies, event = state.handle(0x3b63, request(second.index, 2000))
        self.assertEqual((event['action'], state.reserve), ('pickup', 11))
        self.assertEqual(struct.unpack('>Q', replies[-1][1])[0], second.entity_uid)
        state.available_loot.add(first.entity_uid)
        state.handle(0x3b63, request(first.index, 0))
        self.assertEqual(state.reserve, 21)
        state.handle(0x3b63, request(second.index, 2000))
        self.assertEqual(state.reserve, 21)

    def recycling_state(self, definition=30004, quantity=20):
        # Минимальный публичный821 из той же проверенной схемы.
        body = bytearray(100)
        struct.pack_into('>IQI',body,0,30201002,999,13)
        struct.pack_into('>3i',body,29,100,200,300)
        struct.pack_into('>I',body,46,1); body[62]=2
        struct.pack_into('>III',body,63,definition,quantity,15510)
        item=LootFixture(999,15510,quantity,(100,200,300),bytes(45),definition,bytes(body))
        state=WeaponState(WeaponFixture(bytes(82),bytes(60),loot=item,
                           starting_equipment=(200907,201001,200101)),42)
        state.available_loot.add(999)
        state.update_position((100,200,300))
        return state

    def pickup_request(self, index):
        return struct.pack('>IIQBHB3iB',index,0,0,0,0,1,100,200,300,0)

    def test_partial_pickup_full_bag_drop_repick_conserve_all_rounds(self):
        state=self.recycling_state()
        state.reserve=110
        request=self.pickup_request(15510)
        replies,event=state.handle(0x3b63,request)
        self.assertEqual((event['quantity'],event['remaining'],state.reserve),(10,10,120))
        self.assertEqual(state.loot_registry[15510].quantity,10)
        self.assertEqual(struct.unpack('>I',dict(replies)[0x6f5])[0],150)
        full,event=state.handle(0x3b63,request)
        self.assertEqual((event['quantity'],state.reserve),(0,120))
        self.assertNotIn(0x82b,dict(full))
        drop=struct.pack('>BBBBHIIB',2,2,0,1,5,0,0,1)
        replies,event=state.handle(0x3e80,drop)
        index=event['index']
        self.assertEqual((event['action'],state.reserve),('discard',115))
        self.assertEqual(state.loot_registry[index].position,(100,200,300))
        self.assertEqual(struct.unpack_from('>III',dict(replies)[0x821],63),(30004,5,index))
        state.handle(0x3b63,self.pickup_request(index))
        self.assertEqual(state.reserve,120)
        state.handle(0x3b63,self.pickup_request(index))
        self.assertEqual(state.reserve,120)
        self.assertEqual(state.reserve+state.loot_registry[15510].quantity,130)

    def test_second_ammunition_has_own_slot_weight_and_does_not_feed_citori(self):
        state=self.recycling_state(definition=30001,quantity=100)
        state.reserve=110
        request=self.pickup_request(15510)
        replies,event=state.handle(0x3b63,request)
        self.assertEqual((event['quantity'],event['remaining'],state.reserve),(25,75,110))
        self.assertEqual(state.extra_ammunition,{30001:25})
        self.assertEqual(struct.unpack('>I',dict(replies)[0x6f5])[0],150)
        record=state.inventory()[-69:-9]
        self.assertEqual(struct.unpack_from('>BBBBI',record),(2,2,2,0,30001))
        self.assertEqual(struct.unpack_from('>H',record,58)[0],25)
        # Собственный slot2: drop10 сохраняет12ga и magazine.
        packets,event=state.handle(0x3e80,struct.pack('>BBBBHIIB',2,2,0,2,10,0,0,1))
        index=event['index']
        self.assertEqual((state.reserve,state.extra_ammunition,state.clip),(110,{30001:15},2))
        self.assertEqual((state.loot_registry[index].definition,state.loot_registry[index].quantity),(30001,10))
        state.hand_slot=1;state.clip=1
        state.handle(0x49c,struct.pack('>I',1))
        self.assertEqual((state.reserve,state.extra_ammunition,state.clip),(109,{30001:15},2))
        state.handle(0x3b63,request)
        self.assertEqual((state.extra_ammunition[30001],state.loot_registry[15510].quantity),(27,63))
        self.assertEqual(27+63+state.loot_registry[index].quantity,100)

    def test_last_second_ammunition_drop_clears_only_slot2(self):
        state=self.recycling_state(definition=30001,quantity=10)
        state.handle(0x3b63,self.pickup_request(15510))
        packets,event=state.handle(0x3e80,struct.pack('>BBBBHIIB',2,2,0,2,10,0,0,1))
        self.assertEqual(state.extra_ammunition,{})
        self.assertEqual((state.reserve,state.clip),(6,2))
        self.assertEqual(dict(packets)[0x3e82][:4],bytes.fromhex('01000202'))
        self.assertEqual(state.loot_registry[event['index']].definition,30001)

    def test_armor_replacement_returns_old_item_once_and_supports_repick(self):
        state=self.recycling_state(201003,1)
        replies,event=state.handle(0x3b63,self.pickup_request(15510))
        old_index=event['discarded_index']
        self.assertEqual(state.equipment[12],201003)
        self.assertEqual(state.loot_registry[old_index].definition,201001)
        before=len(state.loot_registry)
        state.handle(0x3b63,self.pickup_request(15510))
        self.assertEqual(len(state.loot_registry),before)
        _,event=state.handle(0x3b63,self.pickup_request(old_index))
        self.assertEqual(state.equipment[12],201001)
        self.assertEqual(state.loot_registry[event['discarded_index']].definition,201003)
        self.assertEqual(state.reserve,6)

    def test_bad_discard_does_not_remove_inventory_or_spawn_entities(self):
        state=self.recycling_state()
        for payload in (bytes(14),struct.pack('>BBBBHIIB',2,2,0,1,7,0,0,1),
                        struct.pack('>BBBBHIIB',2,1,0,11,1,0,0,1),
                        struct.pack('>BBBBHIIB',2,2,0,1,5,1,0,1)):
            self.assertEqual(state.handle(0x3e80,payload)[1]['action'],'rejected')
            self.assertEqual((state.reserve,len(state.loot_registry)),(6,1))
        state.position=None
        self.assertEqual(state.handle(0x3e80,struct.pack('>BBBBHIIB',2,2,0,1,5,0,0,1))[1]['action'],'rejected')

    def test_discard_gun_repick_and_replace_preserve_magazine_rounds(self):
        state=self.recycling_state(10402,1)
        state.clip=1
        drop=struct.pack('>BBBBHIIB',2,1,0,1,1,0,0,1)
        packets,event=state.handle(0x3e80,drop)
        index=event['index']
        self.assertFalse(state.gun_owned)
        self.assertEqual(state.loot_registry[index].clip,1)
        self.assertEqual((state.clip,state.hand_slot,state.reserve),(0,0,6))
        self.assertEqual(dict(packets)[0x3e82][1:4],struct.pack('>HB',1,1))
        packets,event=state.handle(0x3b63,self.pickup_request(index))
        self.assertEqual((state.gun_owned,state.clip,state.reserve),(True,1,6))
        self.assertEqual(struct.unpack('>QIII',dict(packets)[0x4a0]),(42,1,1,0))
        packets,event=state.handle(0x3b63,self.pickup_request(15510))
        previous=state.loot_registry[event['discarded_index']]
        self.assertEqual((state.clip,previous.clip,state.reserve),(2,1,6))
        before=len(state.loot_registry)
        state.handle(0x3b63,self.pickup_request(15510))
        self.assertEqual((state.clip,len(state.loot_registry)),(2,before))

    def test_last_ammo_discard_and_reload_explicitly_clear_slot(self):
        state=self.recycling_state()
        payload=struct.pack('>BBBBHIIB',2,2,0,1,6,0,0,1)
        packets,_=state.handle(0x3e80,payload)
        self.assertEqual((state.reserve,state.clip),(0,2))
        self.assertEqual(len(dict(packets)[0x3e82]),50)
        self.assertEqual(dict(packets)[0x3e82][1:4],struct.pack('>HB',1,2))
        self.assertEqual(struct.unpack('>QIII',dict(packets)[0x4a0]),(42,1,2,0))
        state.reserve=1;state.clip=1;state.hand_slot=1
        packets,_=state.handle(0x49c,struct.pack('>I',1))
        self.assertIn(0x3e82,dict(packets))
        self.assertEqual((state.reserve,state.clip),(0,2))

    def test_delta_medical_pickup_drop_repick_preserves_active_second_weapon(self):
        from dataclasses import replace
        from weapon_probe_2022 import GunInstance
        state=self.recycling_state(definition=70001,quantity=5)
        state.fixture=replace(state.fixture,inventory_update='delta',weapon_slots=2)
        state.guns[2]=GunInstance(10201,17,77)
        state.selected_slot=state.hand_slot=2
        packets,_=state.handle(0x3b63,self.pickup_request(15510))
        self.assertNotIn(0x5fb,dict(packets))
        self.assertEqual((state.selected_slot,state.hand_slot,state.clip,state.medical[70001]),(2,2,17,5))
        payload=struct.pack('>BBBBHIIB',2,2,0,3,2,0,0,1)
        packets,event=state.handle(0x3e80,payload)
        self.assertNotIn(0x5fb,dict(packets))
        self.assertEqual((state.medical[70001],state.clip,state.hand_slot),(3,17,2))
        packets,_=state.handle(0x3b63,self.pickup_request(event['index']))
        self.assertEqual((state.medical[70001],state.clip,state.hand_slot),(5,17,2))
        state.handle(0x3b63,self.pickup_request(event['index']))
        self.assertEqual((state.medical[70001],state.reserve),(5,6))

    def test_delta_spare_gun_pickup_does_not_redirect_active_gun_fire(self):
        from dataclasses import replace
        state=self.recycling_state(definition=10201,quantity=1)
        state.fixture=replace(state.fixture,inventory_update='delta',weapon_slots=2)
        state.hand_slot=1
        state.handle(0x3b63,self.pickup_request(15510))
        self.assertEqual((state.selected_slot,state.hand_slot,state.guns[2].clip),(1,1,0))
        self.assertEqual(state.gun_definition,10402)


if __name__ == '__main__':
    unittest.main()
