"""Estado da zona confirmado ao cliente: 0x27 + 0x481 só no chão, quando o estado do ponto muda."""
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


def world():
    # Fase 20: seguras 1..3, só a 3 continua segura na próxima (1 e 2 em alerta); a 4 fechou.
    fixture = WorldFixture(1000, 100, (10, 20, 30, 40), 50, 1,
                           ((0, 20, encode_shrink(300, 20, [3], [1, 2, 3])),),
                           region_grid=GRID, stage_safe=(frozenset({1, 2, 3}),),
                           stage_future=(frozenset({3}),), hazard_enabled=False)
    state = WorldState(fixture, 42, 0)
    state.poll(0)
    return state


class ZoneViewTests(unittest.TestCase):
    def test_closed_alert_and_safe(self):
        w = world()
        self.assertEqual([w.zone_view((r, 0, 0)) for r in (4, 1, 2, 3)], ['closed', 'alert', 'alert', 'safe'])
        self.assertIsNone(w.zone_view(None))

    def test_without_future_lists_alert_is_not_guessed(self):
        from dataclasses import replace
        w = world()
        w.fixture = replace(w.fixture, stage_future=())
        self.assertEqual([w.zone_view((r, 0, 0)) for r in (4, 1, 3)], ['closed', 'safe', 'safe'])

    def test_before_first_stage_nothing_to_sync(self):
        fixture = WorldFixture(1000, 100, (10, 20, 30, 40), 50, 1,
                               ((5, 20, encode_shrink(300, 20, [3], [1, 2, 3])),), region_grid=GRID,
                               stage_safe=(frozenset({1, 2, 3}),), stage_future=(frozenset({3}),))
        w = WorldState(fixture, 42, 0)
        w.poll(0)
        self.assertIsNone(w.zone_view((4, 0, 0)))


class ZoneViewSyncTests(unittest.TestCase):
    def endpoint(self):
        e = Endpoint.__new__(Endpoint)
        e.started = 0
        e.records, e.out = [], []
        e.capture = SimpleNamespace(record=lambda kind, **kw: e.records.append((kind, kw)))
        e.send_application = lambda d, remote, st, command, payload: e.out.append((command, payload))
        e.register_fixture_entity = lambda st, command, payload: st.update(
            scene_position=struct.unpack_from('>3i', payload, 8), scene_position_sync=payload)
        return e

    def state(self, anchor, current, event):
        return dict(actor_uid=42, scene_position=anchor, last_movement_position=current,
                    scene_position_sync=bytes(40), movement_event=event)

    def test_glider_leaving_closed_zone_waits_for_landing(self):
        # Sessão 20261029T021955: o 0x27 na saída, em INAIR_FLY, fechou a asa-delta.
        e, w = self.endpoint(), world()
        s = self.state((4, 0, 0), (3, 0, 0), 24)
        for event in (24, 70, 55, 4, 22, 6, 41, 49):
            s['movement_event'] = event
            e.sync_zone_view(None, None, s, w, 10)
            self.assertEqual(e.out, [], event)
        s['movement_event'] = 1
        s['vehicles'] = SimpleNamespace(seated=7)
        e.sync_zone_view(None, None, s, w, 10)
        self.assertEqual(e.out, [])
        s['vehicles'].seated = None
        s['movement_event'] = 29                                  # FALL_LAND
        e.sync_zone_view(None, None, s, w, 10)
        self.assertEqual([c for c, _ in e.out], [0x27, 0x481])
        self.assertEqual(struct.unpack_from('>Q3i', e.out[0][1]), (42, 3, 0, 0))
        self.assertEqual(s['scene_position'], (3, 0, 0))          # a âncora passa a ser o ponto confirmado
        self.assertEqual(e.records[-1][1]['view'], 'safe')
        e.out.clear()
        e.sync_zone_view(None, None, s, w, 11)
        self.assertEqual(e.out, [])

    def test_alert_edge_then_safe_region_resyncs(self):
        # Saída para uma região que fecha na próxima fase (60) e depois para uma segura (32):
        # o contador da 60 seguia na 32.
        e, w = self.endpoint(), world()
        s = self.state((4, 0, 0), (1, 0, 0), 1)
        e.sync_zone_view(None, None, s, w, 10)
        self.assertEqual(e.records[-1][1]['view'], 'alert')
        s['last_movement_position'] = (2, 0, 0)                   # outra em alerta: nada muda
        e.out.clear()
        e.sync_zone_view(None, None, s, w, 20)
        self.assertEqual(e.out, [])
        s['last_movement_position'] = (3, 0, 0)
        e.sync_zone_view(None, None, s, w, 10.5)                  # intervalo mínimo de 1 s
        self.assertEqual(e.out, [])
        e.sync_zone_view(None, None, s, w, 21)
        self.assertEqual([c for c, _ in e.out], [0x27, 0x481])
        self.assertEqual(e.records[-1][1]['view'], 'safe')

    def test_no_template_or_no_movement_sends_nothing(self):
        e, w = self.endpoint(), world()
        for s in (self.state((4, 0, 0), None, 1), self.state(None, (3, 0, 0), 1),
                  dict(self.state((4, 0, 0), (3, 0, 0), 1), scene_position_sync=None)):
            e.sync_zone_view(None, None, s, w, 10)
        self.assertEqual(e.out, [])


if __name__ == '__main__':
    unittest.main()
