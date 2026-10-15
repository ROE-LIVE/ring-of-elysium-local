"""Именованные packed-поля11DD без зависимости от исследовательских fixtures."""
import struct
import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server/directory'))
from actor_probe_2022 import ActorFixture, ActorState

class HitFieldTests(unittest.TestCase):
    def setUp(self):
        uid=0x2040000123460;point=(366000,544000,259060)
        self.actor=ActorState(ActorFixture(uid,b'\1'+bytes(22),struct.pack('>II',3,1)+bytes(1508),bytes(40),point,(point,),0,1000,50))
        self.actor.begin(100)
        fire=struct.pack('>6fIBIIfII',365073,543901,259245,366062,544013,259155,4,0,14275,7,480,64,0)
        self.actor.note_fire(fire,dict(action='fire',gun_definition=10201))
        self.hit=bytearray(106)
        struct.pack_into('>Q',self.hit,4,uid)
        struct.pack_into('>3f',self.hit,25,365073,543901,259245)
        struct.pack_into('>3i',self.hit,37,*point)
        struct.pack_into('>3f',self.hit,50,366009,543997,259143)
        self.hit[62]=3;struct.pack_into('>I',self.hit,71,30)
        self.hit[75:78]=bytes((4,1,0));struct.pack_into('>I',self.hit,78,501)
        self.hit[82:84]=bytes((7,1));struct.pack_into('>4i',self.hit,88,4,100,14275,3)

    def test_named_hit_fields_match_primary_getter_offsets(self):
        _,event=self.actor.hit(self.hit)
        self.assertEqual((event['part_id'],event['target_path_id'],event['target_path_sequence'],
                          event['target_path_use_c'],event['on_vehicle'],event['shooter_path_id'],
                          event['shooter_path_sequence'],event['shooter_path_use_c'],
                          event['bullet_id'],event['ratio'],event['pellet_index']), (3,30,4,1,0,501,7,1,4,100,3))
        self.assertEqual(event['hit_impact'],(366009.,543997.,259143.))

    def test_path_use_c_does_not_change_training_damage(self):
        _,first=self.actor.hit(self.hit)
        struct.pack_into('>I',self.hit,0,1);self.hit[83]=0
        _,second=self.actor.hit(self.hit)
        self.assertEqual((first['damage'],second['damage']), (50,50))
