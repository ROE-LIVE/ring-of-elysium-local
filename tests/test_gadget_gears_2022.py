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


def read_obstacle_sync(body):
    """Lê o 0x74D0 na mesma ordem do decodificador do cliente (140ca8150 → 140ca7f80 → 140c29710…)."""
    o = 0

    def take(fmt):
        nonlocal o
        value = struct.unpack_from('>' + fmt, body, o)
        o += struct.calcsize('>' + fmt)
        return value

    out = {}
    _, _, out['config'] = take('QQI')
    take('iiiB'); take('3I'); take('I'); take('f')
    out['kind'] = take('I')[0]
    if out['kind'] == 2:
        size = take('I')[0]
        assert 0 < size <= 0x80
        out['name'] = body[o:o + size - 1].decode(); o += size
        take('3IQ3If3I')
        for _ in range(30):
            take('IQII')
            assert take('I')[0] == 0
            take('II')
        take('I'); take('11I')
        for limit in (10, 5, 10, 80, 10):
            assert take('I')[0] <= limit
        take('II')
        out['appearance'] = take('5i')
        take('B')
        for _ in range(take('I')[0]):
            _, rows = take('II')
            take('IIB' * rows)
        out['path'] = take('I')[0]
        take('iii4f' * out['path'])
        assert take('I')[0] == 0
    take('f'); take('3f')
    out['own'] = take('I')[0]
    assert o == len(body), (o, len(body))
    return out


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

    def test_bait_spawns_obstacle_type_2(self):
        e = self.e
        self.me['actor_display_name'] = 'Jogador1'
        # Trecho do ENTER_ROOM: aparência, flag e 1 grupo de acessórios (slot 7, 1 linha item/índice/flag).
        self.me['appearance_tail'] = (struct.pack('>5IB', 1, 2, 3, 4, 5, 1)
                                      + struct.pack('>III', 1, 7, 1) + struct.pack('>IIB', 9001, 0, 1))
        e.use_bait(None, None, self.me, bait_payload(3))
        (mine_uid, mine), (other_uid, theirs) = e.sent
        self.assertEqual((mine_uid, other_uid, mine[-1][0], theirs[0][0]), (ACTOR, OTHER, 0x74d0, 0x74d0))
        sync = read_obstacle_sync(mine[-1][1])
        self.assertEqual((sync['kind'], sync['config'], sync['name'], sync['appearance'], sync['path'], sync['own']),
                         (2, 201, 'Jogador1', (1, 2, 3, 4, 5), 3, 1))
        self.assertEqual(read_obstacle_sync(theirs[0][1])['own'], 0)

    def test_bait_spends_charge_once(self):
        e = self.e
        e.use_bait(None, None, self.me, bait_payload())
        self.assertEqual([c for c, _ in e.sent[0][1]], [0x74d4, 0x10d0, 0x1162, 0x74d0])
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

    def test_grapple_bc_to_room_and_resolve_to_owner(self):
        e = self.e
        kit = []
        self.me['weapon'].use_kit_charge = lambda index, now: kit.append(index) or True
        self.me['weapon'].kit_counts = lambda now: [(16, 2)]
        e.kit_charge_sync = lambda st, now: [(0x1162, b'kit')]
        e.use_grapple(None, None, self.me, bytes.fromhex(GRAPPLE_SAMPLE))
        self.assertEqual(kit, [16])
        # Nada vai ao dono no lançamento; o 0x3C vai aos outros com o UID do boneco remoto.
        [(other, theirs)] = e.sent
        self.assertEqual((other, [c for c, _ in theirs], 'grapple_charge_sync' in self.me), (OTHER, [0x3c], True))
        body = theirs[0][1]
        self.assertEqual(len(body), 66)
        self.assertEqual(struct.unpack_from('>QIBI', body), (AVATAR, 15, 31, 4096))
        # POS13 do jogador e do ponto de fixação (F32 arredondado para cm).
        self.assertEqual(struct.unpack_from('>iiiB', body, 23), (404384, 369462, 40359, 0))
        self.assertEqual(struct.unpack_from('>iii', body, 36), (403524, 368588, 40491))
        # O 0x3A sai à parte para o dono, depois de GRAPPLE_RESOLVE_DELAY (poll_gadgets).
        e.sent.clear()
        e.send_grapple_resolve(None, None, self.me, 'delay')
        self.assertEqual(([c for c, _ in e.sent[0][1]], 'grapple_resolve' in self.me), ([0x3a], False))
        resolve = e.sent[0][1][0][1]
        self.assertEqual(len(resolve), 42)
        self.assertEqual(struct.unpack_from('>IHiii', resolve), (15, 0, 403524, 368588, 40491))
        self.assertEqual(decode_grapple_request(bytes.fromhex(GRAPPLE_SAMPLE))['tail'][0], 41114)

    def test_stealth_energy_drains_and_turns_off(self):
        e = self.e
        e.use_stealth(None, None, self.me, True)
        self.assertEqual(self.me['stealth_energy'], 100)
        e.sent.clear()
        start = self.me['stealth_tick']
        e.drain_stealth(self.me, (None, None), start + 2.5)
        powers = [p for _, packets in e.sent for c, p in packets if c == 0x1069]
        self.assertEqual([struct.unpack('>QBBBii', p)[4] for p in powers], [94, 88, 82])
        e.drain_stealth(self.me, (None, None), start + 20)
        self.assertEqual((self.me['stealth_energy'], self.me['stealth']), (0, False))
        self.assertIn((0x2c, struct.pack('>QI', ACTOR, 83)), [pk for _, packets in e.sent for pk in packets])

    def test_medgun_weapon_in_bag(self):
        from weapon_probe_2022 import WeaponState, WeaponFixture
        from inventory_codec_2022 import decode_snapshot
        with_medgun = WeaponState(WeaponFixture(bytes(82), bytes(60), tactical=((21, 1),)), ACTOR)
        entries = decode_snapshot(with_medgun.inventory()).entries
        medgun = [e for e in entries if e.item.definition == 20006]
        self.assertEqual([(e.container, e.slot, e.item.item_type) for e in medgun], [(1, 9, 1)])
        # raw começa no tipo do item (registro +2): a capacidade do registro +56 fica em raw +54.
        self.assertEqual(struct.unpack_from('>I', medgun[0].item.raw, 54)[0], 12)
        self.assertEqual([(e.container, e.slot, e.item.category) for e in entries if e.item.definition == 70024],
                         [(2, 21, 35)])
        drone = WeaponState(WeaponFixture(bytes(82), bytes(60), tactical=((23, 1),)), ACTOR)
        self.assertEqual([e.item.definition for e in decode_snapshot(drone.inventory()).entries
                          if e.item.category == 35], [70022])
        without = WeaponState(WeaponFixture(bytes(82), bytes(60), tactical=((29, 1),)), ACTOR)
        self.assertFalse(any(e.item.definition == 20006 for e in decode_snapshot(without.inventory()).entries))

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
