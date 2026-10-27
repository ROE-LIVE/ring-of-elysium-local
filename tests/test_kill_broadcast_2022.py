"""Лента убийств0x0480: формат декодера клиента и рассылка комнате."""
import sys
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'server/directory'))
import struct
from kill_broadcast_2022 import encode_kill_broadcast, decode_kill_broadcast
from game_endpoint_probe_2022 import Endpoint


class KillBroadcastTests(unittest.TestCase):
    def test_round_trip_and_client_string_rules(self):
        body = encode_kill_broadcast(0x2040000100001, 'Charlie', 1, 0x515bb1e1dd242c, 'Jogador1', 10111, True)
        decoded = decode_kill_broadcast(body)
        self.assertEqual((decoded['actor_name'], decoded['killer_name'], decoded['weapon_id']),
                         ('Charlie', 'Jogador1', 10111))
        self.assertEqual((decoded['alive'], decoded['hit_head'], decoded['downer_name']), (1, True, ''))
        # Пустая строка — длина1 (один NUL): декодер клиента отвергает длину0.
        self.assertEqual(body[8:12], (9).to_bytes(4, 'big'))
        empty = decode_kill_broadcast(encode_kill_broadcast(5, 'X', 3))
        self.assertEqual((empty['killer_rid'], empty['killer_name']), (0, ''))
        self.assertEqual(len(encode_kill_broadcast(5, 'X', 3)), 8+5+8+5+4+8+6+12+5+16)

    def endpoint_room(self):
        endpoint = Endpoint.__new__(Endpoint)
        endpoint.room_display_name = 'LOCAL'
        endpoint.records, endpoint.sent = [], []
        endpoint.capture = SimpleNamespace(record=lambda kind, **kw: endpoint.records.append((kind, kw)))
        endpoint.emit_peer_avatars = lambda outputs, events: endpoint.sent.extend(outputs)
        states = [dict(actor_uid=uid, room_uid=1, actor_display_name=name,
                       world=SimpleNamespace(dead=False)) for uid, name in ((10, 'A'), (20, 'B'), (30, 'C'))]
        endpoint.peer_avatars = SimpleNamespace(members={
            (1, s['actor_uid']): dict(state=s, avatar=500+s['actor_uid']) for s in states})
        return endpoint, states

    def test_pvp_kill_uses_recipient_view_and_is_sent_once(self):
        endpoint, (a, b, c) = self.endpoint_room()
        b['world'].dead = True
        b['last_peer_hit'] = (a, 10111, True, time.monotonic())
        endpoint.broadcast_kill(b)
        endpoint.broadcast_kill(b)
        self.assertEqual(len(endpoint.sent), 3)
        views = {state['actor_uid']: decode_kill_broadcast(packets[0][1]) for state, packets in endpoint.sent}
        self.assertEqual((views[10]['killer_rid'], views[10]['actor_rid']), (10, 520))
        self.assertEqual((views[20]['killer_rid'], views[20]['actor_rid']), (510, 20))
        self.assertEqual((views[30]['killer_rid'], views[30]['actor_rid']), (510, 520))
        self.assertTrue(all(v['alive'] == 2 and v['killer_name'] == 'A' and v['hit_head'] and v['reason'] == 1
                            for v in views.values()))

    def test_kill_sends_alive_count_to_all_and_kill_counters_to_killer_and_victim(self):
        endpoint, (a, b, c) = self.endpoint_room()
        b['world'].dead = True
        b['last_peer_hit'] = (a, 10111, False, time.monotonic())
        endpoint.broadcast_kill(b)
        sent = {state['actor_uid']: dict((code, body) for code, body in packets) for state, packets in endpoint.sent}
        self.assertEqual(struct.unpack('>II', sent[10][0x47d]), (2, 1))
        self.assertEqual(struct.unpack('>II', sent[20][0x47d]), (2, 0))
        self.assertEqual(struct.unpack('>IQII', sent[10][0x47e]), (1, 10, 0, 0))
        self.assertEqual(struct.unpack('>IQII', sent[20][0x47e]), (0, 20, 1, 0))
        self.assertNotIn(0x47e, sent[30])

    def test_death_without_recent_shooter_has_no_killer(self):
        endpoint, (a, b, c) = self.endpoint_room()
        c['world'].dead = True
        c['last_peer_hit'] = (a, 10111, False, time.monotonic()-11)
        endpoint.broadcast_kill(c)
        view = decode_kill_broadcast(endpoint.sent[0][1][0][1])
        self.assertEqual((view['killer_rid'], view['killer_name'], view['actor_name'], view['alive'], view['reason']),
                         (0, '', 'C', 2, 3))


class MatchRoomTests(unittest.TestCase):
    def test_entry_during_running_match_gets_separate_room(self):
        endpoint = Endpoint.__new__(Endpoint)
        endpoint.records = []
        endpoint.capture = SimpleNamespace(record=lambda kind, **kw: endpoint.records.append((kind, kw)))
        selecting = dict(actor_uid=20, room_uid=1)
        endpoint.peer_avatars = SimpleNamespace(members={(1, 20): dict(state=selecting, avatar=520)})
        # Мира ещё нет (выбор точки): вход общий.
        self.assertEqual(endpoint.match_room(10, 1), 1)
        selecting['world'] = SimpleNamespace(dead=False)
        # Повторный вход того же аккаунта не считается «другим участником».
        self.assertEqual(endpoint.match_room(20, 1), 1)
        first, second = endpoint.match_room(10, 1), endpoint.match_room(10, 1)
        self.assertNotIn(first, (1, second))
        self.assertEqual(endpoint.records[0][0], 'match_room_separated')
        selecting['match_finished'] = True
        self.assertEqual(endpoint.match_room(10, 1), 1)


class BornPointTests(unittest.TestCase):
    def test_unselected_players_get_distinct_random_cells(self):
        endpoint = Endpoint.__new__(Endpoint)
        endpoint.records = []
        endpoint.capture = SimpleNamespace(record=lambda kind, **kw: endpoint.records.append((kind, kw)))
        endpoint.spawn_points = ((1, 1, 100, 100, 10), (2, 2, 200, 200, 20))
        endpoint.shared_loot = SimpleNamespace(epochs={})
        endpoint.room_born_cells = {}
        a, b = dict(actor_uid=10, room_uid=1), dict(actor_uid=20, room_uid=1)
        first = endpoint.ensure_born_point(a)
        second = endpoint.ensure_born_point(b)
        self.assertNotEqual(first[:2], second[:2])
        self.assertIs(endpoint.ensure_born_point(a), first)
        self.assertEqual(endpoint.records[0][1]['action'], 'born_position_random')
        chosen = dict(actor_uid=30, room_uid=1, born_point=(9, 9, 1, 2, 3))
        self.assertEqual(endpoint.ensure_born_point(chosen), (9, 9, 1, 2, 3))


if __name__ == '__main__':
    unittest.main()
