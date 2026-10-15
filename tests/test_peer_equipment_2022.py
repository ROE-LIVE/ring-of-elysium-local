"""547: изоляция комнаты, текущая экипировка, handoff и поздняя модель."""
import struct
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server/directory'))
from peer_avatar_2022 import PeerAvatarRooms
from peer_equipment_2022 import encode_peer_equipment
from weapon_probe_2022 import WeaponFixture,WeaponState,GunInstance
from attachment_probe_2022 import AttachmentInstance


class EquipmentTests(unittest.TestCase):
    def weapon(self,uid):
        gun=bytearray(82)
        struct.pack_into('>IQ',gun,4,10402,uid+100)
        struct.pack_into('>7I',gun,36,260,0,400,25000,39900,2,2)
        weapon=WeaponState(WeaponFixture(bytes(gun),bytes(60),
            starting_equipment=(200101,201001,200906),weapon_slots=2),uid)
        weapon.hand_slot=1
        return weapon

    def state(self,uid,room=1):
        return dict(actor_uid=uid,room_uid=room,scene_position=(100,200,300),
                    auth_sent=True,room_sent=True,peer_avatar_anchor=(None,None,100),
                    weapon=self.weapon(uid),world=SimpleNamespace(hp=1000,dead=False))

    def rooms(self):
        fixture=SimpleNamespace(listing=bytes(23),profile=bytes(1516),movement=bytes(40))
        return PeerAvatarRooms(fixture,True,False,True)

    def test_wire_golden_slots_properties_clear_and_hand_without_own_mutation(self):
        weapon=self.weapon(1);weapon.guns[2]=GunInstance(10201,30,999)
        weapon.guns[2].parts[1]=AttachmentInstance(40305,888)
        weapon.equipment_durability[12]=7
        body=encode_peer_equipment(weapon,0x2040000100001)
        self.assertEqual(struct.unpack_from('>QI',body),(0x2040000100001,5))
        self.assertEqual(struct.unpack_from('>IQIBI7I4I',body,12),
                         (10402,101,1,0,0,260,0,400,25000,39900,2,2,0,0,1,0))
        self.assertEqual(struct.unpack_from('>I',body,12+65+17)[0],1)
        self.assertEqual(struct.unpack_from('>III',body,12+65+21),(1,40305,0))
        self.assertEqual(struct.unpack_from('>I',body,12+4*65+12+53)[0],7)
        self.assertEqual(struct.unpack_from('>IB',body,len(body)-5),(1,0))
        before=(weapon.clip,weapon.reserve,weapon.hand_slot,dict(weapon.equipment))
        dead=encode_peer_equipment(weapon,42,True)
        self.assertEqual(struct.unpack_from('>I',dead,len(dead)-5)[0],0xffffffff)
        self.assertEqual((weapon.clip,weapon.reserve,weapon.hand_slot,weapon.equipment),before)
        del weapon.guns[2];del weapon.equipment[12]
        body=encode_peer_equipment(weapon,42)
        self.assertEqual(struct.unpack_from('>IQI',body,12+65),(0,0,2))
        self.assertEqual(struct.unpack_from('>IQI',body,12+4*65),(0,0,12))

    def test_room_and_own_isolation_changes_once_and_stale_recipient_recovers(self):
        rooms=self.rooms();a,b,c=self.state(1),self.state(2),self.state(3,2)
        for state in (a,b,c):rooms.admit(state,1,100)
        outputs,events=rooms.equipment(100)
        self.assertEqual(len(outputs),2)
        for target,packets in outputs:
            expected=rooms.members[(1,2 if target is a else 1)]['avatar']
            self.assertEqual(struct.unpack_from('>Q',packets[0][1])[0],expected)
            self.assertIsNot(target,c)
        self.assertEqual(rooms.equipment(101),([],[]))
        a['weapon'].equipment_durability[12]=0
        self.assertEqual(rooms.equipment(110),([],[]))
        b['peer_avatar_anchor']=(None,None,111)
        outputs,_=rooms.equipment(111)
        self.assertEqual(len(outputs),1);self.assertIs(outputs[0][0],b)
        self.assertEqual(b['weapon'].equipment_durability[12],2000)
        b['transport_retired']=True;a['weapon'].hand_slot=0
        self.assertEqual(rooms.equipment(112),([],[]))

    def test_cold_join_and_async_repeat_use_current_gear_before_hp_and_death(self):
        rooms=self.rooms();a,b=self.state(1),self.state(2)
        rooms.admit(a,1,100)
        a['weapon'].equipment_durability[12]=0;a['world'].hp=700
        outputs,_=rooms.admit(b,2,100)
        packet=next(p for target,p in outputs if target is b)
        self.assertEqual([c for c,_ in packet],[0x565,0xbe7,0x547,0x1069])
        self.assertEqual(struct.unpack_from('>I',packet[2][1],12+4*65+53)[0],0)
        a['weapon'].hand_slot=0
        outputs,_=rooms.pose_snapshots(101,3)
        body=next(p[0][1] for target,p in outputs if target is b)
        self.assertEqual(struct.unpack_from('>I',body,len(body)-5)[0],0xffffffff)
        a['world'].hp=0;a['world'].dead=True
        packet=rooms.packets(rooms.members[(1,1)],4)
        self.assertEqual([c for c,_ in packet], [0x565,0xbe7,0x547,0x1069,0x533])
        self.assertEqual(struct.unpack_from('>I',packet[2][1],len(packet[2][1])-5)[0],0xffffffff)

    def test_transport_rebind_reasserts_current_gear_and_retired_source_is_ignored(self):
        rooms=self.rooms();a,b=self.state(1),self.state(2)
        for state in (a,b):rooms.admit(state,1,100)
        rooms.equipment(100)
        resumed=dict(b,gameplay_resumed=True,peer_avatar_anchor=(None,None,101))
        rooms.admit(resumed,1,101)
        outputs,_=rooms.equipment(101)
        self.assertEqual(len(outputs),1);self.assertIs(outputs[0][0],resumed)
        rooms.detach(resumed,'leave');rooms.equipment(102)
        self.assertEqual(rooms.members[(1,1)]['equipment_targets'],{})
        a['transport_retired']=True
        self.assertEqual(rooms.equipment(102),([],[]))
