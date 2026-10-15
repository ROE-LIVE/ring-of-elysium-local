"""Сессии и повторы запросов диагностического Jeep2022."""
import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server/directory'))
from vehicle_probe_2022 import VehicleState, survivor_event, EvacuationUIFixture


class VehicleTests(unittest.TestCase):
    def test_passenger_switch_blocks_driving_preserves_hp_and_allows_exit(self):
        state = self.fixture()
        state.handle(0x6541, struct.pack('>QI', 456, 1))
        responses, event = state.handle(0x6547, struct.pack('>I', 2))
        self.assertEqual(struct.unpack('>QQIII', responses[0][1]), (456, 123, 1, 2, 0))
        self.assertEqual(event['action'], 'seat_switch')
        before = dict(state.vehicles[456])
        move = bytearray(73)
        struct.pack_into('>Q', move, 0, 456)
        struct.pack_into('>3i', move, 13, 1000, 2000, 3000)
        self.assertEqual(state.handle(0x6549, move)[1]['reason'], 'passenger_cannot_drive')
        self.assertEqual(state.vehicles[456], before)
        self.assertEqual(state.handle(0x6547, struct.pack('>I', 2))[1]['action'], 'seat_switch_duplicate')
        self.assertEqual(state.handle(0x6547, struct.pack('>I', 3))[1]['action'], 'seat_switch_rejected')
        self.assertEqual(state.seat, 2)
        self.assertEqual(state.handle(0x6547, struct.pack('>I', 1))[1]['action'], 'seat_switch')
        self.assertEqual(state.handle(0x6549, move)[1]['action'], 'vehicle_move')
        state.handle(0x6547, struct.pack('>I', 2))
        state.register(0x6554, struct.pack('>QII', 456, 0, 3))
        self.assertEqual(state.handle(0x6547, struct.pack('>I', 1))[1]['action'], 'seat_switch_rejected')
        self.assertEqual(state.handle(0x6543, struct.pack('>BiiiB', 0, 1000, 2000, 3000, 0))[1]['action'], 'getoff')
        self.assertEqual(state.handle(0x6541, struct.pack('>QI', 456, 2))[1]['action'], 'geton_rejected')

    def test_native_vehicle_body_hit_requires_spent_ammo_and_unique_pellet(self):
        state = self.fixture()
        state.diagnostic_pellet_damage = 500
        hit = bytearray(98)
        struct.pack_into('>IQ', hit, 0, 8, 456)
        struct.pack_into('>3i', hit, 12, 11, 22, 33)
        struct.pack_into('>3f', hit, 25, 11, 22, 100)
        struct.pack_into('>3i', hit, 41, 11, 22, 33)
        struct.pack_into('>3f', hit, 54, 12, 23, 90)
        struct.pack_into('>I', hit, 82, 7)
        struct.pack_into('>II', hit, 90, 100, 8)
        fire = struct.pack('>6fIBIIfII', 11, 22, 100, 12, 23, 90, 7, 0, 100, 0, 1, 0, 0)
        self.assertEqual(state.handle(0x11de, hit, now=10)[1]['reason'], 'unaccepted_or_expired_shot')
        state.note_fire(fire, {'action': 'empty', 'gun_definition': 10402}, now=10)
        self.assertEqual(state.handle(0x11de, hit, now=10)[1]['reason'], 'unaccepted_or_expired_shot')
        state.note_fire(fire, {'action': 'fire', 'gun_definition': 10402}, now=10)
        before = state.vehicles[456]['hp']
        replies, event = state.handle(0x11de, hit, now=10)
        self.assertEqual(event['damage'], min(before, 500))
        self.assertEqual(struct.unpack('>QII', replies[0][1]), (456, max(0,before-500), 3 if before<=500 else (2 if before-500<=10800 else 1)))
        # Использовать живую машину для проверки дубля, геометрии, детали, срока.
        state.register(0x6554, struct.pack('>QII', 456, 20000, 1))
        self.assertEqual(state.handle(0x11de, hit, now=10)[1]['reason'], 'duplicate_pellet')
        struct.pack_into('>I', hit, 94, 9)
        hit[74] = 1
        self.assertEqual(state.handle(0x11de, hit, now=10)[1]['reason'], 'only_body_supported')
        hit[74] = 0
        struct.pack_into('>3f', hit, 25, 1000, 22, 100)
        self.assertEqual(state.handle(0x11de, hit, now=10)[1]['reason'], 'gun_origin_mismatch')
        struct.pack_into('>3f', hit, 25, 11, 22, 100)
        self.assertEqual(state.handle(0x11de, hit, now=13)[1]['reason'], 'unaccepted_or_expired_shot')
        self.assertEqual(state.vehicles[456]['hp'], 20000)
        struct.pack_into('>f', hit, 54, float('nan'))
        with self.assertRaises(ValueError): state.handle(0x11de, hit, now=10)

    def test_status_hp_order_validation_and_persistence_across_seats(self):
        state = self.fixture()
        for hp, status in [(10800, 1), (16200, 2), (21600, 1)]:
            state.register(0x6554, struct.pack('>QII', 456, hp, status))
            self.assertEqual((state.vehicles[456]['hp'], state.vehicles[456]['status']), (hp, status))
            self.assertEqual(state.handle(0x6541, struct.pack('>QI', 456, 1))[1]['action'], 'geton')
            self.assertEqual(state.handle(0x6543, struct.pack('>BiiiB', 0, 11, 22, 33, 0))[1]['action'], 'getoff')
            self.assertEqual(state.vehicles[456]['hp'], hp)
        before = dict(state.vehicles[456])
        for uid, hp, status in [(999, 0, 3), (456, 21601, 1), (456, 100, 0), (456, 100, 4), (456, 100, 5)]:
            state.register(0x6554, struct.pack('>QII', uid, hp, status))
            self.assertEqual(state.vehicles[456], before)
        state.register(0x6554, bytes(15))
        self.assertEqual(state.vehicles[456], before)

    def test_destroyed_vehicle_rejects_movement_but_allows_occupied_exit(self):
        state = self.fixture()
        state.handle(0x6541, struct.pack('>QI', 456, 1))
        state.register(0x6554, struct.pack('>QII', 456, 0, 3))
        movement = bytearray(73)
        struct.pack_into('>Q', movement, 0, 456)
        struct.pack_into('>3i', movement, 13, 900, 800, 700)
        before = state.vehicles[456]['position']
        self.assertEqual(state.handle(0x6549, movement)[1]['reason'], 'destroyed_vehicle')
        self.assertEqual(state.vehicles[456]['position'], before)
        self.assertEqual(state.handle(0x6543, struct.pack('>BiiiB', 0, 11, 22, 33, 0))[1]['action'], 'getoff')
        self.assertEqual(state.handle(0x6541, struct.pack('>QI', 456, 1))[1]['action'], 'geton_rejected')
        state.register(0x6554, struct.pack('>QII', 456, 21600, 1))
        self.assertEqual(state.handle(0x6541, struct.pack('>QI', 456, 1))[1]['action'], 'geton')

    def test_boat_zero_exit_uses_explicit_seat_fixture_and_keeps_remote_exit_rejected(self):
        state=VehicleState(42)
        body=bytearray(79)
        struct.pack_into('>QIII3i',body,0,456,203,1,24000,10000,20000,30000)
        struct.pack_into('>4f',body,33,0,0,-2**-.5,2**-.5)
        state.register(0x654b,body)
        state.handle(0x6541,struct.pack('>QI',456,1))
        self.assertEqual(state.handle(0x6543,struct.pack('>BiiiB',0,90000,20000,30000,0))[1]['action'],'getoff_rejected')
        self.assertEqual(state.seated,456)
        replies,event=state.handle(0x6543,struct.pack('>BiiiB',40,0,0,0,255))
        self.assertTrue(event['boat_zero_exit_fallback'])
        self.assertEqual(event['position'],(10163,19785,30200))
        self.assertEqual(struct.unpack_from('>3i',replies[0][1],28),(10163,19785,30200))
        self.assertIsNone(state.seated)
        other=VehicleState(42)
        struct.pack_into('>4f',body,33,0,0,0,0)
        other.register(0x654b,body);other.handle(0x6541,struct.pack('>QI',456,1))
        self.assertEqual(other.handle(0x6543,struct.pack('>BiiiB',40,0,0,0,255))[1]['reason'],'invalid_boat_fixture_rotation')
        self.assertEqual(other.seated,456)

    def test_snowmotor_driver_movement_and_exit_reject_unknown_uid_and_remote_exit(self):
        state=VehicleState(42)
        body=bytearray(164)
        struct.pack_into('>QIIIiii',body,0,456,109,1,21600,100,200,300)
        state.register(0x654b,body)
        response,event=state.handle(0x6541,struct.pack('>QI',456,1))
        self.assertEqual(event['configuration'],109)
        self.assertEqual(struct.unpack_from('>I',response[0][1],8)[0],109)
        movement=bytearray(73)
        struct.pack_into('>Q',movement,0,999)
        struct.pack_into('>3i',movement,13,500,600,700)
        self.assertEqual(state.handle(0x6549,movement)[1]['action'],'move_rejected')
        self.assertEqual(state.vehicles[456]['position'],(100,200,300))
        struct.pack_into('>Q',movement,0,456)
        self.assertEqual(state.handle(0x6549,movement)[1]['action'],'vehicle_move')
        self.assertEqual(state.vehicles[456]['position'],(500,600,700))
        self.assertEqual(state.handle(0x6543,struct.pack('>BiiiB',0,50000,600,700,0))[1]['action'],'getoff_rejected')
        self.assertEqual(state.seated,456)
        self.assertEqual(state.handle(0x6543,struct.pack('>BiiiB',0,500,600,700,0))[1]['action'],'getoff')
        self.assertIsNone(state.seated)
        struct.pack_into('>I',body,8,110)
        state.register(0x654b,body)
        self.assertEqual(state.vehicles[456]['configuration'],109)

    def test_remote_jeep_exit_is_rejected_without_changing_seat(self):
        state=self.fixture()
        state.handle(0x6541,struct.pack('>QI',456,1),now=100)
        before=dict(state.vehicles[456])
        response,event=state.handle(0x6543,struct.pack('>BiiiB',0,100000,200000,300000,0))
        self.assertEqual(response,[])
        self.assertEqual(event['reason'],'outside_diagnostic_exit_radius')
        self.assertEqual(state.seated,456)
        self.assertEqual(state.seated_at,100)
        self.assertEqual(state.vehicles[456],before)
        self.assertEqual(state.handle(0x6543,struct.pack('>BiiiB',0,11,22,33,0))[1]['action'],'getoff')
        self.assertIsNone(state.seated)

    def test_diagnostic_departure_moves_before_single_result_and_cancels_on_death(self):
        fixture=EvacuationUIFixture(bytes(41),bytes(174),session_statistics=False,
                                   diagnostic_departure_seconds=20)
        state=VehicleState(123,evacuation_delay=8,result_fixture=fixture)
        entity=bytearray(104)
        struct.pack_into('>QIIIiii',entity,0,789,6,9,100,10000,20000,30000)
        state.register(0x654b,entity)
        state.handle(0x6541,struct.pack('>QI',789,1),now=100)
        packets,events=state.poll(118,tick=450)
        self.assertEqual([c for c,_ in packets],[0x6575])
        pos=struct.unpack_from('>iii',packets[0][1],13)
        self.assertEqual(pos[2],43820)
        self.assertFalse(state.evacuation_finished)
        self.assertEqual(state.poll(118,tick=450),([],[]))
        state.cancel_on_death()
        self.assertEqual(state.poll(130,tick=800),([],[]))
        other=VehicleState(123,evacuation_delay=8,result_fixture=fixture)
        other.register(0x654b,entity)
        other.handle(0x6541,struct.pack('>QI',789,1),now=100)
        packets,_=other.poll(128,tick=800)
        self.assertEqual([c for c,_ in packets],[0x6575,0x106e,0xd62,0x6589])
        self.assertTrue(other.evacuation_finished)
        self.assertEqual(other.poll(129,tick=825),([],[]))

    def test_server_flight_updates_boarding_position_and_waits_for_hover(self):
        state=VehicleState(123)
        entity=bytearray(104)
        struct.pack_into('>QIIIiii',entity,0,789,6,9,100,10000,20000,30000)
        state.register(0x654b,entity)
        rope=struct.pack('>QI',890,7)+bytes(75)
        state.register(0x654b,rope)
        state.register(0x657b,struct.pack('>QQ',890,789))
        move=bytearray(73)
        struct.pack_into('>Q',move,0,789)
        struct.pack_into('>iii',move,13,100,200,1300)
        state.register(0x6575,move)
        self.assertEqual(state.handle(0x6541,struct.pack('>QI',789,1))[0],[])
        self.assertEqual(state.handle(0x657a,struct.pack('>Q',890)+bytes(25))[1]['action'],'climb_rejected')
        state.register(0x6588,struct.pack('>QI',789,1))
        self.assertEqual(state.handle(0x6541,struct.pack('>QI',789,1))[0],[])
        state.register(0x6588,struct.pack('>QI',789,2))
        self.assertEqual(state.handle(0x657a,struct.pack('>Q',890)+bytes(25))[1]['action'],'climb_requested')
        response,event=state.handle(0x6541,struct.pack('>QI',789,1))
        self.assertEqual(event['action'],'geton')
        self.assertEqual(struct.unpack_from('>iii',response[0][1],32),(100,200,1300))
        # MOVE_BC другого UID или короткое тело не изменяют нашу сущность.
        struct.pack_into('>Q',move,0,999)
        state.register(0x6575,move)
        state.register(0x6575,bytes(12))
        self.assertEqual(state.vehicles[789]['position'],(100,200,1300))

    def fixture(self, actor=123):
        state = VehicleState(actor)
        payload = bytearray(164)
        struct.pack_into('>QIIIiii', payload, 0, 456, 102, 1, 21600, 10, 20, 30)
        state.register(0x654b, payload)
        return state

    def test_geton_getoff_rebind_actor_and_reject_duplicate(self):
        state = self.fixture()
        responses, event = state.handle(0x6541, struct.pack('>QI', 456, 1))
        self.assertEqual(responses[0][0], 0x6542)
        self.assertEqual(struct.unpack_from('>Q', responses[0][1], 16)[0], 123)
        self.assertEqual(state.handle(0x6541, struct.pack('>QI', 456, 1))[0], [])
        responses, event = state.handle(0x6543, struct.pack('>BiiiB', 0, 11, 22, 33, 0))
        self.assertEqual(len(responses[0][1]), 54)
        self.assertEqual(struct.unpack_from('>Q', responses[0][1], 12)[0], 123)
        self.assertEqual(event['position'], (11, 22, 33))
        self.assertIsNone(state.seated)
        self.assertEqual(state.handle(0x6543, bytes(14))[0], [])

    def test_separate_sessions_and_unregistered_vehicle(self):
        first, second = self.fixture(), self.fixture(999)
        first.handle(0x6541, struct.pack('>QI', 456, 1))
        self.assertIsNone(second.seated)
        self.assertEqual(second.handle(0x6541, struct.pack('>QI', 457, 1))[0], [])
        with self.assertRaises(ValueError):
            first.handle(0x6549, bytes(12))

    def test_helicopter_passenger_seats_and_no_client_driving(self):
        state = VehicleState(123)
        payload = bytearray(104)
        struct.pack_into('>QIIIiii', payload, 0, 789, 6, 9, 100, 10, 20, 1300)
        state.register(0x654b, payload)
        self.assertEqual(state.handle(0x6541, struct.pack('>QI', 789, 5))[0], [])
        response, _ = state.handle(0x6541, struct.pack('>QI', 789, 4))
        self.assertEqual(struct.unpack_from('>I', response[0][1], 8)[0], 6)
        self.assertEqual(struct.unpack_from('>I', response[0][1], 24)[0], 4)
        movement = bytearray(73)
        struct.pack_into('>Q', movement, 0, 789)
        self.assertEqual(state.handle(0x6549, movement)[0], [])
        response, _ = state.handle(0x6543, bytes(14))
        self.assertEqual(struct.unpack_from('>I', response[0][1], 20)[0], 4)

    def test_singleplayer_finish_requires_seat_delay_and_runs_once(self):
        state = VehicleState(123, evacuation_delay=8)
        payload = bytearray(104)
        struct.pack_into('>QIIIiii', payload, 0, 789, 6, 9, 100, 10, 20, 1300)
        state.register(0x654b, payload)
        self.assertEqual(state.poll(100), ([], []))
        state.handle(0x6541, struct.pack('>QI', 789, 1), now=100)
        self.assertEqual(state.poll(107), ([], []))
        responses, events = state.poll(108)
        self.assertEqual(responses, [(0x6589, struct.pack('>BQ', 1, 789))])
        self.assertEqual(state.poll(109), ([], []))
        self.assertEqual(state.handle(0x6543, bytes(14), now=110)[0], [])
        self.assertEqual(state.handle(0x6541, struct.pack('>QI', 789, 1), now=110)[0], [])
        self.assertEqual(state.seated, 789)

    def test_survivor_event_only_after_completed_boarding(self):
        state = VehicleState(123, evacuation_delay=8, survivor_name='LOCAL')
        payload = bytearray(104)
        struct.pack_into('>QIIIiii', payload, 0, 789, 6, 9, 100, 10, 20, 1300)
        state.register(0x654b, payload)
        state.handle(0x6541, struct.pack('>QI', 789, 2), now=100)
        state.handle(0x6543, bytes(14), now=107)
        self.assertEqual(state.poll(108), ([], []))
        state.handle(0x6541, struct.pack('>QI', 789, 2), now=110)
        responses, events = state.poll(118)
        self.assertEqual([code for code, _ in responses], [0x6580, 0x6589])
        body = responses[0][1]
        self.assertEqual(struct.unpack_from('>Q', body)[0], 789)
        self.assertEqual(struct.unpack_from('>Q', body, 16)[0], 123)
        length = struct.unpack_from('>I', body, 24)[0]
        self.assertEqual(body[28:28+length], b'LOCAL\0')
        self.assertEqual(struct.unpack_from('>II', body, 8), (1, 2))
        self.assertEqual(struct.unpack_from('>II', body, 28+length), (0, 0))
        self.assertTrue(events[0]['survivor_notified'])
        self.assertEqual(state.poll(119), ([], []))

    def test_survivor_name_and_slot_limits(self):
        for name in ('', 'a\0b', 'a'*128):
            with self.assertRaises(ValueError):
                survivor_event(789, 123, name, 1)
        for slot in (0, 5):
            with self.assertRaises(ValueError):
                survivor_event(789, 123, 'LOCAL', slot)

    def test_death_cancels_pending_boarding_result_without_survivor(self):
        state = VehicleState(123, evacuation_delay=8, survivor_name='SNOW')
        payload = bytearray(104)
        struct.pack_into('>QIIIiii', payload, 0, 789, 6, 9, 100, 10, 20, 1300)
        state.register(0x654b, payload)
        state.handle(0x6541, struct.pack('>QI', 789, 4), now=100)
        event = state.cancel_on_death()
        self.assertTrue(event['was_seated'])
        self.assertIsNone(state.cancel_on_death())
        self.assertEqual(state.poll(108), ([], []))
        self.assertIsNone(state.seated)
        self.assertFalse(state.climb_protected(101))
        self.assertEqual(state.handle(0x6541, struct.pack('>QI', 789, 1))[0], [])

    def test_terminal_bridge_binds_current_room_and_actor_after_seat(self):
        fixture = EvacuationUIFixture(bytes(41), bytes(174))
        state = VehicleState(123, evacuation_delay=8, survivor_name='LOCAL',
                             result_fixture=fixture, room_uid=999)
        payload = bytearray(104)
        struct.pack_into('>QIIIiii', payload, 0, 789, 6, 9, 100, 10, 20, 1300)
        state.register(0x654b, payload)
        self.assertEqual(state.poll(100), ([], []))
        state.handle(0x6541, struct.pack('>QI', 789, 1), now=100)
        response, events = state.poll(108)
        self.assertEqual([code for code, _ in response], [0x6580, 0x106e, 0xd62, 0x6589])
        self.assertEqual(struct.unpack_from('>Q', response[1][1])[0], 123)
        self.assertEqual(struct.unpack_from('>QQ', response[2][1]), (999, 123))
        self.assertTrue(events[0]['diagnostic_archive_statistics'])
        self.assertEqual(state.poll(109), ([], []))

    def test_session_result_uses_u64_damage_and_rebases_fields_after_utf8_name(self):
        from match_statistics_2022 import MatchStatistics
        terminal = bytearray(41)
        terminal[8:16] = struct.pack('>I', 4)+b'XXX\0'
        outcome = bytearray(174)
        outcome[16:24] = struct.pack('>I', 4)+b'XXX\0'
        fixture = EvacuationUIFixture(bytes(terminal), bytes(outcome), session_statistics=True)
        statistics = MatchStatistics()
        statistics.begin(10)
        statistics.reset_anchor((0, 0, 0))
        statistics.move([(300, 400, 0)])
        statistics.observe(dict(action='hit_damage', target='T', hp=0, damage=1000))
        report = statistics.finish(30, rescued=True)
        responses = fixture.messages(123, 999, report, 'Зима')
        body = responses[1][1]
        length = struct.unpack_from('>I', body, 16)[0]
        self.assertEqual(body[20:20+length], 'Зима'.encode()+b'\0')
        shift = length-4
        self.assertEqual(struct.unpack_from('>QQ', body), (999, 123))
        self.assertEqual(struct.unpack_from('>I', body, 40+shift)[0], 1)
        self.assertEqual(struct.unpack_from('>Q', body, 48+shift)[0], 1000)
        self.assertEqual(struct.unpack_from('>III', body, 84+shift), (500, 1, 20))
        self.assertEqual(body[144+shift:172+shift], bytes(28))
        with self.assertRaises(ValueError):
            fixture.messages(123, 999)

    def test_climb_grace_requires_registered_rope_and_expires(self):
        state = VehicleState(123, result_fixture=EvacuationUIFixture(bytes(41),bytes(174),12))
        plane, rope = bytearray(104), bytearray(87)
        struct.pack_into('>QI',plane,0,789,6)
        struct.pack_into('>QI',rope,0,790,7)
        request=struct.pack('>Q',790)+bytes(25)
        state.register(0x654b,plane)
        state.register(0x654b,rope)
        self.assertEqual(state.handle(0x657a,request,now=100)[1]['action'],'climb_rejected')
        state.register(0x657b,struct.pack('>QQ',790,789))
        event=state.handle(0x657a,request,now=100)[1]
        self.assertEqual(event['diagnostic_protection_seconds'],12)
        self.assertTrue(state.climb_protected(111))
        self.assertFalse(state.climb_protected(112))
        state.handle(0x6541,struct.pack('>QI',789,1),now=110)
        self.assertFalse(state.climb_protected(111))


if __name__ == '__main__':
    unittest.main()
