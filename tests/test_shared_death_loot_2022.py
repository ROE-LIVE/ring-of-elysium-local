"""Общий остаток погибшего: partial, гонка, открытие и late snapshot."""
from dataclasses import replace
from pathlib import Path
import struct
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server/directory'))
from death_parcel_2022 import DeathParcelState
from shared_loot_2022 import SharedLootRooms
from weapon_probe_2022 import LootFixture,WeaponFixture,WeaponState
from parcel_catalog_2022 import ContainerState


class SharedDeathLootTests(unittest.TestCase):
    def setUp(self):
        template=bytearray(100)
        struct.pack_into('>I',template,0,30201002);template[62]=2
        ground=LootFixture(999,123,1,(100,200,300),bytes(45),entity=bytes(template))
        gun=bytearray(82);struct.pack_into('>IQ',gun,4,10402,777)
        self.fixture=WeaponFixture(bytes(gun),bytes(60),loot=ground,starting_equipment=(200904,),weapon_slots=2,inventory_update='delta')
        self.rooms=SharedLootRooms(self.fixture,True)
        self.states=[]
        for uid in (1,2,3):
            weapon=WeaponState(self.fixture,uid);weapon.position=(100,200,300)
            state=dict(actor_uid=uid,room_uid=100,weapon=weapon)
            self.rooms.attach(state);self.states.append(state)
        self.a,self.b,self.c=self.states
        self.initial_uid=self.a['weapon'].guns[1].uid
        self.a['weapon'].reserve=100
        self.parcels=self.a['death_parcels']
        self.spawns,_=self.parcels.transfer(self.a['weapon'],(100,200,300))
        self.container=self.parcels.containers[0]
        self.ammo=next(x for x in self.container.fixture.items if x.definition==30004)

    def open(self,state):
        return self.parcels.handle(0xbce,struct.pack('>QQ',self.container.fixture.uid,state['actor_uid']),state['weapon'])

    def pick(self,state,item=None):
        item=item or self.ammo
        body=struct.pack('>IIQBHB3iB',self.container.fixture.index,item.index,0,0,0,1,100,200,300,0)
        return self.parcels.handle(0x3b63,body,state['weapon'])

    def test_two_openers_consume_current_partial_once_without_inventory_cross_effects(self):
        self.b['weapon'].reserve=239;self.c['weapon'].reserve=0
        self.open(self.b);self.open(self.c)
        packets,event=self.pick(self.b)
        self.assertEqual((event['quantity'],self.b['weapon'].reserve,self.c['weapon'].reserve,self.container.remaining[self.ammo.index]),(1,240,0,99))
        outputs=self.rooms.death_outputs(self.b,packets,True)
        peer_packets=next(p for s,p in outputs if s is self.c)
        self.assertEqual([code for code,_ in peer_packets],[0x3b61])
        _,event=self.pick(self.c)
        self.assertEqual((event['quantity'],self.c['weapon'].reserve,self.container.remaining[self.ammo.index]),(99,99,0))
        self.assertEqual(self.pick(self.b)[1]['reason'],'consumed')
        self.assertEqual(self.pick(self.c)[1]['reason'],'consumed')
        self.assertEqual((self.b['weapon'].reserve,self.c['weapon'].reserve),(240,99))

    def test_opening_is_per_account_real_position_and_room_snapshot_is_current(self):
        self.open(self.b)
        self.assertEqual(self.pick(self.c)[1]['reason'],'not_open_or_near')
        self.c['weapon'].position=(10000,200,300)
        self.assertEqual(self.open(self.c)[0],[])
        self.assertEqual(self.pick(self.c)[0],[])
        self.assertEqual(self.parcels.reconcile(3),[])
        self.assertEqual(len(self.parcels.reconcile(2)),1)
        late=dict(actor_uid=4,room_uid=100,weapon=WeaponState(self.fixture,4))
        self.rooms.attach(late)
        self.assertIs(late['death_parcels'],self.parcels)
        self.assertIn(self.spawns[0],self.rooms.snapshot(late))
        other=dict(actor_uid=5,room_uid=200,weapon=WeaponState(self.fixture,5))
        self.rooms.attach(other)
        self.assertNotIn(self.spawns[0],self.rooms.snapshot(other))
        self.assertIsNot(other['death_parcels'],self.parcels)

    def test_failed_codec_rolls_back_item_registry_inventory_and_shared_remaining(self):
        self.open(self.b)
        before=(self.b['weapon'].reserve,dict(self.b['weapon'].loot_registry),dict(self.container.remaining))
        original=ContainerState.handle
        def failed(container,*args):
            original(container,*args)
            raise ValueError('after encode')
        with patch.object(ContainerState,'handle',failed):
            with self.assertRaises(ValueError):self.pick(self.b)
        self.assertEqual((self.b['weapon'].reserve,self.b['weapon'].loot_registry,self.container.remaining),before)

    def test_room_assigns_unique_initial_and_new_gun_instances_without_handoff_reset(self):
        initial={state['weapon'].guns[1].uid for state in (self.b,self.c)}|{self.initial_uid}
        self.assertEqual(len(initial),3)
        weapon=self.b['weapon'];before=weapon.guns[1].uid
        self.rooms.attach(self.b)
        self.assertEqual(weapon.guns[1].uid,before)
        generated={state['weapon'].new_instance_uid() for state in self.states}
        self.assertEqual(len(generated),3)
        self.assertFalse(initial & generated)

    def test_one_gun_instance_one_transfer_and_room_epoch_cleanup(self):
        self.open(self.b);self.open(self.c)
        gun=next(x for x in self.container.fixture.items if x.definition==10402)
        self.pick(self.b,gun)
        self.assertEqual(self.b['weapon'].guns[2].uid,self.initial_uid)
        self.assertEqual(self.pick(self.c,gun)[1]['reason'],'consumed')
        self.assertNotIn(2,self.c['weapon'].guns)
        self.assertEqual(self.parcels.transfer(self.a['weapon'],(100,200,300))[1]['action'],'death_inventory_duplicate')
        for state in self.states:self.rooms.detach(state)
        fresh=dict(actor_uid=1,room_uid=100,weapon=WeaponState(self.fixture,1))
        self.rooms.attach(fresh)
        self.assertEqual(fresh['death_parcels'].spawns,[])
        self.assertEqual(fresh['death_parcels'].owners,set())
