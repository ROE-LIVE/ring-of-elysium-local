"""Грани проверяют конечный луч; отказ сохраняет HP/броню и не выдаёт hitmarker."""
from dataclasses import replace
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'server/directory'))
from collision_triangle_2022 import load_triangles, segment_triangle_entry
from actor_probe_2022 import ActorFixture, ActorState


class TriangleTests(unittest.TestCase):
    triangle = ((2, -1, -1), (2, 1, -1), (2, -1, 1))

    def fixture(self):
        # Синтетические шаблоны: тесты не требуют игровых ресурсов/захватов.
        listing = bytearray(23);listing[0] = 1
        profile = struct.pack('>II',3,1)+bytes(1508)
        return ActorFixture(900,bytes(listing),profile,bytes(40),
                            (366000,544000,259060),((366000,544000,259060),),0,1000,50)

    def test_finite_segment_two_sides_edge_and_endpoint(self):
        for tri in (self.triangle, self.triangle[::-1]):
            self.assertAlmostEqual(segment_triangle_entry((0,-.5,-.5), (4,-.5,-.5), tri), .5)
            self.assertAlmostEqual(segment_triangle_entry((4,-.5,-.5), (0,-.5,-.5), tri), .5)
            self.assertEqual(segment_triangle_entry((0,0,0), (2,0,0), tri), 1)
            self.assertEqual(segment_triangle_entry((2,-1,-1), (4,-1,-1), tri), 0)
            self.assertIsNone(segment_triangle_entry((0,-.5,-.5), (1,-.5,-.5), tri))

    def test_inside_aabb_outside_triangle_does_not_block(self):
        self.assertIsNone(segment_triangle_entry((0,.75,.75), (4,.75,.75), self.triangle))
        self.assertIsNone(segment_triangle_entry((2,0,0), (2,1,0), self.triangle))
        self.assertIsNone(segment_triangle_entry((0,0,0), (0,0,0), self.triangle))

    def test_large_world_translation_and_nearly_parallel(self):
        delta = (371000,544000,259000)
        move = lambda p: tuple(a+b for a,b in zip(p,delta))
        tri = tuple(map(move,self.triangle))
        self.assertAlmostEqual(segment_triangle_entry(move((0,-.5,-.5)),move((4,-.5,-.5)),tri),.5)
        self.assertIsNone(segment_triangle_entry((2,-.5,-.5),(2+1e-14,.5,-.5),self.triangle))

    def test_parser_rejects_nonfinite_degenerate_bool_and_unbounded(self):
        valid = [[list(p) for p in self.triangle]]
        self.assertEqual(load_triangles(valid), (self.triangle,))
        self.assertEqual(load_triangles([]), ())
        for value in (None,{},[[]],[[[0,0,0],[1,1,1],[2,2,2]]],
                      [[[False,0,0],[1,0,0],[0,1,0]]],
                      [[[float('nan'),0,0],[1,0,0],[0,1,0]]],
                      [[[10000001,0,0],[1,0,0],[0,1,0]]],valid*65):
            with self.subTest(value=repr(value)[:60]),self.assertRaises(ValueError):
                load_triangles(value)

    def test_actor_triangle_rejection_is_atomic_and_open_target_still_hits(self):
        fixture = self.fixture()
        hit = bytearray(106)
        struct.pack_into('>IQ',hit,0,1,fixture.uid)
        struct.pack_into('>3f',hit,25,365073,543901,259245)
        struct.pack_into('>3i',hit,37,*fixture.position)
        struct.pack_into('>3f',hit,50,366002,544003,259155)
        hit[62] = 3
        struct.pack_into('>I',hit,88,4)
        struct.pack_into('>I',hit,96,14275)
        fire = struct.pack('>6fIBIIfII',365073,543901,259245,366062,544013,259155,4,0,14275,7,480,64,0)
        triangle = ((365500,543000,258000),(365500,546000,258000),(365500,543000,262000))
        actor = ActorState(replace(fixture,collision_triangles=(triangle,)))
        actor.begin(100);actor.note_fire(fire,{'action':'fire','gun_definition':10201})
        actor.armor_durability = 20
        packets,event = actor.hit(hit,shooter_uid=1)
        self.assertEqual((packets,event['reason'],event['blocking_triangle']),([],'line_of_sight',0))
        self.assertEqual((actor.hp,actor.armor_durability,actor.hits),(1000,20,set()))
        actor.fixture = replace(actor.fixture,collision_triangles=())
        packets,event = actor.hit(hit,shooter_uid=1)
        self.assertEqual((event['action'],event['validation']),('hit_damage','diagnostic_ray_triangles'))
        self.assertIn(0x11eb,[command for command,_ in packets])

    def test_fixture_keeps_triangles_opt_in(self):
        fixture = self.fixture()
        config = dict(uid=900,waypoints=[list(fixture.position)],speed_cm_seconds=0,hp=1000,pellet_damage=50)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'actor.json'
            for key,data in [('listing_file',fixture.listing),('profile_file',fixture.profile),('movement_file',fixture.movement)]:
                target = Path(tmp)/(key+'.fixture')
                target.write_bytes(data)
                config[key] = str(target)
            path.write_text(json.dumps(config))
            self.assertIsNone(ActorFixture.load(path).collision_triangles)
            config['collision_triangles'] = [[list(p) for p in self.triangle]]
            path.write_text(json.dumps(config))
            self.assertEqual(ActorFixture.load(path).collision_triangles,(self.triangle,))

    def test_bot_does_not_spend_ammunition_through_triangle(self):
        fixture = self.fixture()
        triangle = ((365500,543000,258000),(365500,546000,258000),(365500,543000,262000))
        bot = ActorState(replace(fixture,equipment=bytes(82),attack=(1500,50,3,2),
                         attack_ammunition=(2,6),collision_triangles=(triangle,)))
        bot.begin(100)
        player = (365100,544000,259100)
        bot.poll(0,0,player)
        self.assertEqual(bot.poll(3,75,player)[1],[])
        self.assertEqual((bot.magazine,bot.reserve,bot.spent_ammunition),(2,6,0))
        bot.fixture = replace(bot.fixture,collision_triangles=())
        packets,events = bot.poll(4,100,player)
        self.assertEqual(events[0]['action'],'bot_attack')
        self.assertEqual(events[0]['validation'],'diagnostic_ray_triangles')
        self.assertEqual((bot.magazine,bot.spent_ammunition),(1,1))
