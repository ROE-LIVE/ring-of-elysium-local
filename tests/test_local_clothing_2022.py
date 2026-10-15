"""Сохранность гардероба, нативные ссылки и отказ на чужой категории2022."""
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
sys.path.insert(0,str(ROOT/'server/directory'))
from inventory_codec_2022 import decode_delta, decode_snapshot
from local_clothing_2022 import ClothingSelection
from local_cosmetics_2022 import LocalCosmetics


def move(sc,source,dc,destination,quantity=1,own=0):
    return struct.pack('>BBHBHHB',1,sc,source,dc,destination,quantity,own)


class ClothingTests(unittest.TestCase):
    def wardrobe(self):
        return ClothingSelection([1000023,1000024,1050028],
                                 {'1000023':22,'1000024':22,'1050028':15})

    def test_native_reference_equip_replace_and_unequip_preserve_instances(self):
        wardrobe=self.wardrobe()
        packets,action=wardrobe.handle(move(6,0,1,22),42)
        self.assertEqual(action,'move_clothing')
        empty,new=(decode_delta(p[1]) for p in packets[1:])
        self.assertEqual((empty.entries[0].container,empty.entries[0].slot,empty.entries[0].item.definition),(6,0,0))
        self.assertEqual((new.entries[0].container,new.entries[0].slot,new.entries[0].item.definition),(1,22,1000023))
        self.assertEqual((new.actor_uid,new.own),(42,0))
        first_uid=new.entries[0].item.instance_uid
        wardrobe.handle(move(6,1,1,22),42)
        self.assertEqual(wardrobe.storage,{0:1000023,2:1050028})
        self.assertEqual(wardrobe.equipped,{22:1000024})
        wardrobe.handle(move(1,22,6,1),42)
        self.assertEqual(wardrobe.equipped,{})
        rows=decode_snapshot(wardrobe.snapshot(42)).entries
        self.assertEqual(sorted(x.item.definition for x in rows),[1000023,1000024,1050028])
        self.assertEqual(next(x.item.instance_uid for x in rows if x.item.definition==1000023),first_uid)

    def test_rejected_moves_and_replay_do_not_change_inventory(self):
        wardrobe=self.wardrobe()
        for body in (move(6,0,1,15),move(6,99,1,22),move(6,0,1,22,2),move(6,0,1,22,own=1),move(6,0,1,1)):
            before=wardrobe.snapshot(42)
            packets,action=wardrobe.handle(body,42)
            self.assertEqual(action,'clothing_move_rejected')
            self.assertEqual(packets[0][1][1:5],struct.pack('>I',1))
            self.assertEqual(wardrobe.snapshot(42),before)
        wardrobe.handle(move(6,0,1,22),42)
        before=wardrobe.snapshot(42)
        self.assertEqual(wardrobe.handle(move(6,0,1,22),42)[1],'clothing_move_noop')
        self.assertEqual(wardrobe.snapshot(42),before)
        self.assertEqual(wardrobe.handle(move(1,22,6,1),42)[1],'clothing_move_rejected')
        self.assertEqual(wardrobe.handle(move(1,1,1,2),42),([],None))

    def test_catalog_reference_a_b_a_and_repeated_save_preserve_owned_items(self):
        wardrobe = self.wardrobe()
        for source, expected in ((0,1000023), (1,1000024), (0,1000023), (0,1000023)):
            packets, action = wardrobe.handle(move(6,source,1,22),42)
            self.assertIn(action, ('move_clothing','clothing_move_noop'))
            self.assertEqual(packets[0][1][1:5], bytes(4))
            self.assertEqual(wardrobe.equipped[22], expected)
            self.assertEqual(sorted([*wardrobe.storage.values(), *wardrobe.equipped.values()]),
                             sorted(wardrobe.ids))
            self.assertTrue(all(wardrobe.catalog_slots[item] == slot
                                for slot,item in wardrobe.storage.items()))
        # Повтор с чужой категорией не превращается в успешное сохранение.
        self.assertEqual(wardrobe.handle(move(6,0,1,15),42)[1], 'clothing_move_rejected')
        saved = dict(clothing_selection={'22':1000024},
                     clothing_storage={'1':1000023,'2':1050028})
        restored = ClothingSelection(wardrobe.ids, {str(k):v for k,v in wardrobe.slots.items()}, saved)
        self.assertEqual(restored.storage, {0:1000023,2:1050028})
        self.assertEqual(restored.handle(move(6,0,1,22),42)[1], 'move_clothing')

    def test_saved_inventory_requires_unique_complete_owned_items_and_matching_slots(self):
        wardrobe=self.wardrobe()
        wardrobe.handle(move(6,0,1,22),42)
        saved=json.loads(json.dumps(wardrobe.state()))
        restored=ClothingSelection(wardrobe.ids,{str(k):v for k,v in wardrobe.slots.items()},saved)
        self.assertEqual(restored.snapshot(42),wardrobe.snapshot(42))
        for corrupt in (dict(clothing_storage={'0':1000023,'1':1000023,'2':1050028}),
                        dict(clothing_storage={'0':1000023}),
                        dict(clothing_selection={'15':1000023}),
                        dict(clothing_storage={'00':1000023,'1':1000024,'2':1050028})):
            with self.assertRaises(ValueError):
                ClothingSelection(wardrobe.ids,{str(k):v for k,v in wardrobe.slots.items()},corrupt)

    def test_account_saves_move_and_cold_login_restores_equip_and_storage(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);config=root/'catalog.json';state=root/'state.json'
            config.write_text(json.dumps(dict(owned_gun_skin_ids=[],owned_clothing_ids=[1000023,1000024],
                clothing_inventory_container=6,clothing_equipment_slots={'1000023':22,'1000024':22},state_file=state.name)))
            account=LocalCosmetics(config)
            self.assertEqual(account.handle(0x3e80,move(6,0,1,22),42)[1],'move_clothing')
            old=state.read_bytes()
            self.assertEqual(account.handle(0x3e80,move(6,0,1,22),42)[1],'clothing_move_noop')
            self.assertEqual(state.read_bytes(),old)
            fresh=LocalCosmetics(config)
            entries=decode_snapshot(dict(fresh.initial(42))[0x5fb]).entries
            self.assertEqual([(x.container,x.slot,x.item.definition) for x in entries],[(6,1,1000024),(1,22,1000023)])
            fresh.handle(0x3e80,move(1,22,6,0),42)
            self.assertEqual(LocalCosmetics(config).wardrobe.equipped,{})
