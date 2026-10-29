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
                    weapon=self.weapon(uid, tactical))

    def weapon(self, uid, tactical):
        # WeaponState real: o 0x1162 sai pelo ability_cd_sync (kit + táticos com os usos atuais).
        from weapon_probe_2022 import WeaponState, WeaponFixture
        return WeaponState(WeaponFixture(bytes(82), bytes(60), tactical=tactical), uid)

    def test_barrier_once_then_rejected_and_removed_after_time(self):
        e = self.endpoint()
        a, b = self.state(5), self.state(6, ())
        e.sessions = {1: a, 2: b}
        e.use_barrier(None, None, a, request())
        own = dict(e.out[0][1])
        self.assertEqual(own[0x74e1], struct.pack('>I', 0))
        self.assertEqual(own[0x10d0], struct.pack('>II', 28, 0))
        self.assertEqual(own[0x1162], struct.pack('>QI', 5, 1) + struct.pack('>III', 6, 0, 0))
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

    def test_scanner_use_spends_charge_and_mark_notifies_marked_player(self):
        e = self.endpoint()
        e.emitted = []
        e.emit_peer_avatars = lambda outputs, events: e.emitted.extend(outputs)
        a, b = self.state(5, ((37, 1),)), self.state(6, ())
        e.peer_avatars = SimpleNamespace(members={(1, 5): dict(state=a, avatar=0x9005),
                                                  (1, 6): dict(state=b, avatar=0x9006)})
        e.use_scanner(None, None, a)
        own = dict(e.out[0][1])
        self.assertEqual(own[0x10d0], struct.pack('>II', 38, 0))
        self.assertEqual(own[0x1162], struct.pack('>QI', 5, 1) + struct.pack('>III', 9, 0, 0))
        e.scanner_mark(a, struct.pack('>Q', 0x9006))
        self.assertEqual(e.emitted, [(b, [(0x1168, struct.pack('>Q', 0x9006)), (0x1166, b'\x01')])])
        # O aviso de detectado (0x1166) desliga ao fim de mMarkCloseTime, só uma vez.
        e.emitted.clear()
        e.poll_gadgets(time.monotonic() + 1)
        self.assertEqual(e.emitted, [])
        e.poll_gadgets(time.monotonic() + gadget.SCANNER_MARK_SECONDS + 1)
        e.poll_gadgets(time.monotonic() + gadget.SCANNER_MARK_SECONDS + 2)
        self.assertEqual(e.emitted, [(b, [(0x1166, b'\x00')])])
        # Sem uso: nada é mandado; marca de unidade desconhecida (NPC) só vai para o log.
        e.out.clear(); e.emitted.clear()
        e.use_scanner(None, None, a)
        e.scanner_mark(a, struct.pack('>Q', 0x1234))
        self.assertEqual((e.out, e.emitted), ([], []))
        self.assertEqual(gadget.eu_action(struct.pack('>I', 72)), gadget.AT_USE_SCANNER)

    def test_client_data_from_scanner_returns_to_sender_as_ntf(self):
        # Amostra real do PC2 (28/10): tipo 15, unit do host + posição, bBc_to_ob 1.
        sample = bytes.fromhex('0000000f0100000014010010000004020040b29848c0b9e748004f154701')
        r = gadget.decode_client_data(sample)
        self.assertEqual((r['kind'], r['bc_type'], r['to_ob']), (gadget.CLIENT_DATA_SCANNER, 1, 1))
        self.assertEqual(struct.unpack_from('<Q', r['data'])[0], 0x0002040000100001)
        with self.assertRaises(ValueError):
            gadget.decode_client_data(sample[:-1])
        e = self.endpoint()
        a = self.state(5, ((37, 1),))
        e.client_data(None, None, a, sample)
        self.assertEqual(e.out, [(5, [(0x11ca, struct.pack('>QII', 5, 15, 20) + r['data'])])])

    def test_player_without_barrier_tactic_is_refused(self):
        e = self.endpoint()
        b = self.state(6, ())
        e.sessions = {2: b}
        e.use_barrier(None, None, b, request())
        self.assertEqual(e.out, [(6, [(0x74e1, struct.pack('>I', 1))])])


if __name__ == '__main__':
    unittest.main()
