"""Реальный UDP handshake: виртуальные порты, wrap sequence и ключевой ответ."""
import asyncio
import json
import contextlib
import io
from pathlib import Path
import struct
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'server/directory'))
sys.path.insert(0,str(ROOT/'tools'))
from game_endpoint_probe_2022 import Endpoint,encode_datagram,load_scene_rules,main
from listener import Capture
from roe_tgcp_2023 import parse_datagram,parse_frame,direct_session_key,parse_applications
from roe_protocol_2022 import encrypt,decrypt
from roe_room_2023 import decode_enter_room_response
from test_roe_room_2023 import room_fixture
from weapon_probe_2022 import WeaponFixture, WeaponState
from world_probe_2022 import WorldFixture, WorldState, encode_shrink, encode_shrink_warning
from environment_probe_2022 import EnvironmentFixture


class GameplayActionReplayTests(unittest.TestCase):
    """Новая UDP рамка повторяет старый application id после изменения инвентаря."""
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.capture = Capture(Path(self.temp.name)/'capture')
        self.addCleanup(self.capture.events.close)
        self.endpoint = Endpoint(self.capture, True, auth=True, reliable_udp=getattr(self,'reliable_udp',False))
        self.sent = []
        self.endpoint.transport = SimpleNamespace(sendto=lambda raw,remote:self.sent.append(raw))
        self.remote = ('127.0.0.1',23456)
        with contextlib.redirect_stdout(io.StringIO()):
            self.endpoint.datagram_received(encode_datagram(5000,18001,100,0,0x22,1,0),self.remote)
        self.state = self.endpoint.sessions[(self.remote,5000,18001)]
        self.weapon = WeaponState(WeaponFixture(bytes(82),bytes(60)),42)
        self.weapon.hand_slot = 1
        self.state.update(key_sent=True,auth_sent=True,room_sent=True,actor_uid=42,weapon=self.weapon)

    def request(self, sequence, command, payload):
        plain=(struct.pack('>IIHI',sequence,30+len(payload),command,0)
               +struct.pack('>IIQ',123,0,42)+struct.pack('>I',command)+payload)
        body=encrypt(plain,self.state['key'])
        frame=struct.pack('>HHHHBIII',0x3366,10,10,0x4013,0,3,25,len(body))+bytes(4)+body
        raw=encode_datagram(5000,18001,self.state['next_client'],0,0x18,1,0,frame)
        before=len(self.sent)
        with contextlib.redirect_stdout(io.StringIO()):
            self.endpoint.datagram_received(raw,self.remote)
        return self.sent[before:],raw

    def test_door_request_replay_and_distance_guard(self):
        from door_state_2022 import DoorFixture
        self.endpoint.door_fixture = DoorFixture({7767:((100,200,300),0)})
        self.state['scene_position'] = (100,200,300)
        payload = struct.pack('>II',7767,1)
        packets,_ = self.request(1,0x6f57,payload)
        self.assertEqual([m.command for m in self.terminal_commands(packets)],[0x6f55])
        self.assertEqual(self.state['doors'].status[7767],1)
        packets,_ = self.request(1,0x6f57,payload)
        self.assertFalse(self.terminal_commands(packets))
        self.state['last_movement_position'] = (10000,200,300)
        packets,_ = self.request(2,0x6f57,struct.pack('>II',7767,0))
        self.assertFalse(self.terminal_commands(packets))
        self.assertEqual(self.state['doors'].status[7767],1)

    def test_scene_starter_magazine_follows_chosen_gun_without_rewriting_foreign_actor(self):
        fixture = WeaponFixture(bytes(82), bytes(60), weapon_slots=3,
            starting_equipment=(200906,), winter_starter_inventory=True)
        self.endpoint.weapon_fixture = fixture
        self.state.pop('weapon')
        self.state['winter_choice'] = 1
        self.state['selection_deadline'] = 0
        self.endpoint.scene_rules = [(0x1f49, [
            (0x5fb, b'fixture'),
            (0x4a0, struct.pack('>QIII', 42, 1, 2, 0)),
            (0x4a0, struct.pack('>QIII', 43, 1, 2, 0))], True, 0)]
        packets, _ = self.request(1, 0x1f49, b'')
        syncs = [struct.unpack('>QIII', m.payload) for m in self.terminal_commands(packets)
                 if m.command == 0x4a0]
        self.assertEqual([x[2] for x in syncs if x[0] == 42], [17, 17])
        self.assertIn((43, 1, 2, 0), syncs)

    def terminal_state(self, dead=False):
        from vehicle_probe_2022 import EvacuationUIFixture
        from match_statistics_2022 import MatchStatistics
        self.endpoint.evacuation_result_fixture = EvacuationUIFixture(
            bytes(41), bytes(174), session_statistics=True,
            result_on_death=True, timeout_seconds=10)
        statistics = MatchStatistics();statistics.begin(100)
        self.state.update(world=SimpleNamespace(dead=dead), match_statistics=statistics,
            transport_header=SimpleNamespace(source_port=5000,destination_port=18001,clock=1))
        return statistics

    def terminal_commands(self, packets):
        frames=[parse_frame(parse_datagram(raw).data) for raw in packets if parse_datagram(raw).data]
        return [m for f in frames for m in parse_applications(f,decrypt(f.body,self.state['key']),'server')]

    def test_timeout_callback_needs_no_c2s_and_stops_gameplay(self):
        statistics=self.terminal_state()
        self.weapon.clip=1;self.weapon.pending_reload={'deadline':120}
        medical=SimpleNamespace(pending={'definition':70001},completed_at=1)
        grenades=SimpleNamespace(pending={1:object()})
        self.state.update(medical=medical,throwable_actions=grenades,clock_started=True)
        before=len(self.sent)
        with patch('game_endpoint_probe_2022.time.monotonic',return_value=117):
            self.endpoint.poll_match_ends()
        messages=self.terminal_commands(self.sent[before:])
        self.assertEqual([m.command for m in messages],[0x106e,0xd62,0x6589])
        self.assertEqual(messages[-1].payload,bytes(9))
        self.assertEqual(statistics.snapshot(200)['survival_seconds'],10)
        self.assertTrue(self.state['match_finished']);self.assertFalse(self.state['clock_started'])
        self.assertIsNone(self.weapon.pending_reload);self.assertIsNone(medical.pending)
        self.assertIsNone(medical.completed_at);self.assertFalse(grenades.pending)
        for field in ('world','weapon','medical','throwable_actions'):
            self.assertNotIn(field,self.state)
        before=len(self.sent)
        with patch('game_endpoint_probe_2022.time.monotonic',return_value=120):
            self.endpoint.poll_match_ends()
            packets,_=self.request(1,0x11da,struct.pack('>I',1))
        self.assertEqual(self.weapon.clip,1)
        self.assertFalse(self.terminal_commands(packets))
        self.assertEqual(len(self.sent),before+1) # Только UDP ACK запроса, не повтор result.

    def test_death_preserves_frozen_stats_and_has_no_survivor_event(self):
        statistics=self.terminal_state(dead=True);statistics.finish(105)
        with patch('game_endpoint_probe_2022.time.monotonic',return_value=107):
            self.endpoint.check_match_end(self.state['transport_header'],self.remote,self.state,107)
        self.assertEqual(statistics.snapshot(200)['survival_seconds'],5)
        self.assertEqual(statistics.snapshot(200)['rescued'],0)
        self.assertEqual([m.command for m in self.terminal_commands(self.sent[1:])],
                         [0x106e,0xd62,0x6589])

    def test_terminal_cannot_handoff_but_unfinished_policy_keeps_deadline(self):
        from match_result_2022 import MatchEndPolicy
        self.state.update(identity=b'LOCAL',handoff_at=100,match_finished=True)
        identity=(('127.0.0.1',23457),5001,18001)
        new=dict(auth_sent=True,identity=b'LOCAL',room_sent=False,frame_seq=3)
        self.endpoint.sessions[identity]=new
        self.assertFalse(self.endpoint.resume_gameplay(identity,new,101))
        self.state['match_finished']=False
        policy=MatchEndPolicy(timeout_seconds=10);self.state['match_end_policy']=policy
        self.assertTrue(self.endpoint.resume_gameplay(identity,new,101))
        self.assertIs(new['match_end_policy'],policy)
        self.assertNotIn('match_end_policy',self.state)

    def test_finished_result_relay_checks_actor_deadline_and_does_not_restore_gameplay(self):
        statistics=self.terminal_state();self.state['identity']=b'LOCAL'
        with patch('game_endpoint_probe_2022.time.monotonic',return_value=117):
            self.endpoint.check_match_end(self.state['transport_header'],self.remote,self.state,117)
        self.endpoint.reliable_udp=self.endpoint.idle_handoff=True
        identity=(('127.0.0.1',23457),5001,18001)
        new=dict(auth_sent=True,identity=b'LOCAL',room_sent=False,frame_seq=3)
        self.endpoint.sessions[identity]=new
        self.endpoint.scene_rules=[(0xdcd,[(0x7083,b'\0')])]
        header=SimpleNamespace(source_port=5001,destination_port=18001,clock=1)
        with patch.object(self.endpoint,'send_application') as sync, patch.object(self.endpoint,'send_application_batch') as send:
            self.assertFalse(self.endpoint.resume_finished_result(identity,header,new,118,43))
            self.assertFalse(self.endpoint.resume_finished_result(identity,header,new,148,42))
            self.assertTrue(self.endpoint.resume_finished_result(identity,header,new,118,42))
            self.assertFalse(self.endpoint.resume_finished_result(identity,header,new,119,42))
        sync.assert_called_once_with(header,identity[0],new,0x7083,b'\0')
        send.assert_called_once_with(header,identity[0],new,self.state['match_terminal_packets'])
        self.assertTrue(new['match_finished']);self.assertIs(new['match_statistics'],statistics)
        self.assertEqual(statistics.snapshot(200)['survival_seconds'],10)
        self.assertNotIn('world',new);self.assertNotIn('weapon',new)
        self.assertTrue(self.state['transport_retired']);self.assertFalse(self.state['room_sent'])

    def test_ui_winter_choice_is_saved_but_cannot_replace_live_inventory(self):
        self.endpoint.weapon_fixture = WeaponFixture(bytes(82), bytes(60), starting_equipment=(200906,))
        self.state.pop('weapon')
        self.state['selection_deadline'] = 200
        with patch('game_endpoint_probe_2022.time.monotonic', return_value=self.endpoint.started+100):
            self.request(1, 0x10cc, struct.pack('>II', 1, 1))
        self.assertEqual(self.state['winter_choice'], 1)
        self.state['weapon'] = self.weapon
        with patch('game_endpoint_probe_2022.time.monotonic', return_value=self.endpoint.started+101):
            self.request(2, 0x10cc, struct.pack('>II', 1, 3))
        self.assertEqual(self.state['winter_choice'], 1)
        self.assertIs(self.state['weapon'], self.weapon)

    def test_selected_cell_patches_both_spawn_packets_without_late_change(self):
        self.state.pop('weapon')
        self.endpoint.spawn_points = ((12,26,365100,544000,259407), (13,8,377600,313600,256529))
        self.state['selection_deadline'] = 200
        with patch('game_endpoint_probe_2022.time.monotonic', return_value=self.endpoint.started+100):
            self.request(1, 0x11df, struct.pack('>IQIII',2,42,13,8,0))
        self.assertEqual(self.state['born_point'], self.endpoint.spawn_points[1])
        self.endpoint.scene_rules = [(0x1f49,[(0x27,bytes(40),[0],[31]), (0x27,bytes(40),[0],[31])],True,0)]
        captured=[]
        original=self.endpoint.register_fixture_entity
        def register(state, code, payload):
            if code==0x27:captured.append(payload)
            original(state, code, payload)
        with patch.object(self.endpoint,'register_fixture_entity',side_effect=register), patch('game_endpoint_probe_2022.time.monotonic',return_value=self.endpoint.started+201):
            self.request(2, 0x11df, struct.pack('>IQIII',2,42,12,26,1))
            self.request(3, 0x1f49, bytes(4))
        self.assertEqual(self.state['born_point'], self.endpoint.spawn_points[1])
        self.assertEqual(len(captured),2)
        for payload in captured:
            self.assertEqual(struct.unpack_from('>iii',payload,8),(377600,313600,256529))
            self.assertEqual(struct.unpack_from('>Q',payload)[0],42)


    def test_fixed_practice_spawn_preserves_uid_tick_and_ignores_selected_cell(self):
        self.state.update(selection_deadline=0, born_point=(12,26,1,2,3))
        body = bytearray(40)
        struct.pack_into('>3i', body, 8, 548255,483380,255000)
        self.endpoint.scene_rules = [(0x1f49,[(0x27,bytes(body),(0,),(31,),True)],True,0)]
        captured=[]
        with patch.object(self.endpoint,'register_fixture_entity',side_effect=lambda st,c,p:captured.append((c,p))), patch('game_endpoint_probe_2022.time.monotonic',return_value=self.endpoint.started+201):
            self.request(1,0x1f49,bytes(4))
        payload = next(p for c,p in captured if c==0x27)
        self.assertEqual(struct.unpack_from('>3i',payload,8),(548255,483380,255000))
        self.assertEqual(struct.unpack_from('>Q',payload)[0],42)
        self.assertEqual(struct.unpack_from('>I',payload,31)[0],5025)

    def test_movement_guard_rejects_jump_before_world_loot_mutation_and_corrects_position(self):
        from dataclasses import replace
        from movement_validation_2022 import MovementLimits
        fixture = WorldFixture(1000,100,(10000,10000,11000,11000),50,1,(),
                               movement_limits=MovementLimits())
        self.endpoint.world_fixture = fixture
        world = WorldState(fixture,42,0)
        world.position = (0,0,0)
        self.state.update(world=world,scene_position=(0,0,0),scene_position_sync=bytes(40))
        def body(*positions):
            return (struct.pack('>i',len(positions))
                    + b''.join(struct.pack('>iiiBBBI',*p,0,0,0,1) for p in positions)
                    + struct.pack('>IBfffIBB',0,0,0,0,0,0,0,0)
                    + b''.join(struct.pack('>BQ',0,42) for _ in positions))
        with patch('game_endpoint_probe_2022.time.monotonic',return_value=100):
            self.request(100,0x2a,body((500,0,0)))
        self.assertEqual((world.position,self.weapon.position,self.state['last_movement_position']),
                         ((500,0,0),)*3)
        guard = self.state['movement_guard']
        budget = guard.horizontal_budget
        with patch('game_endpoint_probe_2022.time.monotonic',return_value=100):
            packets,_ = self.request(101,0x2a,body((10500,10500,0)))
        self.assertEqual((world.position,self.weapon.position,self.state['last_movement_position']),
                         ((500,0,0),)*3)
        self.assertFalse(world.inside)
        self.assertEqual(guard.horizontal_budget,budget)
        frames=[parse_frame(parse_datagram(raw).data) for raw in packets if parse_datagram(raw).data]
        messages=[m for f in frames for m in parse_applications(f,decrypt(f.body,self.state['key']),'server')]
        correction=next(m.payload for m in messages if m.command==0x27)
        self.assertEqual(struct.unpack_from('>Q3i',correction),(42,500,0,0))
        # Только серверный27 разрешает перенос и новый burst.
        authorized=bytearray(40);struct.pack_into('>Q3i',authorized,0,42,1000000,0,0)
        with patch('game_endpoint_probe_2022.time.monotonic',return_value=101):
            self.endpoint.register_fixture_entity(self.state,0x27,bytes(authorized))
            self.request(102,0x2a,body((1000500,0,0)))
        self.assertEqual(world.position,(1000500,0,0))

    def test_death_during_first_message_blocks_fire_in_same_udp_batch(self):
        fixture = WorldFixture(50,0,(10,20,30,40),50,1,(),death_on_zero=True)
        world = WorldState(fixture,42,0)
        world.update_position((20,30,0),0)
        self.endpoint.world_fixture = fixture
        self.state['world'] = world
        before = (self.weapon.clip,self.weapon.reserve)
        fire = struct.pack('>6fIBIIfII',0,0,0,0,0,0,1,0,1,0,0,0,0)
        parts=[]
        for sequence, command, payload in ((100,0x1f49,bytes(4)),(101,0x11da,fire)):
            parts.append(struct.pack('>IIHI',sequence,30+len(payload),command,0)
                         +struct.pack('>IIQ',123,0,42)+struct.pack('>I',command)+payload)
        extra=bytes((0,0,0,1))+struct.pack('>H',len(parts[0]))
        body=encrypt(b''.join(parts),self.state['key'])
        frame=struct.pack('>HHHHBIII',0x3366,10,10,0x4013,0,3,21+len(extra),len(body))+extra+body
        raw=encode_datagram(5000,18001,self.state['next_client'],0,0x18,1,0,frame)
        with patch('game_endpoint_probe_2022.time.monotonic',return_value=100), contextlib.redirect_stdout(io.StringIO()):
            self.endpoint.datagram_received(raw,self.remote)
        self.assertTrue(world.dead)
        self.assertEqual(world.hp,0)
        self.assertEqual((self.weapon.clip,self.weapon.reserve),before)
        events=[json.loads(line) for line in (Path(self.temp.name)/'capture/events.jsonl').read_text().splitlines()]
        self.assertEqual(sum(e.get('action')=='own_death' for e in events),1)
        self.assertTrue(any(e.get('kind')=='dead_action_rejected' and e.get('command')=='0x11da' for e in events))

    def test_bot_hit_updates_own_armor_before_hp_and_preserves_weapon_through_break(self):
        from dataclasses import replace
        from actor_probe_2022 import ActorFixture, ActorState
        actor_fixture = ActorFixture(43, b'', bytes(1100), bytes(49), (900,0,0),
                                     ((900,0,0),), 0, 1000, 50, bytes(80), (1500,50,3,2))
        actor = ActorState(actor_fixture)
        actor.started = True
        actor.started_at = 0
        self.endpoint.actor_fixture = actor_fixture
        self.state['target_actor'] = actor
        fixture = WorldFixture(100,0,(10000,10000,11000,11000),50,1,(),death_on_zero=True)
        world = WorldState(fixture,42,0)
        world.position = (0,0,0)
        self.endpoint.world_fixture = fixture
        self.state['world'] = world
        self.weapon.fixture = replace(self.weapon.fixture, combat_armor_absorb_percent=50)
        self.weapon.equipment[12] = 201001
        self.weapon.equipment_durability[12] = 1
        gun, reserve = self.weapon.guns[1], self.weapon.reserve
        with patch('game_endpoint_probe_2022.time.monotonic',return_value=100):
            packets, _ = self.request(100,0x1f49,bytes(4))
        frames = [parse_frame(parse_datagram(raw).data) for raw in packets if parse_datagram(raw).data]
        messages = [m for f in frames for m in parse_applications(f,decrypt(f.body,self.state['key']),'server')]
        commands = [m.command for m in messages]
        self.assertLess(commands.index(0x3e82), commands.index(0x1069))
        self.assertEqual((world.hp,self.weapon.equipment_durability[12]),(51,0))
        self.assertIs(self.weapon.guns[1],gun)
        self.assertEqual(self.weapon.reserve,reserve)
        # Тот же application replay не повторяет расход; следующий удар после
        # interval пробивает уже сломанный жилет на полные50raw.
        with patch('game_endpoint_probe_2022.time.monotonic',return_value=100):
            self.request(100,0x1f49,bytes(4))
        self.assertEqual(world.hp,51)
        with patch('game_endpoint_probe_2022.time.monotonic',return_value=103):
            self.request(101,0x1f49,bytes(4))
        self.assertEqual(world.hp,1)
        self.assertEqual(self.weapon.equipment_durability[12],0)


    def test_bot_finite_ammunition_and_blocked_los_limit_encrypted_heartbeat_damage(self):
        from actor_probe_2022 import ActorFixture, ActorState
        for blocked in (True,False):
            with self.subTest(blocked=blocked):
                boxes = (((400,-100,-100),(600,100,300)),) if blocked else ()
                fixture = ActorFixture(43,b'',bytes(1100),bytes(49),(900,0,0),
                    ((900,0,0),),0,1000,50,bytes(80),(1500,50,3,2),
                    collision_boxes=boxes,attack_ammunition=(2,1))
                actor = ActorState(fixture);actor.started=True;actor.started_at=98
                self.endpoint.actor_fixture=fixture;self.state['target_actor']=actor
                world_fixture = WorldFixture(1000,0,(10000,10000,11000,11000),50,1,(),death_on_zero=True)
                world = WorldState(world_fixture,42,0);world.position=(0,0,0)
                self.endpoint.world_fixture=world_fixture;self.state['world']=world
                for sequence, now in enumerate((100,103,106,108.129,108.131,120), start=110 if blocked else 120):
                    with patch('game_endpoint_probe_2022.time.monotonic',return_value=now):
                        self.request(sequence,0x1f49,bytes(4))
                self.assertEqual((world.hp,actor.spent_ammunition,actor.magazine,actor.reserve),
                                 (1000,0,2,1) if blocked else (850,3,0,0))
                self.assertEqual(actor.magazine+actor.reserve+actor.spent_ammunition,3)

    def test_dead_requests_cannot_spend_ammunition_or_move_player(self):
        self.state['world'] = WorldState(WorldFixture(
            0, 0, (10,20,30,40), 50, 1, (), death_on_zero=True), 42, 0)
        before = (self.weapon.clip, self.weapon.reserve, self.weapon.hand_slot)
        fire = struct.pack('>6fIBIIfII',0,0,0,0,0,0,1,0,1,0,0,0,0)
        for sequence, command, body in ((100,0x11da,fire),
                (101,0x49c,struct.pack('>I',1)), (102,0x2a,b'bad'),
                (103,0x3b63,b'bad'), (104,0x3e80,b'bad'),
                (105,0x6541,b'bad'), (106,0x656f,b'bad')):
            packets, _ = self.request(sequence, command, body)
            self.assertTrue(all(not parse_datagram(raw).data for raw in packets))
        self.assertEqual((self.weapon.clip,self.weapon.reserve,self.weapon.hand_slot),before)
        self.assertNotIn('last_movement_position',self.state)

    def test_death_cancels_pending_actions_and_resume_reasserts_death_last(self):
        from dataclasses import replace
        from medical_probe_2022 import MedicalState
        self.weapon = WeaponState(replace(self.weapon.fixture, timed_reload=True,
                                         reload_update='delta'),42)
        self.weapon.hand_slot = 1
        self.weapon.clip = 0
        self.weapon.handle(0x49c,struct.pack('>I',1),now=100)
        self.assertIsNotNone(self.weapon.pending_reload)
        world = WorldState(WorldFixture(0,0,(10,20,30,40),50,1,(),
                                       death_on_zero=True),42,0)
        medical = MedicalState(self.weapon,world)
        medical.pending = {'definition':70001,'deadline':100}
        medical.completed_at = 100
        self.state.update(weapon=self.weapon,world=world,medical=medical)
        packets=[]
        self.endpoint.send_application = lambda d,r,s,c,p: packets.append((c,p))
        with patch('game_endpoint_probe_2022.time.monotonic',return_value=103):
            self.endpoint.restore_resume_inventory(None,self.remote,self.state)
        self.assertIsNone(self.weapon.pending_reload)
        self.assertIsNone(medical.pending)
        self.assertIsNone(medical.completed_at)
        self.assertEqual((self.weapon.clip,self.weapon.reserve),(0,6))
        self.assertEqual(packets[-1],world.death_message())
        self.assertFalse(any(c==0x2b for c,p in packets))
        size=len(packets)
        self.endpoint.restore_resume_inventory(None,self.remote,self.state)
        self.assertEqual(len(packets),size)

    def test_reload_replay_after_another_shot_does_not_consume_reserve(self):
        self.weapon.clip=1
        self.request(100,0x49c,struct.pack('>I',1))
        self.assertEqual((self.weapon.clip,self.weapon.reserve),(2,5))
        fire=struct.pack('>6fIBIIfII',0,0,0,0,0,0,1,0,1,0,0,0,0)
        self.request(101,0x11da,fire)
        self.assertEqual((self.weapon.clip,self.weapon.reserve),(1,5))
        packets,_=self.request(100,0x49c,struct.pack('>I',1))
        self.assertEqual((self.weapon.clip,self.weapon.reserve),(1,5))
        self.assertTrue(all(not parse_datagram(raw).data for raw in packets))
        # То же содержимое с новым id — обычная следующая перезарядка.
        self.request(102,0x49c,struct.pack('>I',1))
        self.assertEqual((self.weapon.clip,self.weapon.reserve),(2,4))

    def test_pending_reload_handoff_republishes_magazine_once_without_respending(self):
        from dataclasses import replace
        self.weapon = WeaponState(replace(self.weapon.fixture, timed_reload=True,
                                         reload_update='delta'), 42)
        self.weapon.hand_slot = 1
        self.weapon.clip = 1
        self.state['weapon'] = self.weapon
        self.weapon.handle(0x49c, struct.pack('>I', 1), now=100)
        header = SimpleNamespace(source_port=5000, destination_port=18001, clock=1)
        with patch('game_endpoint_probe_2022.time.monotonic', return_value=120):
            self.endpoint.restore_resume_inventory(header, self.remote, self.state)
            packets, _ = self.request(150, 0x1f49, bytes(4))
        messages = self.terminal_commands(packets)
        magazines = [struct.unpack('>QIII', m.payload) for m in messages if m.command == 0x4a0]
        self.assertEqual(magazines, [(42, 1, 2, 0), (42, 1, 2, 0)])
        self.assertEqual((self.weapon.clip, self.weapon.reserve), (2, 5))
        self.assertNotIn('resume_reload_reconcile', self.state)
        with patch('game_endpoint_probe_2022.time.monotonic', return_value=121):
            packets, _ = self.request(151, 0x1f49, bytes(4))
        self.assertFalse(any(m.command == 0x4a0 for m in self.terminal_commands(packets)))
        self.assertEqual((self.weapon.clip, self.weapon.reserve), (2, 5))

    def test_pending_reload_handoff_cancel_cannot_republish_replaced_gun(self):
        from dataclasses import replace
        self.weapon = WeaponState(replace(self.weapon.fixture, timed_reload=True,
                                         reload_update='delta'), 42)
        self.weapon.hand_slot = 1
        self.weapon.clip = 1
        self.state['weapon'] = self.weapon
        self.weapon.handle(0x49c, struct.pack('>I', 1), now=100)
        self.state['resume_reload_reconcile'] = (1, self.weapon.guns[1].uid)
        self.weapon.pending_reload = None
        self.weapon.guns[1].uid += 1
        packets = [(0x4a0, self.weapon.ammunition_sync())]
        result = self.endpoint.reconcile_resume_reload(self.remote, self.state,
                    packets, [dict(action='reload', slot=1)])
        self.assertEqual(result, packets)
        self.assertNotIn('resume_reload_reconcile', self.state)
        self.assertEqual((self.weapon.clip, self.weapon.reserve), (1, 6))

    def test_fire_after_reload_deadline_commits_pending_reload_first(self):
        from dataclasses import replace
        self.weapon = WeaponState(replace(self.weapon.fixture, reload_update='delta',
                                          timed_reload=True), 42)
        self.weapon.hand_slot = 1
        self.weapon.clip = 0
        self.state['weapon'] = self.weapon
        with patch('weapon_probe_2022.time.monotonic', return_value=100):
            self.request(100, 0x49c, struct.pack('>I', 1))
        self.assertEqual((self.weapon.clip,self.weapon.reserve),(0,6))
        fire=struct.pack('>6fIBIIfII',0,0,0,0,0,0,1,0,1,0,0,0,0)
        with patch('weapon_probe_2022.time.monotonic', return_value=102.2):
            self.request(101, 0x11da, fire)
        self.assertIsNone(self.weapon.pending_reload)
        self.assertEqual((self.weapon.clip,self.weapon.reserve),(1,4))
        self.request(101, 0x11da, fire)
        self.assertEqual((self.weapon.clip,self.weapon.reserve),(1,4))

    def ground(self, quantity=20):
        from weapon_probe_2022 import LootFixture
        template=bytearray(100)
        struct.pack_into('>Q',template,4,999)
        item=LootFixture(999,15510,quantity,(100,200,300),bytes(45),30004,bytes(template))
        self.weapon=WeaponState(WeaponFixture(bytes(82),bytes(60),loot=item,
                               starting_equipment=(200907,)),42)
        self.weapon.available_loot.add(999)
        self.weapon.update_position((100,200,300))
        self.state['weapon']=self.weapon

    def test_discard_replay_creates_only_one_ground_entity(self):
        self.ground()
        request=struct.pack('>BBBBHIIB',2,2,0,1,2,0,0,1)
        self.request(100,0x3e80,request)
        reserve=self.weapon.reserve;counter=self.weapon.drop_counter
        packets,_=self.request(100,0x3e80,request)
        self.assertEqual((self.weapon.reserve,self.weapon.drop_counter),(reserve,counter))
        self.assertTrue(all(not parse_datagram(raw).data for raw in packets))
        self.request(101,0x3e80,request)
        self.assertEqual((self.weapon.reserve,self.weapon.drop_counter),(reserve-2,counter+1))

    def test_partial_ground_pickup_replay_after_freeing_capacity_does_not_grant_more(self):
        self.ground();self.weapon.reserve=110
        request=struct.pack('>IIQBHB3iB',15510,0,0,0,0,1,100,200,300,0)
        self.request(100,0x3b63,request)
        self.assertEqual((self.weapon.reserve,self.weapon.loot_registry[15510].quantity),(120,10))
        self.request(101,0x3e80,struct.pack('>BBBBHIIB',2,2,0,1,5,0,0,1))
        self.request(100,0x3b63,request)
        self.assertEqual((self.weapon.reserve,self.weapon.loot_registry[15510].quantity),(115,10))
        self.request(102,0x3b63,request)
        self.assertEqual((self.weapon.reserve,self.weapon.loot_registry[15510].quantity),(120,5))

    def test_same_udp_segment_is_already_idempotent(self):
        self.weapon.clip=1
        _,raw=self.request(100,0x49c,struct.pack('>I',1))
        self.weapon.clip=1
        with contextlib.redirect_stdout(io.StringIO()):
            self.endpoint.datagram_received(raw,self.remote)
        self.assertEqual((self.weapon.clip,self.weapon.reserve),(1,5))

    def test_partial_container_pickup_replay_and_reopen_use_current_contents(self):
        from parcel_probe_2022 import ParcelFixture, ParcelState
        from parcel_catalog_2022 import ContainerFixture, ParcelCatalog, ParcelCatalogState
        from weapon_probe_2022 import LootFixture
        for catalog in (False, True):
            with self.subTest(catalog=catalog):
                self.ground()
                self.state.pop('inventory_action_sequence',None)
                self.weapon.reserve=110
                if catalog:
                    item=LootFixture(1000,15521,20,(100,200,300),bytes(45),30004,bytes(100))
                    parcels=ParcelCatalogState(ParcelCatalog((ContainerFixture(456,15520,(100,200,300),(item,)),)))
                else:
                    parcels=ParcelState(ParcelFixture(456,15520,15521,20,(100,200,300)))
                parcels.register(0x654b,struct.pack('>QI',456,501)+bytes(105))
                parcels.register(0x6571,struct.pack('>QI',456,15520))
                self.state['parcels']=parcels
                self.request(99,0x656f,struct.pack('>Q',456))
                request=struct.pack('>IIQBHB3iB',15520,15521,0,0,0,1,100,200,300,0)
                self.request(100,0x3b63,request)
                self.assertEqual(self.weapon.reserve,120)
                self.request(101,0x3e80,struct.pack('>BBBBHIIB',2,2,0,1,5,0,0,1))
                packets,_=self.request(100,0x3b63,request)
                self.assertEqual(self.weapon.reserve,115)
                self.assertTrue(all(not parse_datagram(raw).data for raw in packets))
                # OPEN — просмотр текущего остатка, не повторная выдача.
                packets,_=self.request(99,0x656f,struct.pack('>Q',456))
                frames=[parse_frame(parse_datagram(raw).data) for raw in packets if parse_datagram(raw).data]
                contents=[m.payload for f in frames for m in parse_applications(f,decrypt(f.body,self.state['key']),'server') if m.command==0x3b61]
                self.assertEqual(struct.unpack_from('>I',contents[0],20)[0],10)
                self.request(102,0x3b63,request)
                self.assertEqual(self.weapon.reserve,120)

    def test_serial_wrap_stale_and_same_id_different_payload(self):
        self.ground();self.weapon.reserve=10
        drop=struct.pack('>BBBBHIIB',2,2,0,1,1,0,0,1)
        self.request(0xffffffff,0x3e80,drop)
        self.request(0,0x3e80,drop)
        self.assertEqual((self.weapon.reserve,self.weapon.drop_counter),(8,2))
        for sequence,payload in [(0xffffffff,drop),(0,struct.pack('>BBBBHIIB',2,2,0,1,2,0,0,1)),(0x80000000,drop)]:
            self.request(sequence,0x3e80,payload)
        self.assertEqual((self.weapon.reserve,self.weapon.drop_counter),(8,2))
        self.request(1,0x3e80,drop)
        self.assertEqual((self.weapon.reserve,self.weapon.drop_counter),(7,3))


class Client(asyncio.DatagramProtocol):
    def __init__(self):self.queue=asyncio.Queue()
    def connection_made(self,transport):self.transport=transport
    def datagram_received(self,data,remote):self.queue.put_nowait(data)


class GameplayHandoffTests(unittest.TestCase):
    def fixture(self):
        events = []
        endpoint = Endpoint(SimpleNamespace(record=lambda *a, **kw: events.append((a,kw))))
        old_key = (('127.0.0.1', 1111), 5000, 18001)
        new_key = (('127.0.0.1', 2222), 5001, 18001)
        weapon, world = object(), object()
        old = dict(identity=b'local\0', auth_sent=True, room_sent=True,
                   handoff_at=100, weapon=weapon, world=world, actor_uid=123,
                   room_uid=456, selection_deadline=90, scene_rules_sent={0,1},
                   clock_started=True, key=b'old', frame_seq=1023, seq=999)
        new = dict(identity=b'local\0', auth_sent=True, room_sent=False,
                   key=b'new', frame_seq=3, seq=20)
        endpoint.sessions = {old_key:old, new_key:new}
        return endpoint, old_key, new_key, old, new, weapon, world, events

    def test_resume_moves_gameplay_without_reusing_transport_or_resetting_timer(self):
        endpoint, _, key, old, new, weapon, world, events = self.fixture()
        catalog = object()
        old['loot_catalog'] = catalog
        old['environment_initialized'] = True
        self.assertTrue(endpoint.resume_gameplay(key,new,101))
        self.assertIs(new['weapon'],weapon)
        self.assertIs(new['world'],world)
        self.assertIs(new['loot_catalog'],catalog)
        self.assertIs(new['environment_initialized'],True)
        self.assertEqual((new['actor_uid'],new['room_uid'],new['selection_deadline']), (123,456,90))
        self.assertEqual(new['scene_rules_sent'],{0,1})
        self.assertEqual((new['key'],new['frame_seq'],new['seq']), (b'new',3,20))
        self.assertFalse(old['room_sent'])
        self.assertNotIn('weapon',old)
        self.assertFalse(endpoint.resume_gameplay(key,new,102))
        self.assertEqual(events[0][0],('gameplay_handoff_complete',))

    def test_resume_moves_door_state_and_reissues_visible_status(self):
        from door_state_2022 import DoorFixture, DoorState
        endpoint, _, key, old, new, _, _, events = self.fixture()
        doors = DoorState(DoorFixture({7767:((100,200,300),0)}))
        doors.handle(struct.pack('>II',7767,1),(100,200,300))
        old['doors'] = doors
        self.assertTrue(endpoint.resume_gameplay(key,new,101))
        self.assertIs(new['doors'],doors)
        self.assertNotIn('doors',old)
        self.assertEqual(doors.snapshot((100,200,300))[0][1][4],1)
        self.assertEqual(events[0][1]['door_state_changes'],{'7767':1})

    def test_resume_moves_breakable_state_and_reissues_damaged_part(self):
        from breakable_state_2022 import BreakableFixture, BreakableState
        endpoint, _, key, old, new, _, _, events = self.fixture()
        broken = BreakableState(BreakableFixture({7690:((100,200,300),(1,))}),123)
        context=bytearray(72);struct.pack_into('<QI',context,0,123,0)
        request=struct.pack('>III',7690,1,1000)+b'\x48'+context
        replies,event=broken.handle(request,(100,200,300))
        old['breakables']=broken
        self.assertTrue(endpoint.resume_gameplay(key,new,101))
        self.assertIs(new['breakables'],broken);self.assertNotIn('breakables',old)
        self.assertEqual(broken.remaining[7690],[0])
        self.assertEqual(broken.snapshot((100,200,300)),replies)

    def test_resume_preserves_accumulated_statistics_and_anchor(self):
        from match_statistics_2022 import MatchStatistics
        endpoint, _, key, old, new, _, _, _ = self.fixture()
        statistics = MatchStatistics()
        statistics.begin(10)
        statistics.reset_anchor((0, 0, 0))
        statistics.move([(300, 400, 0)])
        statistics.observe(dict(action='hit_damage', target='T', damage=1000, hp=0))
        old['match_statistics'] = statistics
        self.assertTrue(endpoint.resume_gameplay(key, new, 101))
        self.assertIs(new['match_statistics'], statistics)
        self.assertNotIn('match_statistics', old)
        statistics.move([(300, 400, 1200)])
        result = statistics.finish(120, True)
        self.assertEqual((result['survival_seconds'], result['distance_cm'],
                          result['kills'], result['damage_raw']), (110, 1700, 1, 1000))

    def test_resume_moves_corpse_ownership_and_remaining_without_recreation(self):
        endpoint, _, key, old, new, _, _, _ = self.fixture()
        corpses, inventory = object(), object()
        old.update(death_parcels=corpses, target_inventory=inventory,
                   own_death_inventory_processed=True)
        self.assertTrue(endpoint.resume_gameplay(key,new,101))
        self.assertIs(new['death_parcels'],corpses)
        self.assertIs(new['target_inventory'],inventory)
        self.assertIs(new['own_death_inventory_processed'],True)
        self.assertNotIn('death_parcels',old)

    def test_resume_preserves_grenade_identifiers_and_pending_deadline(self):
        from throwable_actions_2022 import ThrowableActions, decode_throw
        endpoint, _, key, old, new, _, _, _ = self.fixture()
        grenades=ThrowableActions()
        request=decode_throw(bytes.fromhex('0000c3510005920c00084ce90003f4c3000000267500000000000006d90000059c4400084b170003f3640000000000000009c4'))
        grenades.pending[0]=(request,99)
        grenades.completed.add(1)
        old['throwable_actions']=grenades
        self.assertTrue(endpoint.resume_gameplay(key,new,101))
        self.assertIs(new['throwable_actions'],grenades)
        self.assertEqual(new['throwable_actions'].pending[0][1],99)
        self.assertEqual(new['throwable_actions'].completed,{1})
        self.assertNotIn('throwable_actions',old)

    def test_resume_starts_fresh_inventory_sequence_boundary(self):
        endpoint, _, key, old, new, _, _, _ = self.fixture()
        old['inventory_action_sequence']=0xfffffff0
        self.assertTrue(endpoint.resume_gameplay(key,new,101))
        self.assertNotIn('inventory_action_sequence',new)
        message=SimpleNamespace(sequence=1,command=0x49c)
        self.assertTrue(endpoint.accept_inventory_action(new,message,key[0]))
        self.assertFalse(endpoint.accept_inventory_action(new,message,key[0]))

    def test_resume_pending_medical_preserves_deadline_and_spends_once(self):
        from medical_probe_2022 import MedicalState
        endpoint, _, key, old, new, *_ = self.fixture()
        weapon = WeaponState(WeaponFixture(bytes(82), bytes(60)), 123)
        weapon.medical[70001] = 2
        world = SimpleNamespace(hp=500)
        medical = MedicalState(weapon, world)
        request = bytes.fromhex('03020003009c00000001')
        medical.handle(0x3e80, request, 99)
        old.update(weapon=weapon, world=world, medical=medical)
        self.assertTrue(endpoint.resume_gameplay(key, new, 101))
        self.assertNotIn('medical', old)
        self.assertIs(new['medical'].weapon, new['weapon'])
        self.assertIs(new['medical'].world, new['world'])
        _, events = new['medical'].handle(0x3e80, request, 101)
        self.assertEqual(events[0]['reason'], 'action_in_progress')
        self.assertEqual(new['medical'].poll(101.99), ([], []))
        new['medical'].poll(102)
        self.assertEqual((world.hp, weapon.medical[70001]), (600, 1))
        self.assertEqual(new['medical'].poll(103), ([], []))

    def test_initial_environment_waits_for_inventory_and_does_not_repeat(self):
        with tempfile.TemporaryDirectory() as temporary, contextlib.redirect_stdout(io.StringIO()):
            capture = Capture(Path(temporary)/'capture')
            endpoint = Endpoint(capture, True, auth=True,
                                environment_fixture=EnvironmentFixture(8,500))
            endpoint.transport = SimpleNamespace(sendto=lambda *args: None)
            remote = ('127.0.0.1',23456)
            try:
                endpoint.datagram_received(encode_datagram(5000,18001,100,0,0x22,1,0),remote)
                state = endpoint.sessions[(remote,5000,18001)]
                state.update(key_sent=True,auth_sent=True,room_sent=True,actor_uid=42)
                def heartbeat(now):
                    plain=(struct.pack('>IIHI',1,34,0x1f49,0)+struct.pack('>IIQ',0,0,42)
                           +struct.pack('>I',0x1f49)+bytes(4))
                    body=encrypt(plain,state['key'])
                    frame=struct.pack('>HHHHBIII',0x3366,10,10,0x4013,0,3,25,len(body))+bytes(4)+body
                    with patch('game_endpoint_probe_2022.time.monotonic',return_value=now), patch('game_endpoint_probe_2022.time.time',return_value=1791432000):
                        endpoint.datagram_received(encode_datagram(5000,18001,state['next_client'],0,0x18,1,0,frame),remote)
                sent=[]
                endpoint.send_application_batch=lambda d,r,s,packets:sent.extend(packets)
                heartbeat(101)
                self.assertFalse(state.get('environment_initialized'))
                state['weapon']=WeaponState(WeaponFixture(bytes(82),bytes(60)),42)
                endpoint.started=100
                heartbeat(102)
                self.assertEqual(sent[:2],EnvironmentFixture(8,500).messages(1791432000))
                self.assertTrue(state['environment_initialized'])
                # Обрабатываем обычные heartbeat, но начальные4816/10d0 повторно не уходят.
                sent.clear()
                heartbeat(103)
                self.assertFalse(any(command in (0x4816,0x10d0) for command,_ in sent))
            finally:
                capture.events.close()

    def test_scene_position_enables_standing_hazard_without_move_request(self):
        # Игрок не отправляет 2a: начальный 27 обязан дать миру координаты.
        fixture = WorldFixture(1000, 100, (0, 0, 100, 100), 50, 1, ())
        with tempfile.TemporaryDirectory() as temporary, contextlib.redirect_stdout(io.StringIO()):
            capture = Capture(Path(temporary)/'capture')
            endpoint = Endpoint(capture, True, auth=True, world_fixture=fixture)
            endpoint.transport = SimpleNamespace(sendto=lambda *args: None)
            remote = ('127.0.0.1', 23456)
            try:
                endpoint.datagram_received(encode_datagram(5000,18001,100,0,0x22,1,0), remote)
                state = endpoint.sessions[(remote,5000,18001)]
                state.update(key_sent=True, auth_sent=True, room_sent=True, actor_uid=42,
                             weapon=WeaponState(WeaponFixture(bytes(82),bytes(60)),42))
                position = struct.pack('>Q3i',42,10,20,30) + bytes(20)
                endpoint.register_fixture_entity(state,0x27,position)
                for now in (101,104):
                    plain = (struct.pack('>IIHI',1,34,0x1f49,0) + struct.pack('>IIQ',0,0,42)
                             + struct.pack('>I',0x1f49) + bytes(4))
                    body = encrypt(plain,state['key'])
                    frame = struct.pack('>HHHHBIII',0x3366,10,10,0x4013,0,3,25,len(body))+bytes(4)+body
                    with patch('game_endpoint_probe_2022.time.monotonic',return_value=now):
                        endpoint.datagram_received(encode_datagram(5000,18001,state['next_client'],0,0x18,1,0,frame),remote)
                self.assertEqual(state['world'].position,(10,20,30))
                self.assertEqual(state['world'].hp,850)
                # Последующий RPC собственной позиции также выключает опасный участок.
                endpoint.register_fixture_entity(state,0x27,struct.pack('>Q3i',42,1000,20,30)+bytes(20))
                self.assertFalse(state['world'].inside)
                endpoint.register_fixture_entity(state,0x27,struct.pack('>Q3i',99,10,20,30)+bytes(20))
                self.assertEqual(state['world'].position,(1000,20,30))
            finally:
                capture.events.close()

    def test_early_handoff_preserves_spawn_for_late_world_initialization(self):
        # Обрыв после27, но до первого heartbeat с созданием мира.
        endpoint, _, key, old, new, *_ = self.fixture()
        old.pop('world')
        old['scene_position'] = (10,20,30)
        old['weapon'] = WeaponState(WeaponFixture(bytes(82),bytes(60)),123)
        new.update(key=b'2'*16,key_sent=True,next_client=200)
        endpoint.handshake = endpoint.auth = True
        endpoint.started = 100
        endpoint.world_fixture = WorldFixture(1000,100,(0,0,100,100),50,1,())
        endpoint.transport = SimpleNamespace(sendto=lambda *args:None)
        self.assertTrue(endpoint.resume_gameplay(key,new,101))
        for now in (102,105):
            plain=(struct.pack('>IIHI',1,34,0x1f49,0)+struct.pack('>IIQ',0,0,123)
                   +struct.pack('>I',0x1f49)+bytes(4))
            body=encrypt(plain,new['key'])
            frame=struct.pack('>HHHHBIII',0x3366,10,10,0x4013,0,3,25,len(body))+bytes(4)+body
            with patch('game_endpoint_probe_2022.time.monotonic',return_value=now):
                endpoint.datagram_received(encode_datagram(key[1],key[2],new['next_client'],0,0x18,1,0,frame),key[0])
        self.assertEqual(new['world'].position,(10,20,30))
        self.assertTrue(new['world'].inside)
        self.assertEqual(new['world'].hp,850)
        self.assertEqual(new['key'],b'2'*16)

    def test_resume_rejects_unauthorized_different_identity_expired_or_unclosed(self):
        for field,value in [('auth_sent',False),('identity',b'other\0')]:
            endpoint,_,key,old,new,*_ = self.fixture();new[field]=value
            self.assertFalse(endpoint.resume_gameplay(key,new,101))
            self.assertIn('weapon',old)
        for now in (99,131):
            endpoint,_,key,old,new,*_ = self.fixture()
            self.assertFalse(endpoint.resume_gameplay(key,new,now))
        endpoint,_,key,old,new,*_ = self.fixture();old.pop('handoff_at')
        self.assertFalse(endpoint.resume_gameplay(key,new,101))
        endpoint,_,key,old,new,*_ = self.fixture()
        old['vehicles'] = SimpleNamespace(evacuation_finished=True)
        self.assertFalse(endpoint.resume_gameplay(key,new,101))

    def test_resume_rejects_different_host_destination_and_ambiguous_donor(self):
        for remote,destination in [(('127.0.0.2',2222),18001),(('127.0.0.1',2222),18002)]:
            endpoint,_,_,old,new,*_ = self.fixture()
            self.assertFalse(endpoint.resume_gameplay((remote,5001,destination),new,101))
        endpoint,_,key,old,new,*_ = self.fixture()
        endpoint.sessions[(('127.0.0.1',3333),5002,18001)] = dict(old)
        self.assertFalse(endpoint.resume_gameplay(key,new,101))
        self.assertIn('weapon',old)

    def test_close_then_wire_auth_resumes_and_relay_sync_does_not_reenter_room(self):
        endpoint, old_key, new_key, old, new, _, _, events = self.fixture()
        weapon = WeaponState(WeaponFixture(bytes(82),bytes(60)),123)
        weapon.clip, weapon.reserve, weapon.position = 1,3,(10,20,30)
        weapon.picked_loot.add(987)
        weapon.available_loot.add(988)
        world = WorldState(WorldFixture(700,100,(0,0,100,100),50,1,
                           ((0,1,encode_shrink(30,1,[24],[])),
                            (10,10,encode_shrink(60,10,[4],[24]))),
                            warnings=((15,60,encode_shrink_warning(60)),)),123,50)
        world.hp, world.position, world.initialized = 650,(10,20,30),True
        world.stage_index, world.warning_index, world.closed = 2,1,{24}
        template=struct.pack('>QiiiBBBIIIBI',123,1,2,3,4,5,6,7,0,8,9,10)
        old.update(weapon=weapon,world=world,scene_position=(10,20,30),scene_position_sync=template,
                   loot_spawned=True,loot_spawned_uids={988},winter_kit_initialized=True,
                   environment_initialized=True)
        endpoint.handshake = endpoint.auth = True
        endpoint.started = 0
        endpoint.scene_rules = [(0xdcd, [(0x7083,b'fixture')])]
        packets = []
        endpoint.transport = SimpleNamespace(sendto=lambda raw,remote:packets.append(parse_datagram(raw)))
        old.update(key=b'1'*16,key_sent=True,next_client=100)
        new.update(key=b'2'*16,key_sent=True,next_client=200,auth_sent=False)
        def wire_request(key, state, command, payload, common=False):
            if common:
                frame=struct.pack('>HHHHBIII',0x3366,10,10,command,0,3,21,0)
            else:
                plain=(struct.pack('>IIHI',1,30+len(payload),command,0)+
                       struct.pack('>IIQ',0,0,123)+struct.pack('>I',command)+payload)
                body=encrypt(plain,state['key'])
                frame=struct.pack('>HHHHBIII',0x3366,10,10,0x4013,0,3,25,len(body))+bytes(4)+body
            endpoint.datagram_received(encode_datagram(key[1],key[2],state['next_client'],0,0x18,1,0,frame),key[0])
        with patch('game_endpoint_probe_2022.time.monotonic',return_value=101):
            wire_request(old_key,old,0x5001,b'',True)
            self.assertEqual(old['handoff_at'],101)
            wire_request(new_key,new,0x406,struct.pack('>QI',1,2)+bytes(16)+struct.pack('>I',1))
            self.assertIs(new['world'],world)
            self.assertIs(new['weapon'],weapon)
            packets.clear()
            wire_request(new_key,new,0x7082,b'\1')
        frames=[parse_frame(p.data) for p in packets if p.data]
        messages=[m for f in frames for m in parse_applications(f,decrypt(f.body,new['key']),'server')]
        self.assertEqual([m.command for m in messages[:2]],[0x7083,0x27])
        self.assertEqual([m.command for m in messages[2:]],
                         [0x3e82] * 15 + [0x4a0, 0x6f5, 0x1069, 0x481, 0x481])
        self.assertEqual(struct.unpack_from('>I', messages[-1].payload, 8)[0], 24)
        self.assertEqual(struct.unpack_from('>I', next(m.payload for m in messages if m.command==0x1069), 11)[0], 650)
        self.assertEqual(messages[0].payload,b'fixture')
        position=messages[1].payload
        self.assertEqual(struct.unpack_from('>Q3i',position),(123,10,20,30))
        self.assertEqual(position[20:31],template[20:31])
        self.assertEqual(position[35:],template[35:])
        self.assertEqual(struct.unpack_from('>I',position,31)[0],2525)
        self.assertEqual(new['selection_deadline'],90)
        self.assertEqual((world.hp,world.started,world.stage_index,world.warning_index), (650,50,2,1))
        self.assertEqual(world.closed,{24})
        self.assertEqual((weapon.clip,weapon.reserve,weapon.position),(1,3,(10,20,30)))
        self.assertEqual(weapon.picked_loot,{987})
        self.assertEqual(weapon.available_loot,{988})
        self.assertEqual(new['scene_position'],(10,20,30))
        self.assertEqual(new['loot_spawned_uids'],{988})
        self.assertTrue(new['winter_kit_initialized'])
        self.assertTrue(new['environment_initialized'])
        self.assertEqual(new['key'],b'2'*16)
        self.assertNotEqual(new['seq'],old['seq'])
        self.assertFalse(old['room_sent'])
        # Повтор RELAY не телепортирует назад и не повторяет лут/инвентарь.
        world.update_position((90,80,70),102)
        packets.clear()
        with patch('game_endpoint_probe_2022.time.monotonic',return_value=103):
            wire_request(new_key,new,0x7082,b'\1')
        frames=[parse_frame(p.data) for p in packets if p.data]
        messages=[m for f in frames for m in parse_applications(f,decrypt(f.body,new['key']),'server')]
        self.assertEqual([m.command for m in messages],[0x7083])
        self.assertEqual(world.position,(90,80,70))

    def test_resume_without_position_template_does_not_invent_sync(self):
        endpoint,_,key,old,new,*_ = self.fixture()
        endpoint.transport=SimpleNamespace(sendto=lambda *args:None)
        self.assertTrue(endpoint.resume_gameplay(key,new,101))
        sent=[]
        endpoint.send_application=lambda *args:sent.append(args)
        endpoint.restore_resume_position(None,key[0],new)
        self.assertFalse(sent)
        self.assertFalse(new.get('resume_position_sent'))

    def test_resume_reconciles_lost_medical_delta_and_two_magazines_once(self):
        from medical_probe_2022 import MedicalState
        from weapon_probe_2022 import GunInstance
        endpoint, _, key, old, new, *_ = self.fixture()
        weapon = WeaponState(WeaponFixture(bytes(82), bytes(60), weapon_slots=2),123)
        weapon.guns[1].clip = 1
        weapon.guns[2] = GunInstance(10201,11,77)
        weapon.selected_slot = weapon.hand_slot = 2
        weapon.medical[70001] = 2
        world = SimpleNamespace(hp=550)
        medical = MedicalState(weapon, world)
        medical.completed_at = 99
        old.update(weapon=weapon, world=world, medical=medical)
        self.assertTrue(endpoint.resume_gameplay(key, new,101))
        sent=[]
        endpoint.send_application=lambda d,remote,state,command,payload:sent.append((command,payload))
        with patch('game_endpoint_probe_2022.time.monotonic',return_value=101):
            endpoint.restore_resume_inventory(None,key[0],new)
            count=len(sent)
            endpoint.restore_resume_inventory(None,key[0],new)
        self.assertEqual(len(sent),count)
        deltas={struct.unpack_from('>HB',body,1):body for command,body in sent if command==0x3e82}
        self.assertEqual(struct.unpack_from('>H',deltas[(3,2)],80)[0],2)
        self.assertEqual((len(deltas[(4,2)]),len(deltas[(5,2)])),(50,50))
        magazines=[struct.unpack('>QIII',body)[1:3] for command,body in sent if command==0x4a0]
        self.assertEqual(magazines,[(1,1),(2,11)])
        self.assertEqual(dict(sent)[0x1069],struct.pack('>QBBBII',123,0,1,0,550,1000))
        self.assertEqual(sent[-1],(0x2b,struct.pack('>QI',123,27)))
        self.assertEqual((world.hp,weapon.medical[70001],weapon.hand_slot),(550,2,2))
        self.assertNotIn(0x5fb,[command for command,body in sent])


class EndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_windows_startup_avoids_unavailable_signal_api(self):
        loop = asyncio.get_running_loop()
        with tempfile.TemporaryDirectory() as temporary, contextlib.redirect_stdout(io.StringIO()):
            output = Path(temporary)/'capture'
            args = SimpleNamespace(output=output, scene_rules=None,
                                   handshake=False, ident=False, grant=False, auth=False,
                                   room_template=None, scene_clock=False,
                                   selection_seconds=None, port=0, duration=0.01)
            with patch('game_endpoint_probe_2022.sys.platform', 'win32'), patch.object(
                    loop, 'add_signal_handler', side_effect=AssertionError('API Windows')) as register:
                await main(args)
                register.assert_not_called()
            self.assertIn('"kind": "stopped"', (output/'events.jsonl').read_text())

    async def test_synack_key_response_and_decrypted_request(self):
        await self.exercise(False)

    async def test_ident_and_grant_use_current_identity(self):
        await self.exercise(True)

    async def exercise(self,full):
        loop=asyncio.get_running_loop()
        with tempfile.TemporaryDirectory() as temporary, contextlib.redirect_stdout(io.StringIO()):
            capture=Capture(Path(temporary)/'capture')
            server,endpoint=await loop.create_datagram_endpoint(lambda:Endpoint(capture,True,full,full),local_addr=('127.0.0.1',0))
            client,protocol=await loop.create_datagram_endpoint(Client,local_addr=('127.0.0.1',0))
            address=server.get_extra_info('sockname')
            async def receive():return parse_datagram(await asyncio.wait_for(protocol.queue.get(),2))
            try:
                client.sendto(encode_datagram(5000,18001,0xffffffff,0,0x22,123,0),address)
                synack=await receive()
                self.assertEqual((synack.source_port,synack.destination_port,synack.acknowledgement,synack.flags,synack.echoed_clock),(18001,5000,0,0x12,123))
                name=b'00000000-0000-0000-0000-000000000001\0'
                extra=b'\2\3'+struct.pack('>IIHBI',10000,0,0,3,len(name))+name+bytes(16)
                frame=struct.pack('>HHHHBIII',0x3366,10,10,0x1001,0,1,21+len(extra),0)+extra
                client.sendto(encode_datagram(5000,18001,0,synack.sequence+1,0x18,124,synack.clock,frame),address)
                ack=await receive(); response=await receive()
                self.assertEqual(ack.acknowledgement,len(frame))
                keyframe=parse_frame(response.data);key=direct_session_key(keyframe)
                self.assertEqual((keyframe.command,keyframe.sequence),(0x1002,1))
                self.assertEqual(decrypt(keyframe.body,key),b'\0')
                plain=b'\0'*6;body=encrypt(plain,key)
                request=struct.pack('>HHHHBIII',0x3366,10,10,0x2001,0,2,21,len(body))+body
                client.sendto(encode_datagram(5000,18001,len(frame),response.sequence+len(response.data),0x18,125,response.clock,request),address)
                ack=await receive()
                self.assertEqual(ack.acknowledgement,len(frame)+len(request))
                if full:
                    ident=await receive();grant=await receive()
                    ident_frame=parse_frame(ident.data);grant_frame=parse_frame(grant.data)
                    self.assertEqual((ident_frame.command,grant_frame.command),(0x2002,0x6002))
                    ident_plain=decrypt(ident_frame.body,key)
                    self.assertEqual(ident_plain[7:7+len(name)],name)
                    self.assertEqual(len(ident_plain),70)
                    grant_plain=decrypt(grant_frame.body,key)
                    self.assertEqual(len(grant_plain),33)
                    self.assertEqual(struct.unpack_from('>I',grant_plain,29)[0],1024)
                await asyncio.sleep(0)

                files=list(capture.directory.glob('*-plaintext.bin'))
                self.assertEqual(len(files),1)
                self.assertEqual(files[0].read_bytes(),plain)
                # Повторные данные подтверждаются, но не обрабатываются второй раз.
                client.sendto(encode_datagram(5000,18001,len(frame),ack.sequence,0x18,126,ack.clock,request),address)
                await receive()
                self.assertEqual(len(list(capture.directory.glob('*-plaintext.bin'))),1)
            finally:
                client.close();server.close();capture.events.close()
                await asyncio.sleep(0)


class RoomEndpointTests(unittest.TestCase):
    def test_scene_schedule_supports_late_evacuation_and_bounds(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'rules.json'
            row = {'trigger': '0x1f49', 'after_selection': True,
                   'after_selection_delay_seconds': 240,
                   'responses': [{'command': '0x6589', 'payload_hex': '00'}]}
            path.write_text(json.dumps([row]))
            self.assertEqual(load_scene_rules(path)[0][3], 240)
            for value in (1801, -1, float('nan')):
                row['after_selection_delay_seconds'] = value
                path.write_text(json.dumps([row]))
                with self.assertRaises(ValueError):
                    load_scene_rules(path)

    def test_delayed_rule_waits_for_deadline_and_extra_margin(self):
        rules = [(0x1f49, [(0x2b, struct.pack('>QI', 0, 0), (0,))], True, 3)]
        class Transport:
            def __init__(self): self.sent = []
            def sendto(self, raw, remote): self.sent.append(parse_datagram(raw))
        with tempfile.TemporaryDirectory() as temporary, contextlib.redirect_stdout(io.StringIO()):
            capture = Capture(Path(temporary)/'capture')
            endpoint = Endpoint(capture, True, scene_rules=rules)
            endpoint.transport = Transport()
            remote = ('127.0.0.1', 23456)
            try:
                endpoint.datagram_received(encode_datagram(5000,18001,100,0,0x22,1,0), remote)
                state = endpoint.sessions[(remote,5000,18001)]
                state.update(key_sent=True, auth_sent=True, room_sent=True,
                             actor_uid=42, selection_deadline=10)
                def heartbeat(elapsed):
                    plain = (struct.pack('>IIHI',1,34,0x1f49,0) + struct.pack('>IIQ',0,0,42)
                             + struct.pack('>I',0x1f49) + bytes(4))
                    body = encrypt(plain, state['key'])
                    frame = struct.pack('>HHHHBIII',0x3366,10,10,0x4013,0,3,25,len(body)) + bytes(4) + body
                    endpoint.transport.sent.clear()
                    with patch('game_endpoint_probe_2022.time.monotonic', return_value=endpoint.started+elapsed):
                        endpoint.datagram_received(encode_datagram(5000,18001,state['next_client'],0,0x18,2,0,frame), remote)
                    return [packet for packet in endpoint.transport.sent if packet.data]
                self.assertEqual(heartbeat(12.99), [])
                packets = heartbeat(13)
                self.assertEqual(len(packets), 1)
                frame = parse_frame(packets[0].data)
                message = parse_applications(frame, decrypt(frame.body,state['key']), 'server')[0]
                self.assertEqual((message.command, struct.unpack('>QI',message.payload)), (0x2b,(42,0)))
                self.assertEqual(heartbeat(14), [])
            finally:
                capture.events.close()

    def test_batched_rule_preserves_order_patches_delay_and_single_delivery(self):
        class Transport:
            def __init__(self): self.sent = []
            def sendto(self, raw, remote): self.sent.append(parse_datagram(raw))
        with tempfile.TemporaryDirectory() as temporary, contextlib.redirect_stdout(io.StringIO()):
            directory = Path(temporary)
            config = directory / 'rules.json'
            row = {'trigger': '0x1f49', 'after_selection': True,
                   'after_selection_delay_seconds': 3, 'batch_responses': True,
                   'responses': [{'command': '0x2b', 'payload_hex': bytes(12).hex(),
                                  'actor_uid_offsets': [0]},
                                 {'command': '0x47a', 'payload_hex': '00000001'}]}
            config.write_text(json.dumps([row]))
            capture = Capture(directory/'capture')
            endpoint = Endpoint(capture, True, scene_rules=load_scene_rules(config))
            endpoint.transport = Transport()
            remote = ('127.0.0.1', 23456)
            try:
                endpoint.datagram_received(encode_datagram(5000,18001,100,0,0x22,1,0), remote)
                state = endpoint.sessions[(remote,5000,18001)]
                state.update(key_sent=True, auth_sent=True, room_sent=True,
                             actor_uid=42, selection_deadline=10)
                def heartbeat(elapsed):
                    plain = (struct.pack('>IIHI',1,34,0x1f49,0) + struct.pack('>IIQ',0,0,42)
                             + struct.pack('>I',0x1f49) + bytes(4))
                    body = encrypt(plain, state['key'])
                    frame = struct.pack('>HHHHBIII',0x3366,10,10,0x4013,0,3,25,len(body)) + bytes(4) + body
                    endpoint.transport.sent.clear()
                    with patch('game_endpoint_probe_2022.time.monotonic', return_value=endpoint.started+elapsed):
                        endpoint.datagram_received(encode_datagram(5000,18001,state['next_client'],0,0x18,2,0,frame), remote)
                    return [packet for packet in endpoint.transport.sent if packet.data]
                self.assertEqual(heartbeat(12.99), [])
                packets = heartbeat(13)
                self.assertEqual(len(packets), 1)
                frame = parse_frame(packets[0].data)
                messages = parse_applications(frame, decrypt(frame.body,state['key']), 'server')
                self.assertEqual([m.command for m in messages], [0x2b, 0x47a])
                self.assertEqual(struct.unpack('>QI',messages[0].payload), (42,0))
                self.assertEqual(messages[1].payload, bytes.fromhex('00000001'))
                self.assertEqual(heartbeat(14), [])
                for invalid in ('true', 1):
                    row['batch_responses'] = invalid
                    config.write_text(json.dumps([row]))
                    with self.assertRaises(ValueError): load_scene_rules(config)
                row['batch_responses'] = True
                row['responses'] = [{'command': '0x47a', 'payload_hex': ''}] * 65
                config.write_text(json.dumps([row]))
                with self.assertRaises(ValueError): load_scene_rules(config)
                row['responses'] = [{'command': '0x47a', 'payload_hex': bytes(12000).hex()}] * 3
                config.write_text(json.dumps([row]))
                with self.assertRaises(ValueError): load_scene_rules(config)
            finally:
                capture.events.close()

    def test_auth_guard_room_segmentation_and_one_time_scene_rule(self):
        self.exercise(None)

    def test_selection_timer_uses_current_clock_and_stable_deadline(self):
        self.exercise(10)

    def exercise(self, selection_seconds):
        class Transport:
            def __init__(self): self.sent=[]
            def sendto(self, raw, remote): self.sent.append(parse_datagram(raw))

        with tempfile.TemporaryDirectory() as temporary, contextlib.redirect_stdout(io.StringIO()):
            directory=Path(temporary)
            template=directory/'room.bin';template.write_bytes(room_fixture())
            capture=Capture(directory/'capture')
            rules=[(0xdcd,[(0x47a,bytes(4)),(0x27,bytes(40),(0,),(31,)),(0x2b,struct.pack('>QI',1,43),(0,))])]
            if selection_seconds:
                rules.append((0x1f49,[(0x2b,struct.pack('>QI',0,0),(0,))],True))
            endpoint=Endpoint(capture,True,True,True,True,template,rules,True,selection_seconds)
            endpoint.transport=Transport();remote=('127.0.0.1',23456)
            try:
                endpoint.datagram_received(encode_datagram(5000,18001,100,0,0x22,1,0),remote)
                state=endpoint.sessions[(remote,5000,18001)]
                state['key_sent']=True
                def request(code,payload):
                    plain=(struct.pack('>IIHI',1,30+len(payload),code,0)+
                           struct.pack('>IIQ',0,0,42)+struct.pack('>I',code)+payload)
                    body=encrypt(plain,state['key']);extra=bytes(4)
                    frame=struct.pack('>HHHHBIII',0x3366,10,10,0x4013,0,3,25,len(body))+extra+body
                    endpoint.transport.sent.clear()
                    endpoint.datagram_received(encode_datagram(5000,18001,state['next_client'],0,0x18,2,0,frame),remote)
                    return [p for p in endpoint.transport.sent if p.data]
                # Несогласованный ConnectKey запрещает успешный AUTH.
                self.assertEqual(request(0x406,struct.pack('>QI',1,2)+b'x'*16+struct.pack('>I',1)),[])
                self.assertFalse(state['auth_sent'])
                frames=request(0x406,struct.pack('>QI',1,2)+bytes(16)+struct.pack('>I',1))
                frame=parse_frame(frames[0].data)
                self.assertEqual(parse_applications(frame,decrypt(frame.body,state['key']),'server')[0].command,0x407)
                frames=request(0xdce,struct.pack('>QIQ',123,2,1))
                self.assertEqual([len(p.data) for p in frames],[500,500,81])
                for previous,current in zip(frames,frames[1:]):
                    self.assertEqual(current.sequence,previous.sequence+len(previous.data))
                frame=parse_frame(b''.join(p.data for p in frames))
                message=parse_applications(frame,decrypt(frame.body,state['key']),'server')[0]
                fields={f['name']:f['value'] for f in decode_enter_room_response(message.payload)['fields']}
                self.assertEqual(message.command,0xdcf)
                self.assertEqual((fields['profile.base.m000'],fields['profile.base.m00c']),(123,42))
                self.assertEqual(request(0xdce,struct.pack('>QIQ',123,2,1)),[])
                frames=request(0xdcd,bytes(4))
                messages=[]
                for packet in frames:
                    frame=parse_frame(packet.data)
                    messages.extend(parse_applications(frame,decrypt(frame.body,state['key']),'server'))
                expected=[0x1f5f,0x1f57]+([0x486,0x47a,0x482] if selection_seconds else [])+[0x47a,0x27,0x2b]
                self.assertEqual([m.command for m in messages],expected)
                self.assertEqual(struct.unpack('>QI',messages[-1].payload),(42,43))
                self.assertEqual(struct.unpack_from('>Q',messages[-2].payload)[0],42)
                self.assertLessEqual(abs(struct.unpack_from('>I',messages[-2].payload,31)[0]-struct.unpack('>4I',messages[1].payload)[0]),1)
                if selection_seconds:
                    packets=request(0x483,b'\xe8')
                    frame=parse_frame(packets[0].data)
                    timer=parse_applications(frame,decrypt(frame.body,state['key']),'server')[0]
                    self.assertEqual(timer.command,0x484)
                    tick,fraction=struct.unpack('>II',timer.payload)
                    self.assertLess(fraction,40)
                    initial_tick=struct.unpack('>4I',messages[1].payload)[0]
                    self.assertLessEqual(abs(tick-initial_tick-selection_seconds*25),1)
                    packets=request(0x483,b'\0');frame=parse_frame(packets[0].data)
                    self.assertEqual(parse_applications(frame,decrypt(frame.body,state['key']),'server')[0].payload,timer.payload)
                self.assertEqual(struct.unpack('>6I',messages[0].payload)[-1],4)
                self.assertEqual(struct.unpack('>4I',messages[1].payload)[2],40)
                self.assertEqual(len(request(0x1f49,bytes(4))),2)
                if selection_seconds:
                    with patch('game_endpoint_probe_2022.time.monotonic',return_value=endpoint.started+selection_seconds+20):
                        packets=request(0x1f49,bytes(4))
                        self.assertEqual(len(packets),3)
                        frame=parse_frame(packets[-1].data)
                        status=parse_applications(frame,decrypt(frame.body,state['key']),'server')[0]
                        self.assertEqual((status.command,struct.unpack('>QI',status.payload)),(0x2b,(42,0)))
                        self.assertEqual(len(request(0x1f49,bytes(4))),2)
                self.assertEqual(request(0xdcd,bytes(4)),[])
            finally:
                capture.events.close()


class WorldResumeSnapshotTests(unittest.TestCase):
    def test_resume_sends_current_stage_once_with_original_world_clock(self):
        import tempfile
        from world_probe_2022 import encode_shrink
        with tempfile.TemporaryDirectory() as directory:
            capture=Capture(Path(directory)/'capture')
            try:
                endpoint=Endpoint(capture,True,auth=True)
                fixture=WorldFixture(1000,100,(0,0,1,1),50,1,
                                     ((0,1,encode_shrink(90,1,[24],[])),
                                      (90,10,encode_shrink(60,10,[4],[24]))))
                world=WorldState(fixture,42,100)
                world.poll(190)
                state={'world':world}
                sent=[]
                endpoint.send_application=lambda d,remote,state,code,body:sent.append((code,body))
                with patch('game_endpoint_probe_2022.time.monotonic',return_value=211.5):
                    endpoint.restore_resume_world(None,('127.0.0.1',1),state)
                    endpoint.restore_resume_world(None,('127.0.0.1',1),state)
                self.assertEqual(len(sent),1)
                self.assertEqual(sent[0][0],0x481)
                self.assertEqual(struct.unpack_from('>f',sent[0][1],4)[0],21.5)
                self.assertEqual((world.started,world.stage_index),(100,2))
            finally:capture.events.close()


class EvacuationIdentityTests(unittest.TestCase):
    def test_local_profile_name_and_death_are_bound_to_current_actor(self):
        with tempfile.TemporaryDirectory() as tmp:
            room = room_fixture()
            fields = {f['name']: f for f in decode_enter_room_response(room)['fields']}
            field = fields['profile.base.m014']
            name = 'Зима'.encode('utf-8') + b'\0'
            at = field['offset']
            room = room[:at-4] + struct.pack('>I', len(name)) + name + room[at+field['length']:]
            path = Path(tmp)/'room.bin'; path.write_bytes(room)
            capture = Capture(Path(tmp)/'capture')
            try:
                endpoint = Endpoint(capture, room_template=path, evacuation_delay=8)
                state = dict(actor_uid=42, room_uid=1)
                body = bytearray(104)
                struct.pack_into('>QIIIiii', body, 0, 789, 6, 9, 100, 10, 20, 1300)
                endpoint.register_fixture_entity(state, 0x654b, body)
                self.assertEqual(state['vehicles'].survivor_name, 'Зима')
                state['vehicles'].handle(0x6541, struct.pack('>QI', 789, 1), now=100)
                state['world'] = SimpleNamespace(dead=True)
                endpoint.cancel_dead_actions(state, ('127.0.0.1', 12345))
                self.assertEqual(state['vehicles'].poll(108), ([], []))
            finally:
                capture.events.close()
