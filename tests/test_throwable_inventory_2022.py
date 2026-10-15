"""Формат гранат, частичный pickup и сохранение количества без действий броска."""
import struct
import unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server/directory'))
from inventory_codec_2022 import decode_item, decode_delta, decode_snapshot
from throwable_inventory_2022 import THROWABLE_PROFILES, THROWABLE_SLOTS, throwable_record
import test_weapon_probe_2022 as weapon_tests


class ThrowableInventoryTests(unittest.TestCase):
    def move(self,sc,source,dc,destination,quantity=1):
        return struct.pack('>BBHBHHB',1,sc,source,dc,destination,quantity,1)

    def test_equipment_move_replacement_restore_and_drop_conserve_weight(self):
        state=self.state(quantity=2)
        state.handle(0x3b63,weapon_tests.WeaponStateTests().pickup_request(15510))
        state.throwables[50002]=2
        before=state.bag_weight_hundredths()
        _,event=state.handle(0x3e80,self.move(2,11,1,5))
        self.assertEqual(event['action'],'throwable_moved')
        self.assertEqual((state.throwables,state.equipped_throwables),({50001:1,50002:2},{5:(50001,1)}))
        self.assertEqual(state.bag_weight_hundredths(),before)
        state.handle(0x49e,struct.pack('>I',5));self.assertEqual(state.hand_slot,5)
        state.handle(0x3e80,self.move(2,12,1,5))
        self.assertEqual((state.throwables,state.equipped_throwables),({50001:2,50002:1},{5:(50002,1)}))
        records=decode_snapshot(state.inventory()).entries
        self.assertEqual(next(e.item.definition for e in records if (e.container,e.slot)==(1,5)),50002)
        deltas=[decode_delta(p) for c,p in state.reconcile_inventory() if c==0x3e82]
        self.assertEqual(next(e.item.quantity for m in deltas for e in m.entries if (e.container,e.slot)==(1,5)),1)
        replies,_=state.handle(0x3e80,self.move(1,5,2,12))
        self.assertEqual(state.hand_slot,0);self.assertIn((0x49f,bytes(8)),replies)
        self.assertEqual(state.throwables,{50001:2,50002:2})
        state.handle(0x3e80,self.move(2,11,1,6))
        state.handle(0x49e,struct.pack('>I',6))
        _,event=state.handle(0x3e80,struct.pack('>BBHHQB',2,1,6,1,0,1))
        self.assertEqual(event['action'],'discard');self.assertEqual(state.hand_slot,0)
        self.assertFalse(state.equipped_throwables)
        self.assertEqual(state.bag_weight_hundredths()+1200,before)

    def test_bad_equipment_moves_are_atomic_and_keep_weapon_hand(self):
        state=self.state(quantity=2)
        state.handle(0x3b63,weapon_tests.WeaponStateTests().pickup_request(15510))
        before=state.inventory_records()
        for payload in (self.move(2,11,1,3),self.move(2,11,1,5,3),self.move(1,5,2,11),self.move(2,11,2,12)):
            _,event=state.handle(0x3e80,payload)
            self.assertEqual(event['action'],'rejected');self.assertEqual(state.inventory_records(),before)
        state.pending_reload={'slot':1}
        self.assertEqual(state.handle(0x3e80,self.move(2,11,1,5))[1]['reason'],'throwable_move_reload_pending')
        self.assertEqual(state.inventory_records(),before)

    def state(self, definition=50001, quantity=10):
        return weapon_tests.WeaponStateTests().recycling_state(definition, quantity)

    def test_record_matches_pure_native_variant_and_table_limits(self):
        for definition in THROWABLE_PROFILES:
            record=throwable_record(definition,2)
            parsed=decode_item(record[2:])
            self.assertEqual((len(record),record[0],record[1]),(73,2,THROWABLE_SLOTS[definition]))
            self.assertEqual((parsed.item_type,parsed.category,parsed.definition,parsed.quantity),(2,5,definition,2))
            for quantity in (0,101,True,1.5):
                with self.assertRaises(ValueError):throwable_record(definition,quantity)

    def test_partial_pickup_drop_repick_and_duplicate_conserve_quantity(self):
        state=self.state();state.equipment.pop(11);state.reserve=1
        _,event=state.handle(0x3b63,weapon_tests.WeaponStateTests().pickup_request(15510))
        self.assertEqual((event['quantity'],event['remaining']),(8,2))
        self.assertEqual(state.throwables,{50001:8})
        self.assertEqual(state.bag_weight_hundredths(),9725)
        self.assertEqual(decode_snapshot(state.inventory()).entries[-1].item.quantity,8)
        before=state.inventory_records()
        for quantity in (0,9):
            _,event=state.handle(0x3e80,struct.pack('>BBHHQB',2,2,11,quantity,0,1))
            self.assertEqual(event['action'],'rejected');self.assertEqual(state.inventory_records(),before)
        _,event=state.handle(0x3e80,struct.pack('>BBHHQB',2,2,11,3,0,1))
        self.assertEqual(event['action'],'discard')
        dropped=state.loot_registry[event['index']]
        self.assertEqual(state.throwables[50001]+dropped.quantity+state.loot_registry[15510].quantity,10)
        request=weapon_tests.WeaponStateTests().pickup_request(dropped.index)
        state.handle(0x3b63,request)
        _,event=state.handle(0x3b63,request)
        self.assertEqual(event['action'],'duplicate_pickup')
        self.assertEqual(state.throwables,{50001:8})
        self.assertEqual(state.bag_weight_hundredths(),9725)
        state.handle(0x3e80,struct.pack('>BBHHQB',2,2,11,8,0,1))
        sync=[decode_delta(p) for c,p in state.reconcile_inventory() if c==0x3e82]
        item=next(e.item for m in sync for e in m.entries if (e.container,e.slot)==(2,11))
        self.assertEqual((item.item_type,item.quantity),(0,0))

    def test_stack_max_and_unsupported_throw_do_not_mutate_inventory(self):
        state=self.state();state.throwables[50001]=100
        self.assertEqual(state.throwable_room(50001),0)
        before=state.inventory_records()
        replies,event=state.handle(0xdead,b'own test payload')
        self.assertEqual(replies,[]);self.assertEqual(state.inventory_records(),before)
