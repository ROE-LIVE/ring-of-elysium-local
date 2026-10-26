"""Комната: двери и окна общие — изменение одного игрока видно другому через snapshot."""
from pathlib import Path
import struct
import sys
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server/directory'))
from door_state_2022 import DoorState
from breakable_state_2022 import BreakableState


def damage(identifier, values, actor, part=0):
    context = struct.pack('<QI', actor, part) + struct.pack('<13f', *([0.0] * 13)) + bytes(72 - 12 - 52)
    return struct.pack('>II', identifier, len(values)) + struct.pack('>%dI' % len(values), *values) + bytes((72,)) + context


class SharedWorldObjectTests(unittest.TestCase):
    def test_door_opened_by_one_player_reaches_the_other(self):
        fixture = SimpleNamespace(doors={7: ((0, 0, 0), 0)}, interaction_radius_cm=500,
                                  visibility_radius_cm=6000, accept_unknown=False)
        shared = {}
        a, b = DoorState(fixture, shared), DoorState(fixture, shared)
        self.assertEqual(len(b.snapshot((10, 0, 0))), 1)  # estado inicial da porta próxima
        a.handle(struct.pack('>II', 7, 1), (10, 0, 0))
        self.assertEqual([code for code, _ in b.snapshot((10, 0, 0))], [0x6f55])
        self.assertEqual(b.snapshot((10, 0, 0)), [])
        self.assertEqual(DoorState(fixture).status, {7: 0})

    def test_window_damage_is_shared_and_resent_when_it_changes(self):
        fixture = SimpleNamespace(entities={9: ((0, 0, 0), (100, 100))}, interaction_radius_cm=500, accept_unknown=False)
        shared = {}
        a, b = BreakableState(fixture, 1, shared), BreakableState(fixture, 2, shared)
        a.handle(damage(9, (60, 0), 1), (10, 0, 0))
        self.assertEqual(b.remaining[9], [40, 100])
        self.assertEqual(len(b.snapshot((10, 0, 0))), 1)
        self.assertEqual(b.snapshot((10, 0, 0)), [])
        a.handle(damage(9, (40, 0), 1), (10, 0, 0))
        self.assertEqual(len(b.snapshot((10, 0, 0))), 1)
        _, event = b.handle(damage(9, (10, 0), 1), (10, 0, 0))
        self.assertEqual(event['reason'], 'foreign_actor')


if __name__ == '__main__':
    unittest.main()
