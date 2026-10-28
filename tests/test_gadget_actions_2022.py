"""Barricada tática: formatos 0x74E0/0x74D0/0x74CF e uso com um único carregamento."""
import struct
import sys
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'server/directory'))
import gadget_actions_2022 as gadget
from gadget_actions_2022 import decode_barrier_request, encode_obstacle_sync, encode_obstacle_leave
from game_endpoint_probe_2022 import Endpoint


def request(x=1000, y=2000, z=300):
    return (struct.pack('>iiiB', x, y, z, 0) + struct.pack('>iiiB', x + 100, y, z, 0)
            + struct.pack('>If', 7, 90.0) + struct.pack('>3f', 0.0, 0.0, 1.0))


class GadgetTests(unittest.TestCase):
    def test_formats(self):
        r = decode_barrier_request(request())
        self.assertEqual((r['position'], r['point'], r['extra'], r['yaw'], r['rotation']),
                         ((1000, 2000, 300), (1100, 2000, 300), 7, 90.0, (0.0, 0.0, 1.0)))
        with self.assertRaises(ValueError):
            decode_barrier_request(bytes(45))
        body = encode_obstacle_sync(5, 9, (1, 2, 3), (0.0, 0.0, 1.0), True)
        # U64,U64,U32,POS13,12,U32×3,U32,3F,U32 = 8+8+4+13+12+12+4+12+4
        self.assertEqual(len(body), 77)
        self.assertEqual(struct.unpack_from('>QQI', body), (5, 9, 101))
        self.assertEqual(struct.unpack_from('>III', body, 45), (7500, 7500, 1))
        self.assertEqual(struct.unpack_from('>I', body, 73)[0], 1)
        self.assertEqual(encode_obstacle_leave(5), struct.pack('>QI', 5, 0))

    def endpoint(self):
        e = Endpoint.__new__(Endpoint)
        e.records, e.out = [], []
        e.capture = SimpleNamespace(record=lambda kind, **kw: e.records.append((kind, kw)))
        e.send_application_batch = lambda d, remote, st, packets: e.out.append((st['actor_uid'], packets))
        return e

    def state(self, uid, tactical=((27, 1),)):
        return dict(actor_uid=uid, room_uid=1, peer_avatar_anchor=(None, ('h', uid)), world=SimpleNamespace(dead=False),
                    weapon=SimpleNamespace(fixture=SimpleNamespace(tactical=tactical)))

    def test_barrier_once_then_rejected_and_removed_after_time(self):
        e = self.endpoint()
        a, b = self.state(5), self.state(6, ())
        e.sessions = {1: a, 2: b}
        e.use_barrier(None, None, a, request())
        own = dict(e.out[0][1])
        self.assertEqual(own[0x74e1], struct.pack('>I', 0))
        self.assertEqual(own[0x10d0], struct.pack('>II', 28, 0))
        self.assertEqual(struct.unpack_from('>I', own[0x74d0], 73)[0], 1)
        other = dict(e.out[1][1])
        self.assertEqual((e.out[1][0], struct.unpack_from('>I', other[0x74d0], 73)[0]), (6, 0))
        e.out.clear()
        e.use_barrier(None, None, a, request())
        self.assertEqual(e.out, [(5, [(0x74e1, struct.pack('>I', 1))])])
        e.out.clear()
        e.poll_gadgets(time.monotonic() + gadget.BARRIER_SECONDS + 1)
        self.assertEqual(sorted(uid for uid, _ in e.out), [5, 6])
        self.assertTrue(all(packets[0][0] == 0x74cf for _, packets in e.out))

    def test_player_without_barrier_tactic_is_refused(self):
        e = self.endpoint()
        b = self.state(6, ())
        e.sessions = {2: b}
        e.use_barrier(None, None, b, request())
        self.assertEqual(e.out, [(6, [(0x74e1, struct.pack('>I', 1))])])


if __name__ == '__main__':
    unittest.main()
