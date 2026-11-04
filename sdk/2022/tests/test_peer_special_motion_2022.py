"""Специальное движение не даёт произвольный teleport/чужой attachment."""
import struct,sys,unittest
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'server/directory'),str(Path(__file__).resolve().parents[1]/'tools')]
from peer_special_motion_2022 import decode_rope_motion
from peer_motion_2022 import encode_peer_trajectory
from roe_scene_2023 import decode_bc_move
ROPE=0x5040000123459


def wire():
    return (struct.pack('>I',2)+b''.join(struct.pack('>iiiBBBI',371384,543175,z,0,0,11,t)for z,t in((259077,5581),(259087,5582)))+
        struct.pack('>IB3fIIBB',426,33,-1.,0.,0.,0,163,0,2)+struct.pack('>BQ',1,ROPE)*2+b'\4abcd\x20'+bytes(32))


class SpecialMotionTests(unittest.TestCase):
    def decode(self,payload):return decode_rope_motion(payload,{ROPE:123},{ROPE:(371384,543175,259077)})
    def test_observed_rope_layout_becomes_clocked_trajectory_with_native_mode2_bit(self):
        payload=wire();self.assertEqual(len(payload),125);m=self.decode(payload)
        self.assertEqual(m['rope_uid'],ROPE);self.assertEqual(m['extra_lengths'],[4,32]);self.assertEqual(m['spec_extra'],b'abcd')
        decoded=decode_bc_move(encode_peer_trajectory(123,m,7,5582))
        self.assertEqual(decoded['position'],(371384,543175,259077))
        self.assertEqual(decoded['points'],[(0,0,10,0,11,5582)])
        self.assertEqual(decoded['tail'][0],33)
    def test_truncation_unknown_mode_oversized_strings_and_unknown_rope_rejected(self):
        b=wire()
        candidates=[b[:i]for i in(0,4,60,88,124)]+[b+b'0']
        for offset,value in((46,64),(87,33),(69,0)):
            x=bytearray(b);x[offset]=value;candidates.append(bytes(x))
        for payload in candidates:
            with self.assertRaises(ValueError):self.decode(payload)
        with self.assertRaises(ValueError):decode_rope_motion(b,{}, {})
    def test_far_position_and_nonfinite_direction_rejected(self):
        for offset,fmt,value in((4,'>i',999999),(47,'>f',float('nan'))):
            b=bytearray(wire());struct.pack_into(fmt,b,offset,value)
            with self.assertRaises(ValueError):self.decode(b)
