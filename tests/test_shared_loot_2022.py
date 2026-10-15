"""Один остаток на комнату: гонка, частичный подбор, выброс и поздний вход."""
import struct
import time
import contextlib
import io
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
import test_weapon_probe_2022 as weapon_tests
from shared_loot_2022 import SharedLootRooms
from game_endpoint_probe_2022 import Endpoint, encode_datagram
from listener import Capture
from roe_protocol_2022 import encrypt, decrypt
from roe_tgcp_2023 import parse_datagram, parse_frame, parse_applications


class SharedLootTests(unittest.TestCase):
    def setUp(self):
        helper = weapon_tests.WeaponStateTests()
        self.a = dict(actor_uid=100, room_uid=1, weapon=helper.recycling_state())
        self.b = dict(actor_uid=104, room_uid=1, weapon=helper.recycling_state())
        self.rooms = SharedLootRooms(self.a['weapon'].fixture)
        self.request = helper.pickup_request(15510)
        self.entity = self.a['weapon'].fixture.loot.entity
        self.rooms.filter_spawn(self.a, self.entity)
        self.rooms.attach(self.a)
        self.rooms.attach(self.b)

    def test_world_clock_is_shared_in_epoch_and_reset_after_last_leave(self):
        self.assertEqual(self.rooms.world_start(self.a, 100), 100)
        self.assertEqual(self.rooms.world_start(self.b, 116), 100)
        self.rooms.detach(self.a); self.rooms.detach(self.b)
        fresh = dict(actor_uid=108, room_uid=1, weapon=self.a['weapon'])
        with self.assertRaises(ValueError): self.rooms.world_start(fresh, 200)
        self.rooms.attach(fresh)
        self.assertEqual(self.rooms.world_start(fresh, 200), 200)
        with self.assertRaises(ValueError): self.rooms.world_start(self.a, 201)

    def test_racing_pickups_only_one_inventory_receives_quantity(self):
        before = self.a['weapon'].reserve + self.b['weapon'].reserve
        _, event, outputs = self.rooms.handle(self.a, 0x3b63, self.request)
        self.assertEqual(event['quantity'], 20)
        self.assertIs(outputs[0][0], self.b)
        self.assertEqual(outputs[0][1], [(0x82b, struct.pack('>Q', 999))])
        for state in (self.b, self.a):
            replies, event, outputs = self.rooms.handle(state, 0x3b63, self.request)
            self.assertEqual(event['reason'], 'shared_loot_consumed')
            self.assertEqual(outputs, [])
            self.assertIn((0x82b, struct.pack('>Q', 999)), replies)
        self.assertEqual(self.a['weapon'].reserve + self.b['weapon'].reserve, before + 20)

    def test_partial_pickup_leaves_one_shared_remainder(self):
        self.a['weapon'].reserve = 110
        _, event, outputs = self.rooms.handle(self.a, 0x3b63, self.request)
        self.assertEqual((event['quantity'], event['remaining']), (10, 10))
        self.assertEqual([code for code, _ in outputs[0][1]], [0x82b, 0x821])
        body = self.rooms.filter_spawn(self.b, self.entity)
        self.assertEqual(struct.unpack_from('>I', body, 67)[0], 10)
        _, event, _ = self.rooms.handle(self.b, 0x3b63, self.request)
        self.assertEqual(event['quantity'], 10)
        self.assertIsNone(self.rooms.filter_spawn(self.b, self.entity))

    def test_partial_full_bag_rebind_and_replay_preserve_one_room_total(self):
        # Частичный pickup, отказ полного рюкзака и перенос транспорта
        # должны использовать один остаток, а не исходную quantity fixture.
        self.a['weapon'].reserve = 110
        self.b['weapon'].reserve = 100
        total = 110 + 100 + 20
        def remaining():
            body = self.rooms.filter_spawn(self.b, self.entity)
            return struct.unpack_from('>I', body, 67)[0] if body else 0
        def conserved():
            self.assertEqual(self.a['weapon'].reserve + self.b['weapon'].reserve + remaining(), total)
        self.assertEqual(self.rooms.handle(self.a, 0x3b63, self.request)[1]['quantity'], 10)
        conserved()
        replies, event, outputs = self.rooms.handle(self.a, 0x3b63, self.request)
        self.assertEqual((event['quantity'], event['remaining']), (0, 10))
        self.assertFalse(outputs)
        conserved()
        rebound = dict(self.a, gameplay_resumed=True)
        self.assertTrue(self.rooms.attach(rebound))
        self.assertFalse(self.rooms.detach(self.a))
        self.a = rebound
        conserved()
        self.assertEqual(self.rooms.handle(self.b, 0x3b63, self.request)[1]['quantity'], 10)
        conserved()
        for state in (self.a, self.b):
            self.assertEqual(self.rooms.handle(state, 0x3b63, self.request)[1]['reason'], 'shared_loot_consumed')
            conserved()

    def test_late_join_and_replay_do_not_resurrect_consumed_item(self):
        self.rooms.handle(self.a, 0x3b63, self.request)
        newcomer = dict(actor_uid=108, room_uid=1, weapon=weapon_tests.WeaponStateTests().recycling_state())
        self.assertIsNone(self.rooms.filter_spawn(newcomer, self.entity))
        self.rooms.attach(newcomer)
        self.assertNotIn(999, newcomer['weapon'].available_loot)
        _, event, _ = self.rooms.handle(newcomer, 0x3b63, self.request)
        self.assertEqual(event['reason'], 'shared_loot_consumed')

    def test_rejected_distance_does_not_consume_or_broadcast(self):
        invalid = bytearray(self.request)
        struct.pack_into('>i', invalid, 20, 10000)
        _, event, outputs = self.rooms.handle(self.a, 0x3b63, bytes(invalid))
        self.assertEqual(event['action'], 'rejected')
        self.assertEqual(outputs, [])
        self.assertIsNotNone(self.rooms.filter_spawn(self.b, self.entity))

    def test_room_isolation_and_duplicate_account_guard(self):
        self.rooms.handle(self.a, 0x3b63, self.request)
        other = dict(actor_uid=108, room_uid=2, weapon=weapon_tests.WeaponStateTests().recycling_state())
        self.assertIsNotNone(self.rooms.filter_spawn(other, self.entity))
        self.assertEqual(self.rooms.handle(other, 0x3b63, self.request)[1]['quantity'], 20)
        duplicate = dict(actor_uid=100, room_uid=1, weapon=weapon_tests.WeaponStateTests().recycling_state())
        self.assertFalse(self.rooms.attach(duplicate))
        duplicate['gameplay_resumed'] = True
        self.assertTrue(self.rooms.attach(duplicate))

    def test_unspawned_fixture_cannot_be_picked(self):
        rooms = SharedLootRooms(self.a['weapon'].fixture)
        _, event, outputs = rooms.handle(self.a, 0x3b63, self.request)
        self.assertEqual(event['action'], 'rejected')
        self.assertFalse(outputs)

    def test_two_players_drop_distinct_ids_and_other_player_can_pick(self):
        drop = struct.pack('>BBBBHIIB', 2, 2, 0, 1, 5, 0, 0, 1)
        indices, uids = [], []
        for state in (self.a, self.b):
            replies, event, outputs = self.rooms.handle(state, 0x3e80, drop)
            self.assertEqual(event['action'], 'discard')
            indices.append(event['index'])
            uids.append(struct.unpack_from('>Q', dict(replies)[0x821], 4)[0])
            self.assertEqual(outputs[0][1][0][0], 0x821)
        self.assertEqual(len(set(indices)), 2)
        self.assertEqual(len(set(uids)), 2)
        request = weapon_tests.WeaponStateTests().pickup_request(indices[0])
        self.assertEqual(self.rooms.handle(self.b, 0x3b63, request)[1]['quantity'], 5)

    def test_room_and_member_limits(self):
        for account in range(108, 132, 4):
            self.assertTrue(self.rooms.attach(dict(actor_uid=account, room_uid=1)))
        self.assertFalse(self.rooms.attach(dict(actor_uid=132, room_uid=1)))
        for room in range(2, 33):
            self.rooms.room(dict(room_uid=room))
        with self.assertRaises(ValueError):
            self.rooms.room(dict(room_uid=33))

    def test_late_join_snapshot_contains_unpicked_drop_and_consumed_tombstone(self):
        self.rooms.handle(self.a, 0x3b63, self.request)
        drop = struct.pack('>BBBBHIIB', 2, 2, 0, 1, 5, 0, 0, 1)
        replies, event, _ = self.rooms.handle(self.a, 0x3e80, drop)
        newcomer = dict(actor_uid=108, room_uid=1, weapon=weapon_tests.WeaponStateTests().recycling_state())
        self.assertFalse(self.rooms.snapshot(newcomer))
        self.assertTrue(self.rooms.attach(newcomer))
        self.assertEqual(self.rooms.snapshot(newcomer), [(0x82b, struct.pack('>Q', 999)),
                                                       (0x821, dict(replies)[0x821])])
        # Snapshot не меняет запас и не выдаёт уже подобранное снова.
        before = newcomer['weapon'].reserve
        self.rooms.snapshot(newcomer)
        self.assertEqual(newcomer['weapon'].reserve, before)
        self.rooms.handle(newcomer, 0x3b63, weapon_tests.WeaponStateTests().pickup_request(event['index']))
        self.assertEqual([code for code, _ in self.rooms.snapshot(self.b)], [0x82b, 0x82b])

    def test_last_member_resets_epoch_and_old_state_cannot_restore_consumed_floor(self):
        self.rooms.handle(self.a,0x3b63,self.request)
        self.assertFalse(self.rooms.detach(self.a))
        self.assertIsNone(self.rooms.filter_spawn(self.b,self.entity))
        self.assertTrue(self.rooms.detach(self.b))
        with self.assertRaises(ValueError):self.rooms.filter_spawn(self.a,self.entity)
        newcomer=dict(actor_uid=100,room_uid=1,weapon=weapon_tests.WeaponStateTests().recycling_state())
        self.assertEqual(self.rooms.filter_spawn(newcomer,self.entity),self.entity)
        self.assertEqual(newcomer['shared_loot_epoch'],2)
        self.assertEqual(self.rooms.handle(newcomer,0x3b63,self.request)[1]['quantity'],20)

    def test_rebound_transport_detach_preserves_same_room_epoch(self):
        new=dict(actor_uid=100,room_uid=1,weapon=self.a['weapon'],gameplay_resumed=True)
        self.assertTrue(self.rooms.attach(new))
        self.assertFalse(self.rooms.detach(self.a))
        self.assertIs(self.rooms.rooms[1]['members'][100],new)
        self.assertEqual(new['shared_loot_epoch'],1)

    def test_endpoint_filters_consumed_item_in_single_and_batch_frames(self):
        endpoint = Endpoint.__new__(Endpoint)
        endpoint.started = time.monotonic()
        endpoint.shared_loot = self.rooms
        frames = []
        endpoint.send_frame = lambda *args, **kwargs: frames.append((args, kwargs))
        self.rooms.handle(self.a, 0x3b63, self.request)
        self.b['frame_seq'] = 3
        endpoint.send_application(None, None, self.b, 0x821, self.entity)
        endpoint.send_application_batch(None, None, self.b, [(0x821, self.entity)])
        self.assertFalse(frames)
        endpoint.send_application_batch(None, None, self.b, [(0x821, self.entity), (0x82b, bytes(8))])
        self.assertEqual(frames[0][1]['applications'], (0x82b,))

    def test_endpoint_broadcast_skips_stale_finished_and_retired_transports(self):
        endpoint = Endpoint.__new__(Endpoint)
        endpoint.capture = SimpleNamespace(record=lambda *args, **kwargs: None)
        sent = []
        endpoint.send_application_batch = lambda *args: sent.append(args)
        self.b.update(auth_sent=True, room_sent=True,
                      peer_avatar_anchor=(None, ('127.0.0.1', 2), time.monotonic()))
        outputs = [(self.b, [(0x82b, bytes(8))])]
        endpoint.emit_shared_loot(outputs)
        self.assertEqual(len(sent), 1)

        for flag in ('match_finished', 'transport_retired'):
            self.b[flag] = True
            endpoint.emit_shared_loot(outputs)
            self.b[flag] = False
        self.b['peer_avatar_anchor'] = (None, ('127.0.0.1', 2), time.monotonic()-6)
        endpoint.emit_shared_loot(outputs)
        self.assertEqual(len(sent), 1)

    def test_two_encoded_udp_sessions_apply_only_one_pickup_and_broadcast_removal(self):
        with tempfile.TemporaryDirectory() as directory:
            capture = Capture(Path(directory)/'capture')
            try:
                endpoint = Endpoint(capture, True, auth=True,
                                    weapon_fixture=self.a['weapon'].fixture, shared_ground_loot=True)
                sent, states = [], []
                endpoint.transport = SimpleNamespace(sendto=lambda raw, remote: sent.append((raw, remote)))
                with contextlib.redirect_stdout(io.StringIO()):
                    for account, port in ((100, 23456), (104, 23457)):
                        remote = ('127.0.0.1', port)
                        endpoint.datagram_received(encode_datagram(5000,18001,100,0,0x22,1,0), remote)
                        state = endpoint.sessions[(remote,5000,18001)]
                        state.update(key_sent=True, auth_sent=True, room_sent=True,
                                     actor_uid=account, room_uid=1, weapon=weapon_tests.WeaponStateTests().recycling_state())
                        state['peer_avatar_anchor'] = (SimpleNamespace(source_port=5000, destination_port=18001, clock=1), remote, time.monotonic())
                        endpoint.shared_loot.filter_spawn(state, self.entity)
                        endpoint.shared_loot.attach(state)
                        states.append((state, remote))
                    sent.clear()
                    before = sum(state['weapon'].reserve for state, _ in states)
                    for state, remote in states:
                        plain = (struct.pack('>IIHI',1,30+len(self.request),0x3b63,0)
                                 + struct.pack('>IIQ',123,0,state['actor_uid'])
                                 + struct.pack('>I',0x3b63) + self.request)
                        body = encrypt(plain, state['key'])
                        frame = struct.pack('>HHHHBIII',0x3366,10,10,0x4013,0,3,25,len(body))+bytes(4)+body
                        endpoint.datagram_received(encode_datagram(5000,18001,state['next_client'],0,0x18,1,0,frame),remote)
                self.assertEqual(sum(state['weapon'].reserve for state, _ in states), before+20)
                for state, remote in states:
                    messages = []
                    for raw, recipient in sent:
                        datagram = parse_datagram(raw)
                        if recipient == remote and datagram.data:
                            frame = parse_frame(datagram.data)
                            messages.extend(parse_applications(frame, decrypt(frame.body,state['key']), 'server'))
                    self.assertTrue(any(m.command==0x82b and m.payload==struct.pack('>Q',999) for m in messages))
            finally:
                capture.events.close()
