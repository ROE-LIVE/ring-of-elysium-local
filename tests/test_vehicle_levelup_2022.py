"""Kit de modificação (REFIT): LEVELUP_REQ → RSP + START_LEVELUP_BC; 5 s depois LEVELUP_BC, vida nova e uso gasto."""
import struct
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'server/directory'))
from game_endpoint_probe_2022 import Endpoint
from vehicle_levelup_2022 import (VehicleLevelups, decode_levelup_request, encode_levelup_response,
                                  encode_levelup_bc, encode_start_levelup_bc, SINGING_SECONDS)

UID, ACTOR, OTHER = 0x0005040000160039, 0x515BB1E1DD242C, 0x515BB18E59C77C


class Formats(unittest.TestCase):
    def test_sizes_match_client_decoders(self):
        self.assertEqual(decode_levelup_request(struct.pack('>QB', UID, 0)), (UID, 0))   # 140bf35d0
        self.assertEqual(len(encode_levelup_response(0, UID, 0)), 13)                   # 140c01ac0
        self.assertEqual(len(encode_levelup_bc(UID, 1, 0)), 10)                          # 140c9ca90
        self.assertEqual(len(encode_start_levelup_bc(UID, ACTOR)), 16)                   # 0x6593: 2×U64
        with self.assertRaises(ValueError):
            decode_levelup_request(b'\x00' * 8)

    def test_reject_reasons(self):
        lv = VehicleLevelups()
        jeep = dict(configuration=102, hp=21600)
        self.assertEqual(lv.reject_reason(dict(configuration=109, hp=1), UID, False, 1, False), 'model_without_level')
        self.assertEqual(lv.reject_reason(jeep, UID, True, 1, False), 'vehicle_has_member')
        self.assertEqual(lv.reject_reason(jeep, UID, False, 0, False), 'no_refit_charge')
        self.assertIsNone(lv.reject_reason(jeep, UID, False, 1, False))
        lv.start(UID, ACTOR, 0, 0)
        self.assertEqual(lv.reject_reason(jeep, UID, False, 1, False), 'already_levelling')
        self.assertEqual(lv.due(SINGING_SECONDS - 0.1), [])
        self.assertEqual(lv.due(SINGING_SECONDS), [(UID, ACTOR, 0)])
        self.assertEqual(lv.reject_reason(jeep, UID, False, 1, False), 'already_level1')


def session(actor, sent):
    vehicles = SimpleNamespace(vehicles={UID: dict(configuration=102, hp=21600, status=1)}, seated=None)
    weapon = SimpleNamespace(fixture=SimpleNamespace(tactical=((25, 1),)),
                             ability_cd_sync=lambda counts: (0x1162, bytes([counts.get(25, 0)])))
    st = dict(actor_uid=actor, room_uid=7, vehicles=vehicles, weapon=weapon)
    st['peer_avatar_anchor'] = (actor, None, 0)
    return st


class EndpointFlow(unittest.TestCase):
    def setUp(self):
        e = self.e = Endpoint.__new__(Endpoint)
        e.shared_vehicles = None
        e.sent, e.records = [], []
        e.capture = SimpleNamespace(record=lambda kind, **kw: e.records.append(kw))
        e.send_application_batch = lambda d, remote, st, packets: e.sent.append((st['actor_uid'], packets))
        self.me, self.other = session(ACTOR, e.sent), session(OTHER, e.sent)
        e.room_sessions = lambda room: [self.me, self.other]

    def test_start_then_finish(self):
        e = self.e
        e.vehicle_levelup_request(None, None, self.me, struct.pack('>QB', UID, 0))
        self.assertEqual([c for c, _ in e.sent[0][1]], [0x6538, 0x6593])
        self.assertEqual(struct.unpack('>iQB', e.sent[0][1][0][1]), (0, UID, 0))
        self.assertEqual(e.sent[1], (OTHER, [(0x6593, encode_start_levelup_bc(UID, ACTOR))]))
        e.sent.clear()
        e.finish_vehicle_levelups(float('inf'))
        mine = dict(e.sent)[ACTOR]
        self.assertEqual([c for c, _ in mine], [0x6539, 0x6554, 0x10d0, 0x1162])
        self.assertEqual(struct.unpack('>QII', mine[1][1]), (UID, 34560, 1))
        self.assertEqual(struct.unpack('>II', mine[2][1]), (26, 0))                    # REFIT usado
        self.assertEqual([c for c, _ in dict(e.sent)[OTHER]], [0x6539, 0x6554])
        self.assertEqual(self.other['vehicles'].vehicles[UID]['hp'], 34560)

    def test_no_charge_is_rejected(self):
        e = self.e
        self.me['gadget_counts'] = {25: 0}
        e.vehicle_levelup_request(None, None, self.me, struct.pack('>QB', UID, 0))
        self.assertEqual(e.sent, [(ACTOR, [(0x6538, encode_levelup_response(1, UID, 0))])])
        self.assertEqual(e.records[-1]['reason'], 'no_refit_charge')


if __name__ == '__main__':
    unittest.main()
