"""Ограничения нативных контейнеров и сохранение локального выбора."""
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from local_cosmetics_2022 import LocalCosmetics,gun_skin_sync,character_container,accessory_container,clothing_inventory


class CosmeticsTests(unittest.TestCase):
    def test_clothing_container_control_and_invalid_reference_rejected(self):
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server/directory'))
        from inventory_codec_2022 import decode_snapshot
        for container in (2,6):
            message=decode_snapshot(clothing_inventory([1000023,1000024],42,container))
            self.assertEqual([(x.container,x.slot,x.item.definition) for x in message.entries],
                             [(container,0,1000023),(container,1,1000024)])
            self.assertEqual((message.actor_uid,message.own),(42,0))
        for container in (0,1,True,'6',7):
            with self.assertRaises(ValueError):clothing_inventory([],42,container)

    def test_skin_from_another_weapon_is_rejected_without_changing_saved_selection(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'config.json'
            state = Path(temporary) / 'state.json'
            config = dict(owned_gun_skin_ids=[7200016, 10402210],
                          weapon_skin_to_weapon={'7200016': 10201, '10402210': 10402},
                          state_file=str(state))
            path.write_text(json.dumps(config))
            account = LocalCosmetics(path)
            account.handle(0x54e2, struct.pack('>II', 10402, 10402210))
            before = state.read_bytes()
            packets, action = account.handle(0x54e2, struct.pack('>II', 10402, 7200016))
            self.assertEqual(action, 'skin_not_owned')
            self.assertEqual(packets, [(0x54e3, struct.pack('>III', 1, 10402, 7200016))])
            self.assertEqual(state.read_bytes(), before)
            self.assertEqual(LocalCosmetics(path).selected, {10402: 10402210})
            for selection in ({'0': 10402210}, {'-1': 10402210}, {'4294967296': 0},
                              {'010402': 10402210}, {'10402': True}, {'10402': '10402210'},
                              {'10402': 7200016}, []):
                state.write_text(json.dumps({'gun_skins': selection}))
                with self.assertRaises(ValueError): LocalCosmetics(path)
            state.unlink()
            account.handle(0x54e2, struct.pack('>II', 10402, 0))
            self.assertEqual(LocalCosmetics(path).selected, {10402: 0})

    def test_weapon_skin_mapping_requires_complete_owned_catalog_and_u32_values(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'config.json'
            for mapping in ([], {'1': True}, {'1': 0}, {'01': 10402}, {'2': 10402}):
                path.write_text(json.dumps(dict(owned_gun_skin_ids=[1], weapon_skin_to_weapon=mapping)))
                with self.assertRaises(ValueError): LocalCosmetics(path)

    def test_saved_accessory_initialization_creates_profile_before_full_sync(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);state=root/'state.json';config=root/'catalog.json'
            state.write_text(json.dumps(dict(accessory_selection=[[100608,0,200000,0]])))
            config.write_text(json.dumps(dict(owned_gun_skin_ids=[],owned_accessory_ids=[200000],state_file=str(state))))
            account=LocalCosmetics(config);packets=account.initial(42)
            equip=(0x73b3,struct.pack('>4IB',0,100608,0,200000,0))
            self.assertIn(equip,packets)
            self.assertLess(packets.index(equip),next(i for i,p in enumerate(packets) if p[0]==0x73b1))
            self.assertEqual(dict(packets)[0x73b1],account.accessory_sync())
            self.assertEqual(LocalCosmetics(config).accessory_selection,account.accessory_selection)

    def accessory_account(self, root):
        config=root/'catalog.json';state=root/'state.json'
        config.write_text(json.dumps(dict(owned_gun_skin_ids=[],owned_accessory_ids=[200000,200001],state_file=str(state))))
        return config,state,LocalCosmetics(config)

    def test_accessory_remove_persists_and_rejects_second_removal_without_write(self):
        with tempfile.TemporaryDirectory() as directory:
            config,state,account=self.accessory_account(Path(directory))
            account.handle(0x73b2,struct.pack('>3IB',0x200005,0,200000,1))
            packets,action=account.handle(0x73b4,struct.pack('>II',0x200005,0))
            self.assertEqual((action,packets[0]),('unequip_accessory',(0x73b5,struct.pack('>3IB',0,0x200005,0,1))))
            self.assertEqual(LocalCosmetics(config).accessory_selection,{})
            self.assertEqual(packets[1],(0x73b1,bytes(4)))
            saved=state.read_bytes()
            self.assertEqual(account.handle(0x73b4,struct.pack('>II',0x200005,0))[1],'accessory_slot_empty')
            self.assertEqual(state.read_bytes(),saved)

    def test_accessory_swap_preserves_items_flags_and_persists_final_assignments(self):
        with tempfile.TemporaryDirectory() as directory:
            config,state,account=self.accessory_account(Path(directory))
            for index,item,flag in ((0,200000,1),(1,200001,0)):
                account.handle(0x73b2,struct.pack('>3IB',200005,index,item,flag))
            packets,action=account.handle(0x73b8,struct.pack('>III',200005,0,1))
            self.assertEqual(action,'swap_accessory')
            self.assertEqual(packets[0],(0x73b9,struct.pack('>6I2B',0,200005,0,200001,1,200000,0,1)))
            self.assertEqual(LocalCosmetics(config).accessory_selection,{(200005,0):(200001,0),(200005,1):(200000,1)})
            account.handle(0x73b8,struct.pack('>III',200005,1,2))
            self.assertNotIn((200005,1),account.accessory_selection)
            self.assertEqual(account.accessory_selection[(200005,2)],(200000,1))
            saved=state.read_bytes()
            for args in ((200005,2,2),(200005,3,4),(200005,2,6),(0,2,1)):
                self.assertEqual(account.handle(0x73b8,struct.pack('>III',*args))[1],'accessory_swap_invalid')
                self.assertEqual(state.read_bytes(),saved)

    def test_accessory_request_sync_returns_current_state_without_mutating_account(self):
        with tempfile.TemporaryDirectory() as directory:
            _,state,account=self.accessory_account(Path(directory))
            account.handle(0x73b2,struct.pack('>3IB',200005,0,200000,0))
            saved=state.read_bytes()
            self.assertEqual(account.handle(0x73b6,b'\x01')[0],[(0x73b1,account.accessory_sync())])
            self.assertEqual(account.handle(0x73b7,b'\x00')[0],[(0x73b0,accessory_container(account.accessories))])
            self.assertEqual(account.handle(0x73b6,b'')[0],[])
            self.assertEqual(state.read_bytes(),saved)

    def test_empty_avatar_initialization_is_explicit_and_typed(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'config.json'
            config=dict(owned_gun_skin_ids=[])
            path.write_text(json.dumps(config))
            self.assertNotIn(0x73a1,[code for code,body in LocalCosmetics(path).initial(42)])
            config['initialize_default_avatar']=True
            path.write_text(json.dumps(config))
            self.assertIn((0x73a1,bytes(25)),LocalCosmetics(path).initial(42))
            config['initialize_default_avatar']=1
            path.write_text(json.dumps(config))
            with self.assertRaises(ValueError):LocalCosmetics(path)

    def test_count_limits_reject_instead_of_truncating(self):
        for function,size in [(gun_skin_sync,600),(character_container,400),
                              (accessory_container,240)]:
            with self.assertRaises(ValueError):function(list(range(1,size+2)))
        with self.assertRaises(ValueError):gun_skin_sync([1,1])
        with self.assertRaises(ValueError):clothing_inventory(list(range(1,257)),42)
        wire=gun_skin_sync(list(range(1,451)))
        self.assertEqual(struct.unpack_from('>I',wire)[0],300)
        self.assertEqual(struct.unpack_from('>I',wire,1204)[0],150)

    def test_equip_reply_echoes_weapon_and_skin_and_persists_selection(self):
        with tempfile.TemporaryDirectory() as temporary:
            p=Path(temporary)/'config.json';state=Path(temporary)/'state.json'
            p.write_text(json.dumps(dict(owned_gun_skin_ids=[7200016],state_file=str(state))))
            account=LocalCosmetics(p)
            request=struct.pack('>II',10201,7200016)
            packets,action=account.handle(0x54e2,request)
            self.assertEqual(action,'equip_gun_skin')
            self.assertEqual(packets[0],(0x54e3,struct.pack('>III',0,10201,7200016)))
            self.assertEqual(len(packets),1)
            second=LocalCosmetics(p)
            self.assertEqual(second.selected,account.selected)
            self.assertEqual(second.initial(42)[1],packets[0])
            self.assertNotIn(0x54e5,[code for code,body in second.initial(42)])
            self.assertEqual(second.handle(0x54e2,struct.pack('>II',10201,999))[1],'skin_not_owned')
            self.assertEqual(second.selected,account.selected)

    def test_character_and_accessory_selection_roundtrip_and_native_order(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'config.json'
            path.write_text(json.dumps(dict(owned_gun_skin_ids=[],owned_character_ids=[407,408],
                character_groups={'407':7,'408':7},owned_accessory_ids=[200000],
                state_file=str(Path(temporary)/'state.json'))))
            account=LocalCosmetics(path)
            avatar=struct.pack('>5I',407,0,0,0,0)
            self.assertEqual(account.handle(0x73a2,avatar)[0][0],(0x73a3,bytes(4)))
            self.assertEqual(account.handle(0x73ab,b'\x01')[0][1],(0x73a1,avatar+b'\x01'+bytes(4)))
            request=struct.pack('>3IB',100608,0,200000,0)
            replies,action=account.handle(0x73b2,request)
            self.assertEqual(replies[0],(0x73b3,bytes(4)+request))
            # Полный sync содержит item,index, а запрос содержит index,item.
            self.assertEqual(replies[1],(0x73b1,struct.pack('>5IB',1,100608,1,200000,0,0)))
            second=LocalCosmetics(path)
            self.assertEqual(second.avatar_sync(),account.avatar_sync())
            self.assertEqual(second.accessory_sync(),account.accessory_sync())
            self.assertEqual(second.handle(0x73ad,struct.pack('>I',407))[0],
                             [(0x73ae,struct.pack('>4I',0,2,407,408))])
            self.assertIn((0x73b1,account.accessory_sync()),second.initial(42))
            self.assertEqual(second.handle(0x73b2,struct.pack('>3IB',100608,6,200000,0))[1],
                             'accessory_not_owned')
            self.assertEqual(second.accessory_selection,account.accessory_selection)
            self.assertEqual(second.handle(0x73a2,struct.pack('>5I',999,0,0,0,0))[1],'character_not_owned')
            self.assertEqual(second.avatar,avatar)
