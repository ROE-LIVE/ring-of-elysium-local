"""Expulsão e banimento pelo painel: comando kick, resultado de «não resgatado» e lista de contas."""
import json
import struct
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'server/directory'))
from game_endpoint_probe_2022 import BanList, Endpoint
from match_statistics_2022 import MatchStatistics
from state_scene_actions_2022 import validate_state_action


class FakeFixture:
    def messages(self, actor, room, report, name):
        self.report = dict(report)
        return [(0x6584, b'result')]


def endpoint():
    e = Endpoint.__new__(Endpoint)
    e.records, e.sent = [], []
    e.capture = SimpleNamespace(record=lambda kind, **kw: e.records.append((kind, kw)))
    e.send_application_batch = lambda d, remote, state, packets: e.sent.extend(packets)
    e.evacuation_result_fixture = FakeFixture()
    e.peer_avatars = e.shared_loot = None
    e.room_display_name = 'Jogador'
    return e


class AdminKickTests(unittest.TestCase):
    def test_kick_validation_has_no_payload(self):
        self.assertEqual(validate_state_action(dict(id='k', action='kick', recipient_actor_uid='0x5')), dict(action='kick'))
        with self.assertRaises(ValueError):
            validate_state_action(dict(id='k', action='kick', hp=5))

    def test_kick_sends_not_rescued_result_and_finishes_once(self):
        e = endpoint()
        state = dict(actor_uid=5, room_uid=1, world=object(), match_statistics=MatchStatistics())
        state['match_statistics'].started_at = time.monotonic()
        e.kick_player(state, None, ('127.0.0.1', 1), 'kicked')
        self.assertEqual(e.sent, [(0x6584, b'result'), (0x6589, struct.pack('>BQ', 0, 0))])
        self.assertEqual(e.evacuation_result_fixture.report['rescued'], 0)
        self.assertTrue(state['match_finished'])
        self.assertNotIn('world', state)
        self.assertIn(('player_kicked', dict(account_uid='0x5', cause='kicked', result_messages=2, synthetic=True)),
                      e.records)
        e.kick_player(state, None, ('127.0.0.1', 1), 'kicked')
        self.assertEqual(len(e.sent), 2)

    def test_ban_list_reloads_and_ignores_bad_file(self):
        with tempfile.TemporaryDirectory() as t:
            path = Path(t)/'banidos.json'
            bans = BanList(path)
            self.assertFalse(bans.banned(5))
            path.write_text(json.dumps({'contas': ['0x5']}), encoding='utf-8')
            self.assertTrue(bans.banned(5))
            self.assertFalse(bans.banned(6))
            time.sleep(0.01)
            path.write_text('não é json', encoding='utf-8')
            import os
            os.utime(path, ns=(time.time_ns(), time.time_ns() + 10**9))
            self.assertFalse(bans.banned(5))


if __name__ == '__main__':
    unittest.main()
