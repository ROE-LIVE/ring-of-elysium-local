"""Оборот экземпляров обвеса, границы и сохранение при drop/handoff."""
from dataclasses import replace
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server/directory'))
from attachment_probe_2022 import AttachmentInstance, gun_attachment_record
from weapon_probe_2022 import GunInstance
import test_weapon_probe_2022 as weapon_tests


class AttachmentTests(unittest.TestCase):
    def test_sniper_extended_capacity_comes_from_original_table(self):
        for definition in (10101, 10102):
            state = self.state(40401)
            state.guns[2] = GunInstance(definition, 5, 77)
            _, event = state.handle(0x3e80, self.install(point=3))
            self.assertEqual(event['action'], 'attachment_installed')
            self.assertEqual(state.magazine_capacity, 10)

    def test_native_bag_instance_uid_installs_and_stale_uid_is_atomic(self):
        state = self.state(40405)
        state.guns[2] = GunInstance(10303, 19, 77)
        part = state.attachments[20]
        wrong = struct.pack('>BQBHQBHHB', 6, part.uid + 1, 2, 20, 77, 3, 3, 1, 1)
        before = state.inventory_records()
        self.assertEqual(state.handle(0x3e80, wrong)[1]['reason'], 'attachment_source_uid')
        self.assertEqual(state.inventory_records(), before)
        request = struct.pack('>BQBHQBHHB', 6, part.uid, 2, 20, 77, 3, 3, 1, 1)
        _, event = state.handle(0x3e80, request)
        self.assertEqual(event['action'], 'attachment_installed')
        self.assertIs(state.guns[2].parts[3], part)
        self.assertFalse(state.attachments)
        self.assertEqual(state.handle(0x3e80, request)[1]['reason'], 'attachment_source')

    def test_smg_magazine_uses_table_capacity_and_returns_overflow_on_removal(self):
        state = self.state(40405)
        state.guns[2] = GunInstance(10303, 19, 77)
        state.set_ammunition_quantity(30003, 20)
        _, event = state.handle(0x3e80, self.install(point=3))
        self.assertEqual(event['action'], 'attachment_installed')
        self.assertEqual(state.magazine_capacity, 33)
        state.handle(0x49c, struct.pack('>I', 2))
        self.assertEqual((state.clip, state.ammunition_quantity(30003)), (33, 6))
        _, event = state.handle(0x3e80, self.remove(point=3))
        self.assertEqual(event['action'], 'attachment_removed')
        self.assertEqual((state.clip, state.ammunition_quantity(30003)), (19, 20))

    def state(self, definition=40305):
        state = weapon_tests.WeaponStateTests().recycling_state(definition, 1)
        state.fixture = replace(state.fixture, weapon_slots=2, inventory_update='delta')
        state.guns[2] = GunInstance(10201, 17, 77)
        state.selected_slot = state.hand_slot = 2
        state.handle(0x3b63, weapon_tests.WeaponStateTests().pickup_request(15510))
        return state

    def install(self, source=20, gun=77, point=2):
        return struct.pack('>BQBHQBHHB', 6, 0, 2, source, gun, 3, point, 1, 1)

    def remove(self, gun=77, point=2, target=0):
        return struct.pack('>BQBHQBHHB', 6, gun, 3, point, 0, 2, target, 1, 1)

    def test_install_remove_conserve_uids_clip_and_weight(self):
        state = self.state()
        part = state.attachments[20]
        before = state.bag_weight_hundredths()
        replies, event = state.handle(0x3e80, self.install())
        self.assertEqual(event['action'], 'attachment_installed')
        self.assertIs(state.guns[2].parts[2], part)
        self.assertFalse(state.attachments)
        self.assertEqual(state.bag_weight_hundredths(), before - 1000)
        self.assertEqual((state.guns[2].uid, state.clip, state.reserve, state.hand_slot), (77, 17, 6, 2))
        gun_delta = replies[2][1]
        self.assertEqual(len(gun_delta), 105)
        record = next(r for r in state.inventory_records() if r[:2] == b'\x01\x02')
        self.assertEqual(struct.unpack_from('>I', record, 64)[0], 1)
        self.assertEqual(struct.unpack_from('>III', record, 68), (2, 40305, 0))
        _, event = state.handle(0x3e80, self.remove())
        self.assertEqual(event['action'], 'attachment_removed')
        self.assertIs(state.attachments[20], part)
        self.assertEqual((state.guns[2].parts, state.bag_weight_hundredths()), ({}, before))
        self.assertEqual(state.handle(0x3e80, self.remove())[1]['action'], 'rejected')

    def test_incompatible_malformed_reload_and_full_bag_are_atomic(self):
        state = self.state()
        original = dict(state.attachments)
        for request in (self.install(gun=999), self.install(gun=state.guns[1].uid),
                        self.install(point=0), self.install()[:-1], self.install()[:-1]+b'\x00'):
            self.assertEqual(state.handle(0x3e80, request)[1]['action'], 'rejected')
            self.assertEqual(state.attachments, original)
            self.assertFalse(state.guns[2].parts)
        state.pending_reload = {'slot':2}
        self.assertEqual(state.handle(0x3e80, self.install())[1]['reason'], 'attachment_reload_pending')
        state.pending_reload = None
        state.handle(0x3e80, self.install())
        state.reserve = 180
        self.assertEqual(state.handle(0x3e80, self.remove())[1]['reason'], 'attachment_bag_full')
        self.assertTrue(state.guns[2].parts)
        self.assertFalse(state.attachments)
        sr = self.state(40101)
        self.assertEqual(sr.handle(0x3e80, self.install(point=0))[1]['reason'], 'incompatible_attachment')

    def test_replacement_and_gun_drop_repick_preserve_part_instances(self):
        state = self.state()
        state.handle(0x3e80, self.install())
        old = state.guns[2].parts[2]
        replacement = AttachmentInstance(40305, 88)
        state.attachments[21] = replacement
        state.known_attachment_slots.add(21)
        state.handle(0x3e80, self.install(source=21))
        self.assertIs(state.attachments[21], old)
        self.assertIs(state.guns[2].parts[2], replacement)
        _, event = state.handle(0x3e80, struct.pack('>BBBBHIIB', 2,1,0,2,1,0,0,1))
        ground = state.loot_registry[event['index']]
        self.assertEqual((ground.instance_uid, ground.clip, dict(ground.parts)[2]), (77,17,replacement))
        state.handle(0x3b63, weapon_tests.WeaponStateTests().pickup_request(event['index']))
        self.assertIs(state.guns[2].parts[2], replacement)
        self.assertEqual((state.guns[2].uid, state.guns[2].clip), (77,17))

    def test_part_drop_repick_duplicate_and_handoff_known_slots(self):
        state = self.state()
        part = state.attachments[20]
        _, event = state.handle(0x3e80, struct.pack('>BBBBHIIB',2,2,0,20,1,0,0,1))
        self.assertFalse(state.attachments)
        clears = [(struct.unpack_from('>H',b,1)[0], b[3]) for c,b in state.reconcile_inventory()
                  if c == 0x3e82 and len(b) == 50]
        self.assertIn((20,2), clears)
        self.assertNotIn((63,2), clears)
        request = weapon_tests.WeaponStateTests().pickup_request(event['index'])
        state.handle(0x3b63, request)
        state.handle(0x3b63, request)
        self.assertEqual(list(state.attachments.values()), [part])
        self.assertEqual(state.guns[2].clip, 17)

    def test_record_rejects_wrong_point_and_unproven_magazine(self):
        state = self.state()
        with self.assertRaises(ValueError):
            gun_attachment_record(state.fixture.gun, {0: AttachmentInstance(40305, 1)})
        state.attachments[21] = AttachmentInstance(40401, 90)
        self.assertEqual(state.handle(0x3e80, self.install(source=21,point=3))[1]['reason'], 'incompatible_attachment')

class ExtendedMagazineTests(unittest.TestCase):
    state = AttachmentTests.state
    install = AttachmentTests.install
    remove = AttachmentTests.remove

    def test_extended_reload_remove_and_repeat_conserve_ammunition(self):
        state = self.state(40403)
        state.extra_ammunition[30001] = 50
        state.fixture = replace(state.fixture, reload_update='delta', timed_reload=True)
        _, event = state.handle(0x3e80, self.install(point=3))
        self.assertEqual(event['action'], 'attachment_installed')
        self.assertEqual(state.magazine_capacity, 40)
        state.handle(0x49c, struct.pack('>I', 2), now=10)
        state.poll(20)
        self.assertEqual((state.clip, state.extra_ammunition[30001]), (40, 27))
        uid = state.guns[2].uid
        _, event = state.handle(0x3e80, self.remove(point=3))
        self.assertEqual((event['returned_ammunition'],state.clip,state.extra_ammunition[30001]), (10,30,37))
        self.assertEqual(state.magazine_capacity,30)
        self.assertEqual(state.guns[2].uid,uid)
        self.assertEqual(state.handle(0x3e80,self.remove(point=3))[1]['action'],'rejected')
        self.assertEqual((state.clip,state.extra_ammunition[30001]),(30,37))

    def test_extended_overflow_capacity_and_stack_reject_without_mutation(self):
        state = self.state(40403)
        state.handle(0x3e80,self.install(point=3))
        state.clip = 40
        state.extra_ammunition[30001] = 999
        before = dict(state.guns[2].parts)
        self.assertEqual(state.handle(0x3e80,self.remove(point=3))[1]['reason'],'attachment_bag_full')
        self.assertEqual((state.clip,state.guns[2].parts),(40,before))
        state.extra_ammunition[30001] = 0
        state.reserve = (state.bag_capacity * 100 - 1500) // state.ammunition_weight(30004)
        self.assertEqual(state.handle(0x3e80,self.remove(point=3))[1]['reason'],'attachment_overflow_bag_full')
        self.assertEqual((state.clip,state.guns[2].parts),(40,before))

    def test_extended_offhand_remove_and_drop_repick_preserve_identity(self):
        state = self.state(40403)
        state.handle(0x3e80,self.install(point=3))
        state.clip = 38
        uid = state.guns[2].uid
        part = state.guns[2].parts[3]
        _, event = state.handle(0x3e80,struct.pack('>BBBBHIIB',2,1,0,2,1,0,0,1))
        ground = state.loot_registry[event['index']]
        self.assertEqual((ground.clip,ground.instance_uid,dict(ground.parts)[3]),(38,uid,part))
        state.handle(0x3b63,weapon_tests.WeaponStateTests().pickup_request(event['index']))
        state.selected_slot = 2
        self.assertEqual((state.guns[2].uid,state.clip,state.magazine_capacity),(uid,38,40))
        state.selected_slot = state.hand_slot = 1
        _, event = state.handle(0x3e80,self.remove(point=3))
        self.assertEqual((event['returned_ammunition'],state.guns[2].clip,state.extra_ammunition[30001]),(8,30,8))
        self.assertEqual((state.selected_slot,state.hand_slot),(1,1))
        self.assertIs(state.attachments[20],part)


class GroundAttachmentTests(unittest.TestCase):
    def state(self, definition=40305):
        state = weapon_tests.WeaponStateTests().recycling_state(definition,1)
        state.fixture = replace(state.fixture,weapon_slots=3,inventory_update='delta')
        state.guns[2] = GunInstance(10201,17,77)
        state.selected_slot = state.hand_slot = 1
        return state

    def request(self,index=15510,gun=77,point=2,position=(100,200,300)):
        return struct.pack('>IIQBHB3iB',index,0,gun,3,point,0,*position,0)

    def test_ground_to_offhand_gun_does_not_use_bag_and_preserves_clip_and_hand(self):
        state=self.state();state.reserve=state.bag_capacity*100//state.ammunition_weight(30004)
        before=state.bag_weight_hundredths()
        replies,event=state.handle(0x3b63,self.request())
        self.assertEqual(event['pickup_mode'],'manual_attachment')
        self.assertEqual((event['action'],event['part_index'],event['gun_slot']),('pickup',2,2))
        self.assertEqual((state.guns[2].uid,state.guns[2].clip,state.hand_slot),(77,17,1))
        self.assertEqual(state.guns[2].parts[2].definition,40305)
        self.assertFalse(state.attachments)
        self.assertEqual(state.bag_weight_hundredths(),before)
        self.assertIn(15510,state.picked_loot)
        self.assertEqual(replies[0][0],0x3b64)
        self.assertIn(0x3e82,[c for c,_ in replies])
        self.assertIn((0x82b,struct.pack('>Q',state.fixture.loot.entity_uid)),replies)

    def test_duplicate_ground_request_keeps_identity_and_does_not_replace_again(self):
        state=self.state();state.guns[2].parts[2]=AttachmentInstance(40303,1001)
        state.handle(0x3b63,self.request())
        part=state.guns[2].parts[2];before=state.inventory_records()
        _,event=state.handle(0x3b63,self.request())
        self.assertEqual(event['action'],'duplicate_pickup')
        self.assertIs(state.guns[2].parts[2],part)
        self.assertEqual(state.inventory_records(),before)
        self.assertEqual([x.uid for x in state.attachments.values()],[1001])

    def test_replacement_returns_old_part_and_preserves_all_instance_uids(self):
        state=self.state();old=AttachmentInstance(40303,1001);state.guns[2].parts[2]=old
        _,event=state.handle(0x3b63,self.request())
        self.assertEqual((event['returned_attachment'],event['returned_attachment_slot']),(40303,20))
        self.assertIs(state.attachments[20],old)
        self.assertEqual(state.guns[2].parts[2].definition,40305)
        self.assertNotEqual(state.guns[2].parts[2].uid,old.uid)

    def test_full_bag_replacement_is_atomic(self):
        state=self.state();old=AttachmentInstance(40303,1001);state.guns[2].parts[2]=old
        state.reserve=state.bag_capacity*100//state.ammunition_weight(30004)
        before=state.inventory_records()
        _,event=state.handle(0x3b63,self.request())
        self.assertEqual(event['reason'],'attachment_bag_full')
        self.assertEqual(state.inventory_records(),before)
        self.assertIs(state.guns[2].parts[2],old)
        self.assertNotIn(15510,state.picked_loot)

    def test_unknown_gun_incompatible_part_and_pending_reload_do_not_consume_ground(self):
        for mode,reason in [('unknown','attachment_target_uid'),('incompatible','incompatible_attachment'),('reload','attachment_reload_pending')]:
            with self.subTest(mode=mode):
                state=self.state()
                if mode=='incompatible':state.guns[2]=GunInstance(10402,2,77)
                if mode=='reload':state.pending_reload={'slot':1}
                before=state.inventory_records()
                _,event=state.handle(0x3b63,self.request(gun=9999 if mode=='unknown' else 77))
                self.assertEqual(event['reason'],reason)
                self.assertNotIn(15510,state.picked_loot)
                self.assertEqual(state.inventory_records(),before)

    def test_wrong_point_distance_and_stacked_ground_are_rejected(self):
        for mode,reason in [('point','incompatible_attachment'),('distance','pickup_fixture_or_distance'),('stack','attachment_ground_stack')]:
            with self.subTest(mode=mode):
                state=self.state()
                if mode=='stack':
                    loot=replace(state.fixture.loot,quantity=2)
                    state.fixture=replace(state.fixture,loot=loot);state.loot_registry[loot.index]=loot
                _,event=state.handle(0x3b63,self.request(point=0 if mode=='point' else 2,position=(9999,200,300) if mode=='distance' else (100,200,300)))
                self.assertEqual(event['reason'],reason)
                self.assertFalse(state.guns[2].parts)
                self.assertNotIn(15510,state.picked_loot)

    def test_ground_extended_magazine_increases_capacity_without_refilling_clip(self):
        state=self.state(40403)
        _,event=state.handle(0x3b63,self.request(point=3))
        state.selected_slot=2
        self.assertEqual((state.magazine_capacity,state.clip),(40,17))
        self.assertEqual(event['quantity'],1)

    def test_dropped_attachment_identity_survives_direct_install(self):
        state=self.state()
        state.handle(0x3b63,weapon_tests.WeaponStateTests().pickup_request(15510))
        part=state.attachments[20]
        _,drop=state.handle(0x3e80,struct.pack('>BBBBHIIB',2,2,0,20,1,0,0,1))
        state.handle(0x3b63,self.request(index=drop['index']))
        self.assertEqual(state.guns[2].parts[2].uid,part.uid)
        self.assertFalse(state.attachments)
