"""Táticos novos: holograma (0x74D3 → 0x74D4), capa (0x536 71/73 → 0x2B/0x2C 83) e Medgun em si (0x117B → 0x117C)."""
import struct
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'server/directory'))
from game_endpoint_probe_2022 import Endpoint
from gadget_actions_2022 import decode_bait_request, decode_grapple_request

ACTOR, OTHER, AVATAR = 0x242C, 0x885C, 0x777
# 0x3B real (sessão 20261030T184624, 128 bytes com o bloco da versão >= 99).
GRAPPLE_SAMPLE = ('0000000f1f00001000bf462d7cbf220dea0000000000000000000000062ba00005a33600009da7000000000000000000'
                  '0048c583b448b47c1d471e71b648c5087648b3f97d471e2b1000240025ffb310a09a7d2ba09afff7209b' + '00' * 38)


def bait_payload(points=2):
    body = struct.pack('>iiiB', 100, 200, 300, 0) + struct.pack('>4f', 0, 0, 0, 1) + struct.pack('>i', points)
    for i in range(points):
        body += struct.pack('>iii4f', 100 + i * 50, 200, 300, 0, 0, 0, 1)
    return body + struct.pack('>I', 9) + struct.pack('>3f', 0, 0, 1)


def session(actor, tactical):
    weapon = SimpleNamespace(fixture=SimpleNamespace(tactical=tactical),
                             ability_cd_sync=lambda counts: (0x1162, bytes(sorted(counts.values()))))
    return dict(actor_uid=actor, room_uid=7, weapon=weapon, peer_avatar_anchor=(actor, None, 0),
                world=SimpleNamespace(dead=False, hp=500))


class Gears(unittest.TestCase):
    def setUp(self):
        e = self.e = Endpoint.__new__(Endpoint)
        e.sent, e.records = [], []
        e.capture = SimpleNamespace(record=lambda kind, **kw: e.records.append((kind, kw)))
        e.send_application_batch = lambda d, r, st, packets: e.sent.append((st['actor_uid'], packets))
        e.peer_avatars = SimpleNamespace(members={(7, ACTOR): dict(avatar=AVATAR)})
        self.me, self.other = session(ACTOR, ((29, 1),)), session(OTHER, ())
        e.room_sessions = lambda room: [self.me, self.other]

    def test_bait_decoder(self):
        req = decode_bait_request(bait_payload(3))
        self.assertEqual((req['position'], len(req['path']), req['extra']), ((100, 200, 300), 3, 9))
        with self.assertRaises(ValueError):
            decode_bait_request(bait_payload(1)[:-1])

    def test_bait_spends_charge_once(self):
        e = self.e
        e.use_bait(None, None, self.me, bait_payload())
        self.assertEqual([c for c, _ in e.sent[0][1]], [0x74d4, 0x10d0, 0x1162])
        self.assertEqual(e.sent[0][1][0][1], struct.pack('>i', 0))
        self.assertEqual(struct.unpack('>II', e.sent[0][1][1][1]), (30, 0))
        e.sent.clear()
        e.use_bait(None, None, self.me, bait_payload())
        self.assertEqual(e.sent, [(ACTOR, [(0x74d4, struct.pack('>i', 1))])])
        self.assertEqual(e.records[-1][1]['reason'], 'no_charge_or_dead')

    def test_stealth_on_off(self):
        e = self.e
        e.use_stealth(None, None, self.me, True)
        self.assertEqual(e.sent, [(ACTOR, [(0x2b, struct.pack('>QI', ACTOR, 83))]),
                                  (OTHER, [(0x2b, struct.pack('>QI', AVATAR, 83))])])
        e.sent.clear()
        e.use_stealth(None, None, self.me, False)
        self.assertEqual([p[0][0] for _, p in e.sent], [0x2c, 0x2c])

    def test_grapple_bc_to_self_and_room(self):
        e = self.e
        kit = []
        self.me['weapon'].use_kit_charge = lambda index, now: kit.append(index) or True
        self.me['weapon'].kit_counts = lambda now: [(16, 2)]
        e.kit_charge_sync = lambda st, now: [(0x1162, b'kit')]
        e.use_grapple(None, None, self.me, bytes.fromhex(GRAPPLE_SAMPLE))
        self.assertEqual(kit, [16])
        (who, mine), (other, theirs) = e.sent
        self.assertEqual(([c for c, _ in mine], who, other), ([0x3c, 0x1162], ACTOR, OTHER))
        body = mine[0][1]
        self.assertEqual(len(body), 66)
        self.assertEqual(struct.unpack_from('>QIBI', body), (ACTOR, 15, 31, 4096))
        # POS13 do jogador e do ponto de fixação (F32 arredondado para cm).
        self.assertEqual(struct.unpack_from('>iiiB', body, 23), (404384, 369462, 40359, 0))
        self.assertEqual(struct.unpack_from('>iii', body, 36), (403524, 368588, 40491))
        self.assertEqual(struct.unpack_from('>Q', theirs[0][1])[0], AVATAR)
        self.assertEqual(decode_grapple_request(bytes.fromhex(GRAPPLE_SAMPLE))['tail'][0], 41114)

    def test_heal_gun_oneself(self):
        e = self.e
        e.heal_gun_oneself(None, None, self.me, struct.pack('>i', 30010))
        self.assertEqual(e.sent, [(ACTOR, [(0x117c, struct.pack('>i', 0))])])
        self.assertEqual(len(self.me['heal_gun_pulses']), 10)
        self.me['world'].dead = True
        e.heal_gun_oneself(None, None, self.me, struct.pack('>i', 30010))
        self.assertEqual(e.sent[-1], (ACTOR, [(0x117c, struct.pack('>i', 1))]))


if __name__ == '__main__':
    unittest.main()
