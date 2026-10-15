"""Контракт native379, ограничения запросов и независимость состояния стекла."""
import struct
import sys
from pathlib import Path
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server/directory'))
from breakable_state_2022 import BreakableFixture, BreakableState, decode_damage


def request(actor=42, identifier=7690, damage=1000, part=0):
    context=bytearray(72)
    struct.pack_into('<QI',context,0,actor,part)
    struct.pack_into('<3f',context,12,417391,557270,259595)
    struct.pack_into('<f',context,48,1000)
    return struct.pack('>III',identifier,1,damage)+b'\x48'+context


class BreakableTests(unittest.TestCase):
    def setUp(self):
        self.fixture=BreakableFixture({7690:((417391,557270,259595),(1,))})
        self.state=BreakableState(self.fixture,42)
        self.position=(417300,557270,259419)

    def test_native_shape_preserves_context_and_absolute_remaining(self):
        payload=request();identifier,damage,context,actor,part=decode_damage(payload)
        self.assertEqual((identifier,damage,actor,part),(7690,(1000,),42,0))
        replies,event=self.state.handle(payload,self.position)
        self.assertEqual(event['remaining'],[0]);self.assertTrue(event['changed'])
        opcode,body=replies[0]
        self.assertEqual((opcode,len(body)),(0x6f56,97))
        self.assertEqual(struct.unpack_from('>IIBBBIB',body),(1,7690,0,0,1,0,72))
        self.assertEqual(body[16:88],context)
        self.assertEqual(body[88:],b'\0'*9)

    def test_invalid_and_foreign_requests_leave_state_unchanged(self):
        for payload in [request()[:-1],request(actor=43),request(identifier=7691),request(part=1),request(damage=1000001)]:
            with self.subTest(payload=payload[:12]):
                replies,event=self.state.handle(payload,self.position)
                self.assertFalse(replies);self.assertEqual(event['action'],'breakable_rejected')
                self.assertEqual(self.state.remaining[7690],[1])
        for position in [None,(0,0,0),(float('nan'),0,0)]:
            self.assertFalse(self.state.handle(request(),position)[0])

    def test_nonfinite_context_rejected_before_any_reply(self):
        payload=bytearray(request());struct.pack_into('<f',payload,13+12,float('nan'))
        self.assertFalse(self.state.handle(payload,self.position)[0])

    def test_duplicate_and_resume_keep_context_and_session_isolation(self):
        first,event=self.state.handle(request(),self.position)
        second,event=self.state.handle(request(damage=1),self.position)
        self.assertFalse(event['changed']);self.assertEqual(first,second)
        self.assertFalse(self.state.snapshot(self.position));self.state.resume()
        self.assertEqual(self.state.snapshot(self.position),first)
        self.assertFalse(self.state.snapshot(self.position))
        other=BreakableState(self.fixture,43)
        self.assertEqual(other.remaining[7690],[1]);self.assertFalse(other.contexts)


if __name__=='__main__':
    unittest.main()
