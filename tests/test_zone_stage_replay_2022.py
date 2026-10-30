"""Saída da área fechada: 0x481 da fase anterior e depois o da atual (as cinzas somem; sessão 20261030T005337)."""
import struct
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'server/directory'))
from world_probe_2022 import WorldFixture, WorldState, encode_shrink
from game_endpoint_probe_2022 import Endpoint

# Grade falsa: o x da posição é o número da região.
GRID = SimpleNamespace(regions=lambda position: frozenset({position[0]}))


def endpoint():
    e = Endpoint.__new__(Endpoint)
    e.started = 0
    e.records, e.out = [], []
    e.capture = SimpleNamespace(record=lambda kind, **kw: e.records.append((kind, kw)))
    e.send_application = lambda d, remote, st, command, payload: e.out.append((command, payload))
    return e


def two_stages():
    # Fase 10: seguras 1..4; fase 20 fecha a 4.
    fixture = WorldFixture(1000, 100, (10, 20, 30, 40), 50, 1,
                           ((0, 10, encode_shrink(300, 10, [1, 2, 3], [1, 2, 3, 4])),
                            (5, 20, encode_shrink(300, 20, [3], [1, 2, 3]))),
                           region_grid=GRID,
                           stage_safe=(frozenset({1, 2, 3, 4}), frozenset({1, 2, 3})),
                           stage_future=(frozenset({1, 2, 3}), frozenset({3})), hazard_enabled=False)
    w = WorldState(fixture, 42, 0)
    w.poll(0)
    return w


class ZoneStageReplayTests(unittest.TestCase):
    def test_previous_then_current(self):
        e, w = endpoint(), two_stages()
        self.assertIsNone(w.previous_stage_snapshot(1))           # só a primeira fase aplicada
        w.poll(6)
        e.replay_zone_stage(None, None, {}, w, 6)
        self.assertEqual([c for c, _ in e.out], [0x481, 0x481])
        self.assertEqual([struct.unpack_from('>I', p, len(p)-4)[0] for _, p in e.out], [10, 20])
        self.assertEqual(e.records[-1][1]['reason'], 'closed_zone_leave_replay')
        self.assertEqual(e.records[-1][1]['previous_stage'], 10)

    def test_first_stage_has_no_replay(self):
        e, w = endpoint(), two_stages()
        e.replay_zone_stage(None, None, {}, w, 1)
        self.assertEqual(e.out, [])

    def test_no_position_confirmation(self):
        # O 0x27 não muda o estado no cliente (posição atual, 1411bb640) e derrubava a asa-delta.
        e, w = endpoint(), two_stages()
        w.poll(6)
        e.replay_zone_stage(None, None, {'scene_position_sync': bytes(40)}, w, 6)
        self.assertNotIn(0x27, [c for c, _ in e.out])


    def test_seated_marks_replay_after_getoff(self):
        # Sentado, o reenvio não limpava as cinzas (motorista, sessão 20261030T013558): repetir ao descer.
        e, w = endpoint(), two_stages()
        w.poll(6)
        seated = {'vehicles': SimpleNamespace(seated=0x5040000160039)}
        e.replay_zone_stage(None, None, seated, w, 6)
        self.assertTrue(seated['zone_replay_after_getoff'])
        seated['vehicles'].seated = None
        e.replay_zone_stage(None, None, seated, w, 7, reason='vehicle_getoff_replay')
        self.assertFalse(seated['zone_replay_after_getoff'])
        self.assertEqual(e.records[-1][1]['reason'], 'vehicle_getoff_replay')


if __name__ == '__main__':
    unittest.main()
