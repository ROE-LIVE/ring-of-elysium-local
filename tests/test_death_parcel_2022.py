"""Перенос живого учёта, частичный pickup, metadata и отрицательные контроли."""
from dataclasses import replace
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server/directory'))
from death_parcel_2022 import DeathParcelState
from weapon_probe_2022 import LootFixture, WeaponFixture, WeaponState
from attachment_probe_2022 import AttachmentInstance
from types import SimpleNamespace
from game_endpoint_probe_2022 import Endpoint


class DeathParcelTests(unittest.TestCase):
    def setUp(self):
        template = bytearray(100)
        struct.pack_into('>I', template, 0, 30201002)
        struct.pack_into('>I', template, 12, 13)
        struct.pack_into('>I', template, 46, 1)
        template[62] = 2
        ground = LootFixture(999, 123, 1, (100,200,300), bytes(45), entity=bytes(template))
        self.fixture = WeaponFixture(bytes(82), bytes(60), loot=ground,
                                     inventory_update='delta', weapon_slots=2,
                                     starting_equipment=(200904, 200103, 201001))
        self.owner = WeaponState(self.fixture, 41)
        self.owner.guns[1].clip = 1
        self.owner.guns[1].parts = {0: AttachmentInstance(40101, 987)}
        self.owner.equipment_durability[10] = 23
        self.owner.equipment_durability[12] = 0
        self.owner.reserve = 998
        self.owner.medical[70001] = 3
        self.owner.throwables[50001] = 2
        self.owner.equipped_throwables[5] = (50001, 1)
        self.owner.pending_reload = {'slot': 1}
        self.receiver = WeaponState(replace(self.fixture, starting_equipment=(200904,)), 42)
        self.receiver.reserve = 239
        self.receiver.update_position((100,200,300))
        self.state = DeathParcelState()

    def transfer(self):
        return self.state.transfer(self.owner, (100,200,300))

    def open(self, requester=42):
        return self.state.handle(0xbce, struct.pack('>QQ',self.state.containers[0].fixture.uid,requester),self.receiver)

    def pick(self, item, x=100):
        fixture = self.state.containers[0].fixture
        return self.state.handle(0x3b63,struct.pack('>IIQBHB3iB',
            fixture.index,item.index,0,0,0,1,x,200,300,0),self.receiver)

    def test_atomic_transfer_retains_gun_metadata_and_zero_armor(self):
        uid = self.owner.guns[1].uid
        packets,event = self.transfer()
        self.assertEqual((packets[0][0],packets[0][1][62]),(0x821,1))
        self.assertEqual(struct.unpack_from('>I',packets[0][1],71)[0],event['parcel_id'])
        self.assertEqual((self.owner.guns,self.owner.reserve,self.owner.medical),({},0,{}))
        self.assertEqual(self.owner.equipment,{11:200904})
        self.assertIsNone(self.owner.pending_reload)
        items = self.state.containers[0].fixture.items
        gun = next(x for x in items if x.definition==10402)
        self.assertEqual((gun.clip,gun.instance_uid,gun.parts),(1,uid,((0,AttachmentInstance(40101,987)),)))
        self.assertEqual(next(x.durability for x in items if x.definition==201001),0)
        self.assertEqual(self.transfer()[1]['action'],'death_inventory_duplicate')
        self.assertEqual(len(self.state.containers),1)

    def test_bad_template_leaves_source_and_ownership_untouched(self):
        self.owner.ground_template = bytes(100)
        with self.assertRaises(ValueError): self.transfer()
        self.assertEqual((self.owner.reserve,len(self.owner.guns)),(998,1))
        self.assertEqual((self.state.owners,self.state.containers),(set(),[]))

    def test_item_index_collision_does_not_remove_owner_inventory(self):
        with self.assertRaises(ValueError):
            self.state.transfer(self.owner,(100,200,300),reserved_indexes={450102})
        self.assertEqual((len(self.owner.guns),self.owner.reserve),(1,998))
        self.assertEqual(self.state.owners,set())

    def test_own_terminal_death_transfers_once_and_blocks_open(self):
        events, sent = [], []
        endpoint = Endpoint(SimpleNamespace(record=lambda *a,**kw:events.append(kw)))
        endpoint.send_application_batch = lambda d,r,s,packets:sent.extend(packets)
        state = dict(weapon=self.owner,world=SimpleNamespace(dead=True,position=(100,200,300)))
        endpoint.emit_own_death_inventory(None,None,state)
        self.assertEqual((self.owner.reserve,len(self.owner.guns)),(0,0))
        self.assertEqual(sum(code==0x821 for code,_ in sent),1)
        endpoint.emit_own_death_inventory(None,None,state)
        self.assertEqual(len(state['death_parcels'].containers),1)
        self.assertFalse(endpoint.accept_living_action(state,SimpleNamespace(command=0xbce),None))

    def test_handoff_contents_preserve_partial_residual_without_new_owner_items(self):
        self.transfer();self.open()
        item = next(x for x in self.state.containers[0].fixture.items if x.definition==30004)
        self.pick(item)
        before = self.state.containers[0].contents()
        self.assertEqual(self.state.reconcile(),[(0x3b61,before)])
        self.assertEqual((self.owner.reserve,self.receiver.reserve),(0,240))

    def test_open_and_pick_guards_and_partial_ammunition_conservation(self):
        self.transfer()
        item = next(x for x in self.state.containers[0].fixture.items if x.definition==30004)
        self.assertEqual(self.pick(item)[0],[])
        self.assertEqual(self.open(requester=41)[0],[])
        self.receiver.update_position((850,200,300))
        self.assertEqual(self.open()[0],[])
        self.receiver.update_position((100,200,300))
        self.open()
        self.assertEqual(self.pick(item,x=850)[0],[])
        packets,event = self.pick(item)
        self.assertEqual((self.receiver.reserve,event['remaining']),(240,997))
        self.assertFalse(any(code==0x821 for code,_ in packets))
        self.assertEqual(struct.unpack_from('>II',next(body for code,body in packets if code==0x3b64)),
                         (self.state.containers[0].fixture.index,item.index))
        self.pick(item)
        self.assertEqual((self.receiver.reserve,self.state.containers[0].remaining[item.index]),(240,997))

    def test_pick_preserves_gun_uid_clip_parts_and_armor_durability(self):
        self.transfer();self.open()
        for item in self.state.containers[0].fixture.items:
            if item.definition in (10402,201001,200103): self.pick(item)
        gun = self.receiver.guns[2]
        self.assertEqual((gun.clip,gun.uid,gun.parts),(1,0x1e00000100000001,{0:AttachmentInstance(40101,987)}))
        self.assertEqual((self.receiver.equipment_durability[10],self.receiver.equipment_durability[12]),(23,0))
        items = self.state.containers[0].fixture.items
        self.pick(next(x for x in items if x.definition==10402))
        self.assertEqual(len(self.receiver.guns),2)


if __name__ == '__main__':
    unittest.main()
