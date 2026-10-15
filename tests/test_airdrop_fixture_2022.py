"""Primary26-byte notice и полный native501 без подмены ground/Jeep."""
from pathlib import Path
import struct,sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from airdrop_fixture_2022 import airdrop_notice,native_airdrop_entity,add_airdrop_notices
class AirdropFixtureTests(unittest.TestCase):
    def test_notice_two_pos13_and_signed_bounds(self):
        self.assertEqual(struct.unpack('>iiiBiiiB',airdrop_notice((1,-2,301000))), (1,-2,301000,0,0,0,0,0))
        for bad in [(True,2,3),(2**31,2,3),(1,2)]:
            with self.assertRaises(ValueError):airdrop_notice(bad)
    def test_native501_preserves_uid_xy_and_has_original_dynamic_tail(self):
        b=bytearray(117);struct.pack_into('>QI',b,0,456,501);struct.pack_into('>3i',b,20,100,200,300)
        native=native_airdrop_entity(bytes(b))
        self.assertEqual(len(native),117)
        self.assertEqual(struct.unpack_from('>QI',native),(456,501))
        self.assertEqual(struct.unpack_from('>3i',native,20),(100,200,301000))
        self.assertEqual(native[56],0);self.assertEqual(native[106],1)
        self.assertEqual(struct.unpack_from('>I',native,86)[0],20000)
        with self.assertRaises(ValueError):native_airdrop_entity(bytes(116))
    def test_notices_follow_only501_and_are_idempotent(self):
        b=bytearray(117);struct.pack_into('>I',b,8,501);struct.pack_into('>3i',b,20,100,200,300)
        s=[dict(responses=[dict(command='0x654b',payload_hex=b.hex())]),dict(responses=[])]
        add_airdrop_notices(s);add_airdrop_notices(s)
        self.assertEqual([x['command'] for x in s[0]['responses']],['0x654b','0x4a6'])
        self.assertEqual(s[1]['responses'],[])
        struct.pack_into('>I',b,8,102);s=[dict(responses=[dict(command='0x654b',payload_hex=b.hex())])]
        self.assertEqual(len(add_airdrop_notices(s)[0]['responses']),1)
