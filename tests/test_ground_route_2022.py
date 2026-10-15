"""Рёбра наземного патруля: обход, высота, ограничения и отсутствие shortcuts."""
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from copy import deepcopy
from dataclasses import replace

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server/directory'))
from ground_route_2022 import GroundRoute,crosses_xy_box
from actor_probe_2022 import ActorFixture,ActorState
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from roe_scene_2023 import decode_bc_move


class GroundRouteTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.config=dict(version=1,build='2022-0.2.989.0-x64',map_id=16010,
                         source='Проверенная тестовая траектория',original_navmesh=False,
                         nodes=[dict(id='a',position=[0,0,100]),dict(id='b',position=[0,300,130]),
                                dict(id='c',position=[600,300,160]),dict(id='d',position=[600,0,190])],
                         edges=[['a','b'],['b','c'],['c','d']],patrol_targets=['a','d'],
                         clearance_boxes=[[[200,-100,0],[400,200,500]]])

    def load(self,config=None):
        path=self.root/'graph.json';path.write_text(json.dumps(config or self.config))
        return GroundRoute.load(path)

    def test_path_follows_edges_both_ways_with_original_node_heights(self):
        route=self.load()
        self.assertEqual(route.path('a','d'),('a','b','c','d'))
        self.assertEqual(route.path('d','a'),('d','c','b','a'))
        self.assertEqual(route.patrol_waypoints(),((0,0,100),(0,300,130),(600,300,160),(600,0,190),(600,300,160),(0,300,130)))

    def test_direct_shortcut_through_box_is_rejected_even_above_rock(self):
        config=deepcopy(self.config);config['edges'].append(['a','d'])
        with self.assertRaisesRegex(ValueError,'преграду'):self.load(config)
        self.assertTrue(crosses_xy_box((0,0,900),(600,0,900),(200,-100,0),(400,200,500)))
        self.assertFalse(crosses_xy_box((0,300,100),(600,300,100),(200,-100,0),(400,200,500)))

    def test_disconnected_target_duplicate_edges_and_foreign_build_fail(self):
        for change in [dict(edges=[['a','b'],['b','c']]),dict(edges=[['a','b'],['b','a']]),
                       dict(build='V99'),dict(original_navmesh=True),dict(source='')]:
            with self.subTest(change=change),self.assertRaises(ValueError):
                self.load(dict(self.config,**change))

    def test_nonfinite_long_vertical_invalid_nodes_and_size_fail(self):
        for position in [[0,0,float('nan')],[0,0,0],[0,300,600],[0,2000,130]]:
            config=deepcopy(self.config);config['nodes'][1]['position']=position
            with self.subTest(position=position),self.assertRaises(ValueError):self.load(config)
        config=deepcopy(self.config);config['nodes'][1]=None
        with self.assertRaises(ValueError):self.load(config)
        path=self.root/'huge.json';path.write_text(' '*65537)
        with self.assertRaises(ValueError):GroundRoute.load(path)

    def test_fixture_rebinds_listing_profile_and_patrol_never_cuts_corner(self):
        route=self.load();profile=bytearray(1516);struct.pack_into('>II',profile,0,3,1)
        for name,body in [('listing.bin',bytes([1])+bytes(22)),('profile.bin',profile),('movement.bin',bytes(40))]:
            (self.root/name).write_bytes(body)
        config=dict(uid='0x2040000123460',listing_file='listing.bin',profile_file='profile.bin',
                    movement_file='movement.bin',waypoints=[[999,999,999]],speed_cm_seconds=100,
                    hp=1000,pellet_damage=50,ground_route_file='graph.json')
        path=self.root/'actor.json';path.write_text(json.dumps(config))
        fixture=ActorFixture.load(path);self.assertEqual(fixture.position,(0,0,100))
        self.assertEqual(struct.unpack_from('>3i',fixture.listing,1),(0,0,100))
        self.assertEqual(struct.unpack_from('>3i',fixture.profile,1051),(0,0,100))
        state=ActorState(fixture);last=state.position
        for tick in range(75):
            state.patrol(tick/2,tick)
            self.assertFalse(crosses_xy_box(last,state.position,*route.clearance_boxes[0]))
            last=state.position
        self.assertTrue(100<=state.position[2]<=190)

    def animated(self):
        route=self.load();points=route.patrol_waypoints()
        fixture=ActorFixture(99,b'',b'',bytes(40),points[0],points,500,1000,50,
                             ground_route=route,movement_animation=True)
        return ActorState(fixture)

    def test_animated_multi_edge_frame_preserves_corner_time_and_sequence_wrap(self):
        state=self.animated();state.motion_sequence=0xffffffff
        state.patrol(0,0xfffffff0)
        packets,_=state.patrol(2,34)
        self.assertEqual([code for code,_ in packets],[0x25])
        decoded=decode_bc_move(packets[0][1]);self.assertEqual(decoded['word_0'],500)
        self.assertEqual(decoded['position'],(0,0,100));self.assertEqual(decoded['count'],3)
        points=[decoded['position']]+[tuple(a+b for a,b in zip(decoded['position'],node[:3])) for node in decoded['points']]
        self.assertEqual(points[1:3],[(0,300,130),(600,300,160)])
        self.assertEqual(decoded['tail'][-1],0)
        for a,b in zip(points,points[1:]):
            self.assertFalse(crosses_xy_box(a,b,*state.fixture.ground_route.clearance_boxes[0]))

    def test_animated_pause_fast_stop_once_and_death_has_no_motion(self):
        state=self.animated();state.patrol(0,0);state.patrol(1,25)
        state.fixture=replace(state.fixture,speed=0)
        packets,_=state.patrol(1.01,26);decoded=decode_bc_move(packets[0][1])
        self.assertEqual((decoded['word_0'],decoded['bytes'][0],decoded['count']),(0,1,1))
        self.assertEqual(state.patrol(1.2,30),([],[]))
        state.hp=0;state.started=True
        self.assertEqual(state.poll(2,50),([],[]))

    def test_attack_pauses_once_then_resumes_without_spending_pause_distance(self):
        state=self.animated()
        state.fixture=replace(state.fixture,equipment=bytes(82),attack=(1000,25,3,2),
                              attack_pause_seconds=1,attack_ammunition=(2,1))
        state.magazine,state.reserve=2,1;state.started=True;state.started_at=0
        state.patrol(0,0);state.patrol(1,25)
        packets,events=state.poll(2,50,(50,50,100))
        self.assertIn('bot_attack',[x['action'] for x in events])
        stops=[body for code,body in packets if code==0x25]
        self.assertEqual(decode_bc_move(stops[0])['word_0'],0)
        frozen=state.position
        packets,_=state.poll(2.8,70,(50,50,100))
        self.assertEqual(state.position,frozen);self.assertFalse(any(code==0x25 for code,_ in packets))
        packets,_=state.poll(3.2,80,(50,50,100))
        moving=[body for code,body in packets if code==0x25]
        self.assertGreater(decode_bc_move(moving[0])['word_0'],0)
        self.assertEqual(state.magazine,1)
