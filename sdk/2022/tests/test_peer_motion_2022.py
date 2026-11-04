"""Границы SC25 и преобразование реально выбранных полей движения2022."""
import math
import struct
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server/directory'))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from peer_motion_2022 import encode_peer_trajectory, encode_peer_stop, packed_direction
from roe_scene_2023 import decode_bc_move


class PeerMotionTests(unittest.TestCase):
    def test_stop_uses_native_fast_commit_branch_and_preserves_pose_through_wrap(self):
        for pose,event in ((0,1),(1,2),(2,3)):
            body=encode_peer_stop(123,(10,20,30),42,0xffffffff,pose,(1.,0.,0.))
            decoded=decode_bc_move(body)
            self.assertEqual((decoded['word_0'],decoded['count'],decoded['bytes']),(0,1,(event,0)))
            self.assertEqual(decoded['points'],[(0,0,0,0,0,0)])
            self.assertEqual(decoded['tail'],(0,32768,32768,42))
        with self.assertRaises(ValueError):encode_peer_stop(1,(10,20,30),1,1,9,(1.,0.,0.))

    def movement(self):
        return dict(points=[dict(position=(360233,543119,259507),bytes=(0,1,13),value=100),
                            dict(position=(360133,543169,259498),bytes=(0,0,7),value=105)],
                    word_1=500,bytes=(1,1,0),floats=(1.,0.,0.))

    def test_signed_delta_shared_anchor_timestamp_and_no_pose_override(self):
        body=encode_peer_trajectory(0x2040000100001,self.movement(),165,105)
        decoded=decode_bc_move(body)
        self.assertEqual(len(body),50)
        self.assertEqual(decoded['position'],(360233,543119,259507))
        self.assertEqual(decoded['points'],[(-100,50,-9,0,7,105)])
        self.assertEqual((decoded['word_0'],decoded['bytes'],decoded['value']),(500,(0,13),100))
        self.assertEqual(decoded['tail'],(1,32768,32768,165))

    def test_one_point_and_maximum_points(self):
        movement=self.movement();movement['points']=movement['points'][:1]
        self.assertEqual(len(encode_peer_trajectory(1,movement,1,100)),38)
        movement['points']*=20
        self.assertEqual(len(encode_peer_trajectory(1,movement,1,100)),266)
        movement['points'].append(movement['points'][0])
        with self.assertRaises(ValueError):encode_peer_trajectory(1,movement,1,100)

    def test_clock_wrap_is_valid_but_stale_and_reversed_paths_are_rejected(self):
        movement=self.movement()
        movement['points'][0]['value']=0xfffffffe;movement['points'][1]['value']=2
        self.assertEqual(decode_bc_move(encode_peer_trajectory(1,movement,1,2))['value'],0xfffffffe)
        for first,last in ((100,99),(100,500),(0xfffffff0,0xffffffef)):
            movement['points'][0]['value']=first;movement['points'][1]['value']=last
            with self.assertRaises(ValueError):encode_peer_trajectory(1,movement,1,last)

    def test_unsupported_flags_speed_fraction_and_far_nodes_rejected(self):
        cases=[('flags',64),('speed',65536),('fraction',40),('position',(363234,543119,259507))]
        for field,value in cases:
            movement=self.movement()
            if field=='flags':movement['bytes']=(value,1,0)
            elif field=='speed':movement['word_1']=value
            elif field=='fraction':movement['points'][0]['bytes']=(0,1,value)
            else:movement['points'][1]['position']=value
            with self.subTest(field=field),self.assertRaises(ValueError):
                encode_peer_trajectory(1,movement,1,105)

    def test_observed_cardinal_flags_survive_without_facing_rotation(self):
        for flags in (*range(9),33):
            movement=self.movement();movement['bytes']=(flags,1,0)
            self.assertEqual(decode_bc_move(encode_peer_trajectory(1,movement,1,105))['tail'],
                             (flags,32768,32768,1))
        movement=self.movement();movement['points'][1]['value']=100
        with self.assertRaises(ValueError):encode_peer_trajectory(1,movement,1,100)

    def test_direction_quantization_normalization_and_nonfinite_guard(self):
        self.assertEqual(packed_direction((2,0,0)),(32768,32768))
        self.assertEqual(packed_direction((0,0,2)),(32768,65535))
        self.assertEqual(packed_direction((0,0,0)),(32768,32768))
        u,v=packed_direction((1,1,-1))
        a=(u/65535*2-1)*math.pi;z=v/65535*2-1
        self.assertAlmostEqual(math.cos(a)*math.sqrt(1-z*z),1/math.sqrt(3),places=4)
        with self.assertRaises(ValueError):packed_direction((float('nan'),0,0))
