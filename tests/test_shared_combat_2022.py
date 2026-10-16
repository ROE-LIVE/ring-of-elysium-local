"""Общий PvP: реальный расход WeaponState, room isolation и rollback HP."""
from dataclasses import replace
from pathlib import Path
import struct
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server/directory'))
from actor_probe_2022 import ActorFixture
from peer_avatar_2022 import PeerAvatarRooms
from shared_combat_2022 import SharedCombatRooms
from weapon_probe_2022 import WeaponFixture,WeaponState
from world_probe_2022 import WorldFixture,WorldState
from match_statistics_2022 import MatchStatistics


class SharedCombatTests(unittest.TestCase):
    def setUp(self):
        fixture = ActorFixture(900,bytes(23),bytes(1516),bytes(40),
                               (900,0,0),((900,0,0),),0,1000,50)
        self.avatars = PeerAvatarRooms(fixture,True,False,True)
        self.combat = SharedCombatRooms(self.avatars,50)
        self.a,self.b,self.c = self.state(10,(0,0,0)),self.state(20,(900,0,0)),self.state(30,(900,0,0),2)
        for state in (self.a,self.b,self.c):self.avatars.admit(state,1,100)
        self.target = self.avatars.members[(1,20)]['avatar']

    def state(self,uid,position,room=1):
        gun=bytearray(82);struct.pack_into('>IQ',gun,4,10402,uid+100)
        weapon=WeaponState(WeaponFixture(bytes(gun),bytes(60),
                            starting_equipment=(201001,),combat_armor_absorb_percent=50),uid)
        weapon.hand_slot=1;weapon.position=position
        world=WorldState(WorldFixture(1000,0,(-100,-100,-50,-50),1,1,(),death_on_zero=True),uid,100)
        world.position=position
        return dict(actor_uid=uid,room_uid=room,scene_position=position,
                    weapon=weapon,world=world,auth_sent=True,room_sent=True,
                    peer_avatar_anchor=(None,None,100))

    def fire(self,counter=1,tick=10,now=100,state=None,origin=(0,0,150)):
        state=state or self.a
        body=struct.pack('>6fIBIIfII',*origin,900,0,120,counter,0,tick,0,480,0,0)
        _,event=state['weapon'].handle(0x11da,body)
        self.combat.note_fire(state,body,event,now)
        return body,event

    def hit(self,pellet=1,target=None,counter=1,tick=10):
        body=bytearray(106)
        struct.pack_into('>IQ',body,0,pellet,target or self.target)
        struct.pack_into('>3f',body,25,0,0,150)
        struct.pack_into('>3i',body,37,900,0,0)
        struct.pack_into('>3f',body,50,900,0,120)
        struct.pack_into('>I',body,88,counter);struct.pack_into('>I',body,96,tick)
        return bytes(body)

    def test_real_ammo_current_armor_and_single_death_account_unit_separation(self):
        stats=MatchStatistics();stats.begin(100)
        self.b['world'].hp=60;self.b['weapon'].equipment_durability[12]=30
        self.fire();self.assertEqual(self.a['weapon'].clip,1)
        outputs,event,victim=self.combat.hit(self.a,self.hit(),100.1);stats.observe(event)
        self.assertIs(victim,self.b)
        self.assertEqual((self.b['world'].hp,self.b['weapon'].equipment_durability[12]),(35,5))
        self.assertEqual([code for code,_ in outputs[0][1]],[0x11ea,0x11eb])
        feedback = dict(outputs[0][1])[0x11eb]
        self.assertEqual(struct.unpack_from('>QQ',feedback),(10,self.target))
        own_hp=next(body for code,body in outputs[1][1] if code==0x1069)
        self.assertEqual(struct.unpack_from('>Q',own_hp)[0],20)
        self.assertEqual(self.combat.hit(self.a,self.hit(),100.2)[1]['reason'],'duplicate_hit')
        outputs,event,_=self.combat.hit(self.a,self.hit(2),100.3);stats.observe(event)
        self.assertEqual((self.b['world'].hp,self.b['world'].dead),(0,True))
        self.assertEqual([code for code,_ in outputs[1][1]].count(0x533),1)
        self.assertEqual(struct.unpack_from('>Q',outputs[1][1][-1][1],4)[0],20)
        self.assertEqual((stats.kills,stats.damage_raw,self.a['world'].hp,self.c['world'].hp),(1,60,1000,1000))
        self.assertIsNone(self.combat.hit(self.a,self.hit(3),100.4)[2])
        remote,_=self.avatars.health(self.b,100.4)
        self.assertEqual(struct.unpack_from('>Q',remote[0][1][0][1])[0],self.target)

    def test_other_room_self_stale_retired_and_old_handoff_cannot_mutate(self):
        self.fire()
        for uid in (self.avatars.members[(2,30)]['avatar'],self.avatars.members[(1,10)]['avatar']):
            self.assertEqual(self.combat.hit(self.a,self.hit(target=uid),100)[0],[])
        self.b['peer_avatar_anchor']=(None,None,90)
        self.assertEqual(self.combat.hit(self.a,self.hit(),100)[0],[])
        self.b['peer_avatar_anchor']=(None,None,100);self.b['transport_retired']=True
        self.assertEqual(self.combat.hit(self.a,self.hit(),100)[0],[])
        self.b.pop('transport_retired');new=dict(self.a,gameplay_resumed=True)
        self.avatars.admit(new,2,100)
        self.assertEqual(self.combat.hit(self.a,self.hit(),100)[0],[])
        self.assertEqual(self.combat.hit(new,self.hit(),100)[1]['action'],'hit_damage')

    def test_unaccepted_empty_expired_and_remote_origin_have_no_hit_authority(self):
        self.assertEqual(self.combat.hit(self.a,self.hit(),100)[1]['reason'],'unaccepted_or_expired_shot')
        body,event=self.fire();self.combat.note_fire(self.a,body,event,101.9)
        self.assertEqual(self.combat.hit(self.a,self.hit(),102.1)[1]['reason'],'unaccepted_or_expired_shot')
        self.fire(2,11,origin=(800,0,150))
        self.assertEqual(self.combat.hit(self.a,self.hit(counter=2,tick=11),100)[0],[])
        _,event=self.fire(3,12)
        self.assertEqual(event['action'],'empty')
        self.assertEqual(self.combat.hit(self.a,self.hit(counter=3,tick=12),100)[0],[])
        self.assertEqual(self.b['world'].hp,1000)

    def test_direction_nonfinite_and_manual_los_reject_before_commit(self):
        self.fire()
        body=bytearray(self.hit());struct.pack_into('>f',body,50,float('nan'))
        self.assertEqual(self.combat.hit(self.a,bytes(body),100)[1]['reason'],'ray_nonfinite')
        self.avatars.fixture=replace(self.avatars.fixture,collision_boxes=(((400,-100,0),(500,100,500)),))
        self.assertEqual(self.combat.hit(self.a,self.hit(),100)[1]['reason'],'line_of_sight')
        self.assertEqual((self.b['world'].hp,self.b['weapon'].equipment_durability[12]),(1000,2000))
        self.assertFalse(self.avatars.members[(1,10)].get('combat_hits'))

    def test_codec_failure_rolls_back_hp_armor_and_hit_dedup(self):
        self.fire()
        with patch.object(WeaponState,'absorb_combat_damage',side_effect=ValueError('codec')):
            with self.assertRaises(ValueError):self.combat.hit(self.a,self.hit(),100)
        self.assertEqual((self.b['world'].hp,self.b['weapon'].equipment_durability[12]),(1000,2000))
        self.assertFalse(self.avatars.members[(1,10)].get('combat_hits'))
        self.assertEqual(self.combat.hit(self.a,self.hit(),100)[1]['action'],'hit_damage')

    def test_global_pellet_limit_and_bounded_history(self):
        d=self.state(40,(900,0,0));self.avatars.admit(d,1,100)
        other=self.avatars.members[(1,40)]['avatar'];self.fire()
        for pellet in range(12):
            self.assertEqual(self.combat.hit(self.a,self.hit(pellet,target=other if pellet%2 else self.target),100)[1]['action'],'hit_damage')
        self.assertEqual(self.combat.hit(self.a,self.hit(13),100)[1]['reason'],'shot_hit_limit')
        for counter in range(2,67):
            self.a['weapon'].clip=2;self.fire(counter,counter)
        member=self.avatars.members[(1,10)]
        self.assertEqual(len(member['combat_shots']),64)
        self.assertFalse(member['combat_hits'])
