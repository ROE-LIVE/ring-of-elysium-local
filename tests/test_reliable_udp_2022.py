"""Потери ответа, cumulative ACK, wrap и ограничение памяти sender."""
import asyncio
import contextlib
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'server/directory'))
from reliable_udp_2022 import ReliableSender, ReliableReceiver, FrameStream
from game_endpoint_probe_2022 import encode_datagram
from roe_tgcp_2023 import parse_datagram
from roe_protocol_2022 import encrypt
import test_game_endpoint_probe_2022 as gameplay_tests
import struct


class SenderTests(unittest.TestCase):
    def test_wrap_partial_ack_and_future_ack(self):
        sender = ReliableSender(0xfffffffc)
        sender.remember(b'first', 0xfffffffc, 8, 0)
        sender.remember(b'second', 4, 4, 0)
        self.assertFalse(sender.acknowledge(9))
        self.assertFalse(sender.acknowledge(0xfffffffb))
        self.assertTrue(sender.acknowledge(0))
        self.assertEqual(len(sender.pending), 2)
        self.assertTrue(sender.acknowledge(4))
        self.assertEqual(list(sender.pending), [4])
        self.assertFalse(sender.acknowledge(0))
        self.assertTrue(sender.acknowledge(8))
        self.assertEqual((len(sender.pending), sender.bytes), (0, 0))

    def test_retry_backoff_and_stop_on_limit(self):
        sender = ReliableSender(1, attempts=2)
        sender.remember(b'unchanged', 1, 9, 0)
        self.assertEqual(sender.due(.249), [])
        self.assertEqual(sender.due(.25), [(1, b'unchanged', 1)])
        self.assertEqual(sender.due(.749), [])
        self.assertEqual(sender.due(.75), [(1, b'unchanged', 2)])
        self.assertEqual(sender.due(1.75), [])
        self.assertTrue(sender.failed)

    def test_default_retry_budget_keeps_twenty_second_loss_recoverable(self):
        sender = ReliableSender(1)
        sender.remember(b'data',1,4,0)
        for step in range(1,81):
            sender.due(step*.25)
        self.assertFalse(sender.failed)
        self.assertTrue(sender.acknowledge(5))
        self.assertEqual(sender.pending,{})

    def test_memory_bound_and_invalid_send_order(self):
        sender = ReliableSender(1, maximum_bytes=5)
        with self.assertRaises(ValueError):
            sender.remember(b'a', 2, 1, 0)
        self.assertTrue(sender.remember(b'12345', 1, 5, 0))
        self.assertFalse(sender.remember(b'6', 6, 1, 0))
        self.assertTrue(sender.failed)
        self.assertEqual(sender.bytes, 5)


class LostGameplayResponseTests(unittest.IsolatedAsyncioTestCase):
    reliable_udp = True
    setUp = gameplay_tests.GameplayActionReplayTests.setUp
    request = gameplay_tests.GameplayActionReplayTests.request

    async def test_lost_reload_response_retries_bytes_without_second_effect(self):
        self.addCleanup(self.endpoint.stop_retries)
        self.state['sender'].acknowledge(0x10000001)
        self.weapon.clip = 1
        packets, request = self.request(100, 0x49c, struct.pack('>I', 1))
        responses = [raw for raw in packets if parse_datagram(raw).data]
        self.assertTrue(responses)
        self.assertEqual((self.weapon.clip, self.weapon.reserve), (2, 5))
        # Клиент не получил ответы: ACK не поступил. Никаких gameplay вызовов.
        before = len(self.sent)
        with patch('game_endpoint_probe_2022.time.monotonic', return_value=self.endpoint.started + 10), contextlib.redirect_stdout(io.StringIO()):
            self.endpoint.retry_pending()
        self.assertEqual(self.sent[before:], responses)
        self.assertEqual((self.weapon.clip, self.weapon.reserve), (2, 5))
        with contextlib.redirect_stdout(io.StringIO()):
            self.endpoint.datagram_received(request, self.remote)
        self.assertEqual((self.weapon.clip, self.weapon.reserve), (2, 5))
        sender = self.state['sender']
        ack = encode_datagram(5000, 18001, self.state['next_client'], sender.high, 0x10, 1, 0)
        with contextlib.redirect_stdout(io.StringIO()):
            self.endpoint.datagram_received(ack, self.remote)
        self.assertEqual((len(sender.pending), sender.bytes), (0, 0))
        before = len(self.sent)
        with patch('game_endpoint_probe_2022.time.monotonic', return_value=self.endpoint.started + 20):
            self.endpoint.retry_pending()
        self.assertEqual(len(self.sent), before)

    async def test_duplicate_syn_preserves_session_and_replies_identically(self):
        first = self.sent[0]
        frame_counter = self.state['frame_seq']
        with contextlib.redirect_stdout(io.StringIO()):
            self.endpoint.datagram_received(encode_datagram(5000,18001,100,0,0x22,9,0), self.remote)
        self.assertIs(self.endpoint.sessions[(self.remote,5000,18001)], self.state)
        self.assertIs(self.state['weapon'], self.weapon)
        self.assertEqual(self.state['frame_seq'], frame_counter)
        self.assertEqual(self.sent[-1], first)

    async def test_ack_without_ack_flag_does_not_release_response(self):
        sender = self.state['sender']
        with contextlib.redirect_stdout(io.StringIO()):
            self.endpoint.datagram_received(encode_datagram(5000,18001,101,sender.high,0,1,0),self.remote)
        self.assertEqual(len(sender.pending), 1)


class ReceiverTests(unittest.TestCase):
    def test_reverse_segments_wait_for_gap_and_consume_once(self):
        receiver = ReliableReceiver(100)
        self.assertEqual(receiver.accept(103, b'def'), b'')
        self.assertEqual(receiver.next, 100)
        self.assertEqual(receiver.accept(103, b'def'), b'')
        self.assertEqual(receiver.accept(100, b'abc'), b'abcdef')
        self.assertEqual(receiver.next, 106)
        self.assertEqual(receiver.accept(100, b'abcdef'), b'')
        self.assertEqual(receiver.pending, [])

    def test_consistent_overlap_and_partial_old_segment_wrap(self):
        receiver = ReliableReceiver(0xfffffffc)
        self.assertEqual(receiver.accept(0, b'efgh'), b'')
        self.assertEqual(receiver.accept(0xfffffffc, b'abcdef'), b'abcdefgh')
        self.assertEqual(receiver.next, 4)
        self.assertEqual(receiver.accept(2, b'ghij'), b'ij')
        self.assertEqual(receiver.next, 6)

    def test_conflicting_overlap_is_atomic(self):
        receiver = ReliableReceiver(100)
        receiver.accept(103, b'def')
        before = receiver.pending[:]
        with self.assertRaises(ValueError):
            receiver.accept(102, b'cX')
        self.assertEqual(receiver.pending, before)
        self.assertEqual(receiver.next, 100)
        self.assertEqual(receiver.accept(100, b'abc'), b'abcdef')

    def test_window_and_segment_limit_do_not_advance_ack(self):
        receiver = ReliableReceiver(100, window=8, maximum_segments=2)
        receiver.accept(102, b'c')
        receiver.accept(104, b'e')
        with self.assertRaises(ValueError):
            receiver.accept(106, b'g')
        with self.assertRaises(ValueError):
            receiver.accept(108, b'i')
        self.assertEqual(receiver.next, 100)
        self.assertEqual(receiver.accept(100, b'abcdefgh'), b'abcdefgh')
        self.assertEqual(receiver.next, 108)

    def test_every_split_and_coalesced_tgcp_frames(self):
        first = struct.pack('>HHHHBIII',0x3366,10,10,0x4013,0,3,25,16)+bytes(4)+bytes(16)
        second = struct.pack('>HHHHBIII',0x3366,10,10,0x5001,0,4,21,0)
        for cut in range(1, len(first)):
            stream = FrameStream()
            self.assertEqual(stream.feed(first[:cut]), [])
            self.assertEqual(stream.feed(first[cut:]+second), [first, second])
            self.assertEqual(stream.buffer, b'')

    def test_invalid_declared_lengths_stop_stream_with_bounded_memory(self):
        for header, body, magic in [(20,1,0x3366),(4097,0,0x3366),(21,0xffffffff,0x3366),(21,0,0)]:
            stream = FrameStream()
            packet = struct.pack('>HHHHBIII',magic,10,10,0x4013,0,3,header,body)
            with self.assertRaises(ValueError):
                stream.feed(packet)
            self.assertTrue(stream.failed)
            self.assertEqual(stream.buffer, b'')
            with self.assertRaises(ValueError):
                stream.feed(b'')


class GameplayStreamTests(unittest.TestCase):
    reliable_udp = True
    setUp = gameplay_tests.GameplayActionReplayTests.setUp

    def frame(self, sequence, command, payload):
        plain=(struct.pack('>IIHI',sequence,30+len(payload),command,0)
               +struct.pack('>IIQ',123,0,42)+struct.pack('>I',command)+payload)
        body=encrypt(plain,self.state['key'])
        return struct.pack('>HHHHBIII',0x3366,10,10,0x4013,0,3,25,len(body))+bytes(4)+body

    def deliver(self, sequence, data, flags=0x18):
        raw = encode_datagram(5000,18001,sequence,0,flags,1,0,data)
        with contextlib.redirect_stdout(io.StringIO()):
            self.endpoint.datagram_received(raw,self.remote)

    def test_split_reload_reverse_and_duplicate_is_one_effect(self):
        self.weapon.clip = 1
        start = self.state['next_client']
        frame = self.frame(100,0x49c,struct.pack('>I',1))
        self.deliver(start+17, frame[17:])
        self.assertEqual(self.state['next_client'],start)
        self.assertEqual(parse_datagram(self.sent[-1]).acknowledgement,start)
        self.assertEqual((self.weapon.clip,self.weapon.reserve),(1,6))
        self.deliver(start,frame[:17],0x10)
        self.assertEqual((self.weapon.clip,self.weapon.reserve),(2,5))
        self.assertEqual(self.state['next_client'],start+len(frame))
        before=len(self.sent)
        self.deliver(start,frame[:17],0x10)
        self.deliver(start+17,frame[17:])
        self.assertEqual((self.weapon.clip,self.weapon.reserve),(2,5))
        self.assertTrue(all(not parse_datagram(raw).data for raw in self.sent[before:]))

    def test_two_frames_in_one_datagram_keep_gameplay_order(self):
        self.weapon.clip=1
        first=self.frame(100,0x49c,struct.pack('>I',1))
        fire=struct.pack('>6fIBIIfII',0,0,0,0,0,0,1,0,1,0,0,0,0)
        second=self.frame(101,0x11da,fire)
        self.deliver(self.state['next_client'],first+second)
        self.assertEqual((self.weapon.clip,self.weapon.reserve),(1,5))
        self.assertEqual(self.state['inventory_action_sequence'],101)

    def test_empty_move_does_not_invent_or_clear_last_position(self):
        self.deliver(self.state['next_client'],self.frame(1,0x2a,bytes(27)))
        self.assertNotIn('last_movement_position',self.state)
        move=struct.pack('>IiiiBBBI',1,100,200,300,0,0,0,0)+bytes(23)+bytes(9)
        self.deliver(self.state['next_client'],self.frame(2,0x2a,move))
        self.assertEqual(self.state['last_movement_position'],(100,200,300))
        self.deliver(self.state['next_client'],self.frame(3,0x2a,bytes(27)))
        self.assertEqual(self.state['last_movement_position'],(100,200,300))

    def test_authenticated_idle_relay_moves_world_once_and_retires_old_transport(self):
        self.endpoint.idle_handoff = True
        self.endpoint.scene_rules = [(0xdcd, [(0x7083,b'fixture')])]
        self.state['identity'] = b'local\0'
        old_key=(('127.0.0.1',23455),4999,18001)
        old=dict(self.state)
        old['last_application_at']=100
        old['sender']=ReliableSender(1000)
        old['sender'].remember(b'unacked',1000,7,100)
        self.endpoint.sessions[old_key]=old
        self.state['room_sent']=False
        self.state.pop('weapon')
        with patch('game_endpoint_probe_2022.time.monotonic',return_value=120):
            self.deliver(self.state['next_client'],self.frame(4,0x7082,b'\0'))
        self.assertIs(self.state['weapon'],self.weapon)
        self.assertTrue(self.state['gameplay_resumed'])
        self.assertTrue(old['transport_retired'])
        self.assertEqual((old['sender'].bytes,len(old['sender'].pending)),(0,0))
        self.weapon.clip=1
        with patch('game_endpoint_probe_2022.time.monotonic',return_value=121):
            self.deliver(self.state['next_client'],self.frame(5,0x49c,struct.pack('>I',1)))
        self.assertEqual((self.weapon.clip,self.weapon.reserve),(2,5))


class IdleHandoffTests(unittest.TestCase):
    def fixture(self):
        endpoint,*rest=gameplay_tests.GameplayHandoffTests().fixture()
        endpoint.reliable_udp=endpoint.idle_handoff=True
        old=rest[2]
        old.pop('handoff_at')
        old['last_application_at']=100
        return (endpoint,*rest)

    def test_idle_actor_guard_disabled_recent_expired_and_ambiguous(self):
        for age in (4.99,30.01):
            endpoint,_,key,old,new,*_=self.fixture()
            self.assertFalse(endpoint.resume_gameplay(key,new,100+age,123))
        for actor in (None,0,124):
            endpoint,_,key,old,new,*_=self.fixture()
            self.assertFalse(endpoint.resume_gameplay(key,new,120,actor))
        for field in ('idle_handoff','reliable_udp'):
            endpoint,_,key,old,new,*_=self.fixture()
            setattr(endpoint,field,False)
            self.assertFalse(endpoint.resume_gameplay(key,new,120,123))
        endpoint,_,key,old,new,*_=self.fixture()
        endpoint.sessions[(('127.0.0.1',3333),5002,18001)]=dict(old)
        self.assertFalse(endpoint.resume_gameplay(key,new,120,123))

    def test_idle_handoff_preserves_fields_and_requires_auth_identity_actor(self):
        for mutate in ('unauthenticated','other_identity','no_timestamp','evacuated'):
            endpoint,_,key,old,new,*_=self.fixture()
            if mutate=='unauthenticated':new['auth_sent']=False
            elif mutate=='other_identity':new['identity']=b'other\0'
            elif mutate=='no_timestamp':old.pop('last_application_at')
            else:old['vehicles']=type('Vehicle',(),{'evacuation_finished':True})()
            self.assertFalse(endpoint.resume_gameplay(key,new,120,123))
        endpoint,_,key,old,new,weapon,world,events=self.fixture()
        old['inventory_action_sequence']=999
        self.assertTrue(endpoint.resume_gameplay(key,new,120,123))
        self.assertIs(new['weapon'],weapon)
        self.assertIs(new['world'],world)
        self.assertNotIn('inventory_action_sequence',new)
        self.assertEqual(events[0][1]['handoff_mode'],'authenticated_idle_relay')
        self.assertEqual(events[0][1]['previous_idle_seconds'],20)
        self.assertFalse(endpoint.resume_gameplay(key,new,121,123))

    def test_no_world_uses_last_accepted_movement_before_spawn(self):
        endpoint,_,key,old,new,*_=self.fixture()
        old.pop('world')
        old['scene_position']=(10,20,30)
        old['last_movement_position']=(100,200,300)
        self.assertTrue(endpoint.resume_gameplay(key,new,120,123))
        self.assertEqual(new['resume_position_snapshot'],(100,200,300))


if __name__ == '__main__':
    unittest.main()
