"""Saída da área fechada: no chão e fora do carro, 0x27 da posição atual + 0x481 da fase anterior e da atual."""
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
    e.register_fixture_entity = lambda st, command, payload: st.update(scene_position_sync=payload)
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

    def test_position_confirmed_before_double_stage(self):
        # Só o par (0x27 + 0x481 duplo) limpou as cinzas (sessões 005337 × 234244 × 013558).
        e, w = endpoint(), two_stages()
        w.poll(6)
        st = dict(actor_uid=42, scene_position_sync=bytes(40), last_movement_position=(3, 5, 7))
        e.replay_zone_stage(None, None, st, w, 6)
        self.assertEqual([c for c, _ in e.out], [0x27, 0x481, 0x481])
        self.assertEqual(struct.unpack_from('>Q3i', e.out[0][1]), (42, 3, 5, 7))
        self.assertTrue(e.records[-1][1]['position_confirmed'])

    def test_pending_waits_for_ground_and_getoff(self):
        e, w = endpoint(), two_stages()
        w.poll(6)
        st = dict(actor_uid=42, zone_replay_pending=True, movement_event=24,
                  vehicles=SimpleNamespace(seated=None))
        e.flush_zone_replay(None, None, st, w, 6)                   # planando (FLY 24)
        self.assertEqual(e.out, [])
        st['movement_event'] = 29                                   # FALL_LAND
        st['vehicles'].seated = 0x5040000160039                     # mas sentado no carro
        e.flush_zone_replay(None, None, st, w, 6)
        self.assertEqual(e.out, [])
        st['vehicles'].seated = None
        e.flush_zone_replay(None, None, st, w, 6)
        self.assertEqual([c for c, _ in e.out], [0x481, 0x481])    # sem molde do 0x27 aqui
        self.assertFalse(st['zone_replay_pending'])

    def test_pending_dropped_when_back_inside(self):
        e, w = endpoint(), two_stages()
        w.poll(6)
        w.zone_inside = True
        st = dict(actor_uid=42, zone_replay_pending=True)
        e.flush_zone_replay(None, None, st, w, 6)
        self.assertEqual((e.out, st['zone_replay_pending']), ([], False))

if __name__ == '__main__':
    unittest.main()
