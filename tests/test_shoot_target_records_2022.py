"""Переменный11DD: две формы union, строгая граница и однократный урон."""
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server/directory'))
from shoot_target_records_2022 import decode_hit_records
from actor_probe_2022 import ActorFixture,ActorState


class HitRecordsTests(unittest.TestCase):
    surface = struct.pack('>BBBI3f',0,0,1,305,450,0,110)
    unit = struct.pack('>BQB',1,901,3)

    def payload(self,*records):
        return bytes(104)+struct.pack('>H',len(records))+b''.join(records)

    def state(self):
        fixture=ActorFixture(900,bytes(23),bytes(1516),bytes(40),(900,0,0),((900,0,0),),0,1000,50)
        actor=ActorState(fixture);actor.begin(0)
        fire=struct.pack('>6fIBIIfII',0,0,150,900,0,120,7,0,100,0,480,0,0)
        actor.note_fire(fire,{'action':'fire','gun_definition':10202})
        hit=bytearray(104);struct.pack_into('>IQ',hit,0,1,900)
        struct.pack_into('>3i',hit,37,900,0,0)
        struct.pack_into('>3f',hit,50,890,12,75);hit[62]=2
        struct.pack_into('>I',hit,88,7);struct.pack_into('>I',hit,96,100)
        return actor,bytes(hit)

    def test_zero_count_and_two_surfaces_match_wire_sizes(self):
        self.assertEqual(decode_hit_records(self.payload()),())
        body=self.payload(self.surface,self.surface)
        self.assertEqual(len(body),144)
        records=decode_hit_records(body)
        self.assertEqual(records[0],dict(kind=0,opaque_u8_1=0,opaque_u8_2=1,material_id=305,point=(450,0,110)))

    def test_unit_is_ten_bytes_and_mixed_union_has_no_stride_padding(self):
        body=self.payload(self.surface,self.unit)
        self.assertEqual(len(body),135)
        records=decode_hit_records(body)
        self.assertEqual(records[1],dict(kind=1,unit_uid='0x385',part_id=3))
        self.assertEqual(len(self.payload(self.unit)),116)
        with self.assertRaises(ValueError):decode_hit_records(self.payload(self.unit)+bytes(9))

    def test_count_thirty_allowed_thirty_one_rejected(self):
        self.assertEqual(len(decode_hit_records(self.payload(*([self.surface]*30)))),30)
        with self.assertRaises(ValueError):decode_hit_records(self.payload(*([self.unit]*31)))

    def test_short_count_records_unknown_tag_and_trailing_rejected(self):
        for body in (bytes(105),self.payload(self.surface)[:-1],self.payload(self.unit)[:-1],
                     self.payload(b'\x02'),self.payload()+b'X',bytes(104)+b'\0\1'):
            with self.subTest(length=len(body)),self.assertRaises(ValueError):decode_hit_records(body)

    def test_nonfinite_or_unbounded_surface_point_rejected(self):
        for number in (float('nan'),float('inf'),10000001):
            record=struct.pack('>BBBI3f',0,0,0,305,number,0,0)
            with self.subTest(number=number),self.assertRaises(ValueError):decode_hit_records(self.payload(record))

    def test_records_are_telemetry_not_additional_damage_or_feedback(self):
        actor,base=self.state()
        hit=base+self.payload(self.surface,self.unit)[104:]
        packets,event=actor.hit(hit,shooter_uid=10)
        self.assertEqual((actor.hp,len(actor.hits),event['collision_record_count']),(950,1,2))
        self.assertEqual([command for command,_ in packets],[0x1069,0x11ea,0x11eb])
        self.assertEqual(actor.hit(hit,shooter_uid=10)[1]['reason'],'duplicate_hit')
        self.assertEqual(actor.hp,950)

    def test_malformed_tail_does_not_commit_hit_or_hp(self):
        actor,base=self.state()
        with self.assertRaises(ValueError):actor.hit(base+self.payload(self.surface)[104:-1],shooter_uid=10)
        self.assertEqual((actor.hp,actor.hits),(1000,set()))
        self.assertEqual(actor.hit(base+bytes(2),shooter_uid=10)[1]['hp'],950)
