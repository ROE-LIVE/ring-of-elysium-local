"""Экспериментальный loopback UDP endpoint: SYN/ACK и захват TGCP, без игры."""
import argparse
import asyncio
import json
from itertools import groupby
import os
from pathlib import Path
import signal
import struct
import sys
import time
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'tools'))
from roe_tgcp_2023 import parse_datagram, packet_hash, parse_frame, parse_applications
from roe_scene_2023 import decode_conn_auth_request, decode_enter_room_request
from roe_room_2023 import decode_enter_room_response
from room_cosmetics_2022 import apply_room_cosmetics
from roe_protocol_2022 import encrypt, decrypt
from listener import Capture
from weapon_probe_2022 import WeaponFixture, WeaponState
from medical_probe_2022 import MedicalState
from live_scene_probe_2022 import LiveSceneCommands
from door_state_2022 import DoorFixture, DoorState
from breakable_state_2022 import BreakableFixture, BreakableState
from world_probe_2022 import WorldFixture, WorldState, encode_health
from vehicle_probe_2022 import VehicleState, EvacuationUIFixture, survivor_event
from match_statistics_2022 import MatchStatistics
from match_result_2022 import MatchEndPolicy
from peer_avatar_2022 import PeerAvatarRooms
from shared_loot_2022 import SharedLootRooms
from peer_lifecycle_2022 import expired_members
from peer_spectator_2022 import PeerSpectators
from shared_evacuation_2022 import SharedEvacuationRooms
from shared_vehicle_2022 import SharedVehicleRooms
from shared_combat_2022 import SharedCombatRooms
from actor_probe_2022 import ActorFixture, ActorState, segment_box_entry
from target_roster_2022 import TargetRoster, load_actor_fixtures
from bot_controller_2022 import BotController
from state_scene_actions_2022 import apply_state_action
from death_parcel_2022 import DeathParcelState, target_inventory
from throwable_actions_2022 import ThrowableActions, PROFILES as THROWABLE_EFFECT_PROFILES
from parcel_catalog_2022 import load_parcel_fixture, make_parcel_state
from environment_probe_2022 import EnvironmentFixture
from loot_catalog_2022 import LootCatalog, LootCatalogState
from roe_scene_2023 import decode_move_request
from reliable_udp_2022 import ReliableSender, ReliableReceiver, FrameStream
from movement_validation_2022 import MovementState
from winter_selection_2022 import default_choice, selected_fixture, choose as choose_winter_kit, load_spawn_points, choose_cell


def encode_datagram(source, destination, sequence, acknowledgement, flags, clock, echoed, data=b''):
    header = struct.pack('>HHIIBBH', source, destination, sequence & 0xffffffff,
                         acknowledgement & 0xffffffff, 0x50, flags, 65535)
    raw = header + struct.pack('<HH', echoed & 0xffff, clock & 0xffff) + data
    return raw + struct.pack('<I', packet_hash(raw))


def load_scene_rules(path):
    """Явные одноразовые ответы после входа в комнату, без скрытых полей."""
    if path is None:
        return []
    path = Path(path)
    rules = []
    for rule in json.loads(path.read_text()):
        trigger = int(str(rule['trigger']), 0)
        responses = []
        for response in rule['responses']:
            code = int(str(response['command']), 0)
            if ('payload_file' in response) == ('payload_hex' in response):
                raise ValueError('Нужен ровно один источник payload')
            payload = ((path.parent / response['payload_file']).read_bytes()
                       if 'payload_file' in response else bytes.fromhex(response['payload_hex']))
            if not 0 <= code <= 65535 or len(payload) > 16384:
                raise ValueError('Команда или размер ответа вне допустимых границ')
            # BC_STATUS и сходные ответы адресованы actor из текущей комнаты.
            offsets = response.get('actor_uid_offsets', [])
            if (not isinstance(offsets, list) or any(type(at) is not int or at < 0 or at + 8 > len(payload) for at in offsets)
                    or len(set(offsets)) != len(offsets)):
                raise ValueError('Неверные смещения actor_uid_offsets')
            tick_offsets = response.get('clock_tick_offsets', [])
            if (not isinstance(tick_offsets, list) or any(type(at) is not int or at < 0 or at + 4 > len(payload) for at in tick_offsets)
                    or len(set(tick_offsets)) != len(tick_offsets)):
                raise ValueError('Неверные смещения clock_tick_offsets')
            fixed_position = response.get('fixed_position', False)
            if type(fixed_position) is not bool or (fixed_position and (code != 0x27 or len(payload) != 40)):
                raise ValueError('fixed_position: boolean только для позиции0x27/40')
            if fixed_position:
                responses.append((code, payload, tuple(offsets), tuple(tick_offsets), True))
            elif tick_offsets:
                responses.append((code,payload,tuple(offsets),tuple(tick_offsets)))
            else:
                responses.append((code, payload, tuple(offsets)) if offsets else (code, payload))
        if not 0 <= trigger <= 65535:
            raise ValueError('Команда trigger вне допустимых границ')
        after_selection = rule.get('after_selection', False)
        if type(after_selection) is not bool:
            raise ValueError('after_selection должен быть boolean')
        delay = rule.get('after_selection_delay_seconds', 0)
        if (type(delay) not in (int, float) or not 0 <= delay <= 1800
                or (delay and not after_selection)):
            raise ValueError('Задержка 0..1800 секунд требует after_selection')
        batch = rule.get('batch_responses', False)
        if type(batch) is not bool:
            raise ValueError('batch_responses должен быть boolean')
        if batch and (len(responses) > 64 or sum(len(r[1])+10 for r in responses) > 32768):
            raise ValueError('Пакетное правило превышает 64 сообщения или 32768 байт')
        rules.append((trigger, responses, after_selection, delay, True) if batch else
                     ((trigger, responses, True, delay) if delay else
                      ((trigger, responses, True) if after_selection else (trigger, responses))))
    return rules


class Endpoint(asyncio.DatagramProtocol):
    def __init__(self, capture, handshake=False, ident=False, grant=False, auth=False, room_template=None, scene_rules=None, scene_clock=False, selection_seconds=None, weapon_fixture=None, live_commands=None, world_fixture=None, actor_fixture=None, evacuation_delay=None, parcel_fixture=None, evacuation_result_fixture=None, loot_catalog=None, environment_fixture=None, reliable_udp=False, idle_handoff=False, diagnostic_vehicle_pellet_damage=None, peer_avatar_fixture=None, shared_ground_loot=False, shared_world_clock=False, shared_peer_health=False, peer_avatar_trajectories=False, peer_spectator=False, shared_evacuation=False, shared_vehicles=False, peer_equipment=False, peer_pellet_damage=None, shared_death_loot=False, door_fixture=None, breakable_fixture=None):
        self.capture = capture
        self.breakable_fixture = breakable_fixture
        if breakable_fixture and (peer_avatar_fixture or shared_ground_loot):
            raise ValueError('breakable-config пока требует одиночный профиль')
        self.door_fixture = door_fixture
        if door_fixture and (peer_avatar_fixture or shared_ground_loot):
            raise ValueError('Текущие двери требуют одиночный профиль; общий реестр ещё не реализован')
        self.sessions = {}
        if shared_peer_health and (not peer_avatar_fixture or not world_fixture or not shared_ground_loot):
            raise ValueError('ОбщиеHP требуют peer-avatar-config/world-config/shared-ground-loot')
        if peer_avatar_trajectories and (not peer_avatar_fixture or not scene_clock):
            raise ValueError('Траектории требуют peer-avatar-config и scene-clock')
        if peer_equipment and not shared_peer_health:
            raise ValueError('peer-equipment требует shared-peer-health')
        self.peer_avatars = PeerAvatarRooms(peer_avatar_fixture, shared_peer_health, peer_avatar_trajectories, peer_equipment) if peer_avatar_fixture else None
        if peer_pellet_damage is not None and (not shared_peer_health or not world_fixture
                or not world_fixture.death_on_zero or world_fixture.hp_floor != 0):
            raise ValueError('peer-pellet-damage требует shared-peer-health/death_on_zero/hp_floor0')
        self.peer_combat = SharedCombatRooms(self.peer_avatars,peer_pellet_damage) if peer_pellet_damage is not None else None
        if peer_spectator and not shared_peer_health:
            raise ValueError('Наблюдение требует shared-peer-health')
        self.peer_spectators = PeerSpectators() if peer_spectator else None
        if shared_evacuation and (not shared_peer_health or not evacuation_result_fixture
                or not evacuation_result_fixture.session_statistics
                or evacuation_result_fixture.result_on_death
                or evacuation_result_fixture.timeout_seconds is not None
                or evacuation_result_fixture.diagnostic_departure_seconds):
            raise ValueError('Общая эвакуация требует shared-peer-health и session result без singleton policy/отлёта')
        self.shared_evacuation = SharedEvacuationRooms(evacuation_delay) if shared_evacuation else None
        if shared_vehicles and not shared_peer_health:
            raise ValueError('Общий транспорт требует shared-peer-health')
        self.shared_vehicles = SharedVehicleRooms() if shared_vehicles else None
        self.peer_timer = None
        if shared_ground_loot and (not weapon_fixture or loot_catalog or parcel_fixture):
            raise ValueError('Общий наземный лут требует weapon-config без loot-catalog/parcel-config')
        if shared_death_loot and not shared_peer_health:
            raise ValueError('shared-death-loot требует shared-peer-health')
        if shared_death_loot and actor_fixture:
            raise ValueError('Общий лут погибших пока не поддерживает отдельную мишень каждого клиента')
        self.shared_loot = SharedLootRooms(weapon_fixture,shared_death_loot) if shared_ground_loot else None
        if shared_world_clock and (not self.shared_loot or not world_fixture):
            raise ValueError('Общий календарь требует shared-ground-loot и world-config')
        self.shared_world_clock = shared_world_clock
        self.reliable_udp = reliable_udp
        self.idle_handoff = idle_handoff
        self.diagnostic_vehicle_pellet_damage = diagnostic_vehicle_pellet_damage
        self.retry_timer = None
        self.match_timer = None
        self.match_timers_enabled = False
        self.started = time.monotonic()
        self.handshake = handshake
        self.ident = ident
        self.grant = grant
        self.auth = auth
        self.scene_rules = scene_rules or []
        self.scene_clock = scene_clock
        self.selection_seconds = selection_seconds
        self.weapon_fixture = weapon_fixture
        self.live_commands = live_commands
        # ID команды действует один раз для actor в пределах этого endpoint,
        # включая последующие матчи; файл управления при finish не обнуляется.
        self.live_sent_by_actor = {}
        self.world_fixture = world_fixture
        self.actor_fixtures = (tuple(actor_fixture) if isinstance(actor_fixture, (tuple, list))
                               else (actor_fixture,) if actor_fixture else ())
        if (len(self.actor_fixtures) > 10
                or len({f.uid for f in self.actor_fixtures}) != len(self.actor_fixtures)):
            raise ValueError('Нужны не более10 уникальных мишеней')
        if (len(self.actor_fixtures) > 1
                and any(f.attack or f.behavior or f.speed or f.ground_route
                        or len(f.waypoints) != 1 for f in self.actor_fixtures)):
            raise ValueError('Несколько мишеней пока поддерживают только пассивный режим')
        if any(f.behavior for f in self.actor_fixtures) and (shared_ground_loot or world_fixture is None):
            raise ValueError("BOT05 controller требует одиночный world, без shared-ground-loot")
        self.actor_fixture = self.actor_fixtures[0] if self.actor_fixtures else None
        self.evacuation_delay = evacuation_delay
        self.parcel_fixture = parcel_fixture
        self.environment_fixture = environment_fixture
        self.evacuation_result_fixture = evacuation_result_fixture
        self.loot_catalog = loot_catalog
        self.room_template = Path(room_template).read_bytes() if room_template else None
        self.room_fields = {f['name']:f for f in decode_enter_room_response(self.room_template)['fields']} if self.room_template else None
        # Только публичное имя собственного локального профиля; не журналировать профиль.
        nickname = self.room_fields.get('profile.base.m014') if self.room_fields else None
        self.room_display_name = (nickname['value'][:-1].decode('utf-8') if nickname else '') or 'LOCAL'
        map_field = self.room_fields.get('profile.base.m644') if self.room_fields else None
        self.spawn_points = (load_spawn_points() if map_field and
            struct.unpack_from('>I', self.room_template, map_field['offset'])[0] == 16010 else None)

    def connection_made(self, transport):
        self.transport = transport
        if self.peer_avatars or self.shared_loot:
            self.peer_timer = asyncio.get_running_loop().call_later(1, self.poll_peer_rooms)
        if self.reliable_udp:
            self.retry_timer = asyncio.get_running_loop().call_later(.05, self.retry_pending)
        fixture = self.evacuation_result_fixture
        if fixture and (fixture.result_on_death or fixture.timeout_seconds is not None):
            self.match_timers_enabled = True
            self.match_timer = asyncio.get_running_loop().call_later(.1, self.poll_match_ends)
        self.capture.record('ready', transport='udp', local=transport.get_extra_info('sockname'),
                            handshake=self.handshake, ident=self.ident, grant=self.grant, auth=self.auth,
                            room_template=bool(self.room_template), scene_rules=len(self.scene_rules), scene_clock=self.scene_clock,
                            selection_seconds=self.selection_seconds, weapon_probe=bool(self.weapon_fixture),
                            implementation_revision='20261015-starter-v1',
                            weapon_slots=getattr(self.weapon_fixture, 'weapon_slots', None),
                            winter_starter_inventory=getattr(self.weapon_fixture, 'winter_starter_inventory', False))
        if self.loot_catalog:
            self.capture.record('loot_catalog_ready', count=len(self.loot_catalog.items),
                                radius_cm=self.loot_catalog.radius, synthetic=True,
                                original_aoi_verified=False)

    def datagram_received(self, raw, remote):
        self.capture.record('recv', raw, transport='udp', remote=remote)
        try:
            d = parse_datagram(raw)
            identity = (remote, d.source_port, d.destination_port)
            if d.flags & 2:
                previous = self.sessions.get(identity)
                if (self.reliable_udp and previous is not None
                        and previous.get('client_isn') == d.sequence):
                    # Повтор SYN не заменяет ключ и игровое состояние.
                    sender = previous['sender']
                    packet = sender.pending.get(0x10000000)
                    if packet is not None:
                        self.transport.sendto(packet.raw, remote)
                        self.capture.record('udp_syn_retry', remote=remote)
                    return
                self.sessions[identity] = {'seq':0x10000000, 'next_client':(d.sequence+1)&0xffffffff, 'key':os.urandom(16), 'key_sent':False, 'ident_sent':False, 'identity':None, 'auth_sent':False, 'frame_seq':3, 'room_sent':False, 'scene_rules_sent':set(), 'clock_started':False}
                if self.reliable_udp:
                    self.sessions[identity].update(client_isn=d.sequence,
                                                   sender=ReliableSender(0x10000000),
                                                   receiver=ReliableReceiver((d.sequence+1)&0xffffffff),
                                                   incoming_frames=FrameStream())
                self.send(d, remote, self.sessions[identity]['seq'], self.sessions[identity]['next_client'], 0x12)
                return
            state = self.sessions.get(identity)
            if state is None:
                self.capture.record('ignored', reason='Нет SYN', remote=remote)
                return
            state['peer_avatar_anchor'] = (d,remote,time.monotonic())
            # Публичные поля маршрута последнего UDP; без ключа/identity/body.
            state['transport_header'] = SimpleNamespace(source_port=d.source_port,
                destination_port=d.destination_port, clock=d.clock)
            if self.reliable_udp and d.flags & 0x10:
                state['sender'].acknowledge(d.acknowledgement)
            if state.get('transport_retired'):
                if d.data:
                    self.send(d, remote, state['seq']+1, state['next_client'], 0x10)
                return
            if d.data:
                if self.reliable_udp:
                    try:
                        contiguous = state['receiver'].accept(d.sequence, d.data)
                    except ValueError as error:
                        self.capture.record('udp_receive_rejected', remote=remote, error=str(error))
                        contiguous = b''
                    state['next_client'] = state['receiver'].next
                    self.send(d, remote, state['seq']+1, state['next_client'], 0x10)
                    try:
                        frames = state['incoming_frames'].feed(contiguous)
                    except ValueError as error:
                        self.capture.record('udp_stream_rejected', remote=remote, error=str(error))
                        return
                    for frame_bytes in frames:
                        self.process_frame(d, remote, state, frame_bytes, True)
                    return
                fresh = d.sequence == state['next_client']
                if fresh:
                    state['next_client'] = (d.sequence + len(d.data)) & 0xffffffff
                self.send(d, remote, state['seq']+1, state['next_client'], 0x10)
                self.process_frame(d, remote, state, d.data, fresh)
        except ValueError as error:
            self.capture.record('parse_error', error=str(error), remote=remote)

    def process_frame(self, d, remote, state, frame_bytes, fresh):
        identity = (remote, d.source_port, d.destination_port)
        try:
            frame = parse_frame(frame_bytes)
            self.capture.record('tgcp_frame', remote=remote, command=hex(frame.command),
                                version=frame.version, command_version=frame.command_version,
                                flag=frame.flag, frame_sequence=frame.sequence,
                                extra_length=len(frame.extra_header), body_length=len(frame.body))
            if fresh and frame.command == 0x5001 and state['auth_sent'] and state['room_sent']:
                # Длинный зимний опыт: клиент закрывает TGCP и повторяет
                # AUTH/RELAY_ENTER_SCENE без повторного ENTER_ROOM.
                # Разрешение переноса ограничено30с и текущим identity.
                state['handoff_at'] = time.monotonic()
                self.capture.record('gameplay_handoff_pending', synthetic=True, remote=remote)
            if self.handshake and fresh and frame.command == 0x1001 and not state['key_sent']:
                # Наблюдаемая ветка клиента 2022: identity selector=3.
                extra_in = frame.extra_header
                if len(extra_in)>=17 and extra_in[12]==3:
                    length=struct.unpack_from('>I',extra_in,13)[0]
                    if 1<=length<=256 and 17+length<=len(extra_in):
                        identity_in=extra_in[17:17+length]
                        if identity_in[-1:]==b'\0' and b'\0' not in identity_in[:-1]:
                            state['identity']=identity_in
                # Наблюдаемая официальная ветка selector=2, прямой ключ.
                extra = b'\x02\x10' + state['key'] + bytes.fromhex('010000004000000000')
                body = encrypt(b'\0',state['key'])
                response = struct.pack('>HHHHBIII',0x3366,frame.version,frame.command_version,
                                       0x1002,1,frame.sequence,21+len(extra),len(body))+extra+body
                self.send(d,remote,state['seq']+1,state['next_client'],0x18,response)
                state['seq'] += len(response)
                state['key_sent'] = True
                keyfile = self.capture.directory/f"session-{d.source_port}.key"
                keyfile.write_bytes(state['key']);keyfile.chmod(0o600)
                self.capture.record('key_response', command='0x1002', synthetic=True, remote=remote)
            elif self.handshake and fresh and state['key_sent'] and frame.body:
                try:
                    plain = decrypt(frame.body,state['key'])
                    self.capture.record('plaintext',plain,command=hex(frame.command),remote=remote)
                    if self.ident and frame.command==0x2001 and not state['ident_sent']:
                        name=state['identity']
                        if name is None:
                            raise ValueError('Не разобран identity из 1001; IDENT запрещён')
                        # Decoder 141a48570: результат, identity, U64 и три bounded byte-array.
                        # Неизвестные слова выставлены явно в ноль, массивы пусты.
                        reply=(struct.pack('>HB I',0,3,len(name))+name+
                               struct.pack('>QHHIHIHH',0,0,0,0,0,0,0,0))
                        self.send_frame(d,remote,state,0x2002,frame.sequence,reply)
                        state['ident_sent']=True
                        self.capture.record('ident_response',synthetic=True,remote=remote)
                        if self.grant:
                            # Decoder 141a49710: ident20, U64, U8, U32 maximum.
                            grant=struct.pack('>I',1)+bytes(16)+struct.pack('>QBI',0,0,1024)
                            self.send_frame(d,remote,state,0x6002,frame.sequence+1,grant)
                            self.capture.record('grant_response',synthetic=True,remote=remote)
                    if frame.command==0x4013:
                        messages = parse_applications(frame,plain,'client')
                        state['last_application_at'] = time.monotonic()
                        for message in messages:
                            self.capture.record('application',command=hex(message.command),body_length=len(message.payload),
                                                application_sequence=message.sequence, stamp=message.stamp, remote=remote)
                            if self.auth and message.command==0x406 and not state['auth_sent']:
                                auth=decode_conn_auth_request(message.payload)
                                if auth['word_1']!=1 or auth['token']!=bytes(16):
                                    raise ValueError('AUTH отличается от явно выданных synthetic ident/token')
                                self.send_application(d,remote,state,0x407,struct.pack('>I',0))
                                state['auth_sent']=True
                                self.capture.record('auth_response',synthetic=True,remote=remote)
                                self.resume_gameplay(identity, state, time.monotonic())
                            elif message.command == 0x7082:
                                if ((self.idle_handoff or self.peer_avatars or self.shared_loot)
                                        and not state.get('gameplay_resumed')
                                        and message.payload == b'\0'):
                                    # Cold78: новый authenticated RELAY без доставленного5001.
                                    # Actor UID берётся из проверенного C2S header, не из имени.
                                    relay_actor_uid = struct.unpack_from('>Q', message.decoded, 22)[0]
                                    resumed = self.resume_gameplay(identity, state, time.monotonic(), relay_actor_uid)
                                    if not resumed:
                                        self.resume_finished_result(identity, d, state,
                                                                    time.monotonic(), relay_actor_uid)
                                # Проверенный SCENE_SYNC и однократный27 текущей позиции;
                                # не создаём заново мир/оружие/loot и таймеры.
                                if state.get('gameplay_resumed'):
                                    for rule in self.scene_rules:
                                        if rule[0] == 0xdcd:
                                            for response in rule[1]:
                                                if response[0] == 0x7083:
                                                    self.send_application(d, remote, state, 0x7083, response[1])
                                    self.restore_resume_position(d, remote, state)
                                    self.restore_resume_inventory(d, remote, state)
                                    self.restore_resume_world(d, remote, state)
                            elif message.command==0xdce:
                                room=decode_enter_room_request(message.payload)
                                self.capture.record('enter_room_request',first_identifier=room['first_identifier'],word=room['word'],second_identifier=room['second_identifier'],remote=remote)
                                if self.room_template and state['auth_sent'] and not state['room_sent']:
                                    data=bytearray(self.room_template)
                                    uid=struct.unpack_from('>Q',message.decoded,22)[0]
                                    state['actor_uid']=uid
                                    state['room_uid']=room['second_identifier']
                                    state['actor_display_name']=self.room_display_name
                                    updates={'result':0,'m004':1,'m00c':uid,'m014':1,'m01c':room['second_identifier'],
                                             'profile.base.m000':room['first_identifier'],'profile.base.m00c':uid}
                                    for name,value in updates.items():
                                        f=self.room_fields[name]
                                        struct.pack_into('>'+f['type'],data,f['offset'],value)
                                    if self.weapon_fixture and self.weapon_fixture.cosmetics_config_file:
                                        data, appearance = apply_room_cosmetics(data,self.weapon_fixture.cosmetics_config_file)
                                        self.capture.record('room_cosmetics_applied',synthetic=True,**appearance)
                                    self.send_application(d,remote,state,0xdcf,bytes(data))
                                    state['room_sent']=True
                                    self.capture.record('enter_room_response',synthetic=True,body_length=len(data),remote=remote)
                            elif self.auth and state['auth_sent'] and message.command==0x1f49 and len(message.payload)==4:
                                self.send_application(d,remote,state,0x1f4a,message.payload)
                                if state['clock_started']:
                                    self.send_clock(d,remote,state)
                            if state['auth_sent'] and state['room_sent']:
                                self.cancel_dead_actions(state, remote)
                                if self.check_match_end(d, remote, state, time.monotonic()):
                                    continue
                                if self.peer_spectators and message.command == 0x6fbc:
                                    self.emit_peer_avatars(*self.peer_spectators.relay_camera(
                                        self.peer_avatars,state,message.payload,time.monotonic()))
                                if not self.accept_living_action(state, message, remote):
                                    continue
                                if message.command == 0x2a and not self.accept_movement(d, remote, state, message.payload):
                                    continue
                                if ('weapon' in state and message.command in (0x49e, 0x49c, 0x11da, 0x3b63, 0x3e80, 0x1004, 0x1007, 0x6f57)
                                        and not self.accept_inventory_action(state, message, remote)):
                                    continue
                                if self.live_commands and message.command == 0x1f49:
                                    control = self.live_control_for(state)
                                    elapsed = time.monotonic() - self.started
                                    try:
                                        pending = control.poll(state['actor_uid'], int(elapsed*25)&0xffffffff, elapsed)
                                    except ValueError as error:
                                        # Неверный управляющий файл не останавливает мир/урон.
                                        pending = []
                                        self.capture.record('live_scene_error', error=str(error), synthetic=True)
                                    for state_actions, items in groupby(pending,key=lambda row:row[1] is None):
                                        group = list(items)
                                        if not state_actions:
                                            self.send_application_batch(d,remote,state,[(code,payload) for _,code,payload in group])
                                        for name, code, payload in group:
                                            if code is None:
                                                if self.shared_loot:
                                                    packets,event = [],dict(action=payload['action'],accepted=False,reason='solo_action_only')
                                                else:
                                                    try:
                                                        packets,event = apply_state_action(state,payload,self.death_reserved_indexes(state))
                                                    except ValueError as error:
                                                        packets,event = [],dict(action=payload['action'],accepted=False,reason=str(error))
                                                self.send_application_batch(d,remote,state,packets)
                                                control.acknowledge(name)
                                                self.capture.record('live_state_action',id=name,recipient_actor_uid=hex(state['actor_uid']),synthetic=True,**event)
                                                continue
                                            self.register_fixture_entity(state, code, payload)
                                            control.acknowledge(name)
                                            self.capture.record('live_scene_command', id=name, command=hex(code), body_length=len(payload), recipient_actor_uid=hex(state['actor_uid']), synthetic=True)
                                if self.scene_clock and message.command==0xdcd and not state['clock_started']:
                                    # Наблюдаемые режим 1/50/4; старое абсолютное время не воспроизводим.
                                    counter=int((time.monotonic()-self.started)*50)&0xffffffff
                                    config=struct.pack('>6I',1,0,counter,50,int(time.time())&0xffffffff,4)
                                    self.send_application(d,remote,state,0x1f5f,config)
                                    state['clock_started']=True
                                    self.capture.record('clock_configuration',synthetic=True,remote=remote)
                                    self.send_clock(d,remote,state)
                                    if self.selection_seconds is not None:
                                        state['selection_deadline']=time.monotonic()-self.started+self.selection_seconds
                                        self.send_application(d,remote,state,0x486,struct.pack('>II',1,1))
                                        self.send_application(d,remote,state,0x47a,struct.pack('>I',1))
                                        self.send_application(d,remote,state,0x482,struct.pack('>I',self.selection_seconds))
                                        self.capture.record('selection_started',synthetic=True,seconds=self.selection_seconds,remote=remote)
                                        choice = default_choice(self.weapon_fixture)
                                        if choice is not None:
                                            state.setdefault('winter_choice', choice)
                                            self.send_application_batch(d, remote, state, [
                                                (0x11e0, struct.pack('>II', 0, 2)),
                                                (0x11e2, struct.pack('>III', 2, 0, 0)),
                                                (0x10d0, struct.pack('>II', 1, state['winter_choice'])),
                                            ])
                                if default_choice(self.weapon_fixture) is not None and message.command in (0x10cc, 0xbfc):
                                    result = choose_winter_kit(message.command, message.payload,
                                        time.monotonic()-self.started, state.get('selection_deadline'), 'weapon' in state)
                                    if result is not None:
                                        choice, replies, event = result
                                        if choice is not None:
                                            state['winter_choice'] = choice
                                        self.send_application_batch(d, remote, state, replies)
                                        self.capture.record('winter_selection', synthetic=True, **event)
                                if self.spawn_points and message.command == 0x11df:
                                    point, replies, event = choose_cell(message.payload, state['actor_uid'],
                                        time.monotonic()-self.started, state.get('selection_deadline'),
                                        'weapon' in state, self.spawn_points)
                                    if point is not None:
                                        state['born_point'] = point
                                    self.send_application_batch(d, remote, state, replies)
                                    self.capture.record('winter_selection', synthetic=True, **event)
                                if message.command==0x483 and len(message.payload)==1 and 'selection_deadline' in state:
                                    milliseconds=round(state['selection_deadline']*1000)
                                    tick,fraction=divmod(milliseconds,40)
                                    self.send_application(d,remote,state,0x484,struct.pack('>II',tick&0xffffffff,fraction))
                                    self.capture.record('selection_timer_response',synthetic=True,request_byte=message.payload[0],remote=remote)
                                for index, rule in enumerate(self.scene_rules):
                                    trigger, responses = rule[:2]
                                    if trigger != message.command or index in state['scene_rules_sent']:
                                        continue
                                    if len(rule) >= 3 and rule[2]:
                                        deadline=state.get('selection_deadline')
                                        delay=rule[3] if len(rule) >= 4 else 0
                                        if deadline is None or time.monotonic()-self.started < deadline + delay:
                                            continue
                                    state['scene_rules_sent'].add(index)
                                    batch = len(rule) == 5 and rule[4]
                                    batched_responses = []
                                    for response in responses:
                                        command, payload = response[:2]
                                        if (command == 0x27 and len(payload) == 40 and len(rule) >= 3 and rule[2]
                                                and len(response) >= 3 and 0 in response[2] and state.get('born_point')
                                                and not (len(response) == 5 and response[4])):
                                            patched = bytearray(payload)
                                            struct.pack_into('>iii', patched, 8, *state['born_point'][2:])
                                            payload = bytes(patched)
                                        if len(response) >= 3:
                                            patched = bytearray(payload)
                                            for at in response[2]:
                                                struct.pack_into('>Q',patched,at,state['actor_uid'])
                                            payload = bytes(patched)
                                        if len(response) >= 4:
                                            patched=bytearray(payload)
                                            tick=int((time.monotonic()-self.started)*25)&0xffffffff
                                            for at in response[3]:
                                                struct.pack_into('>I',patched,at,tick)
                                            payload=bytes(patched)
                                        if command == 0x5fb and self.weapon_fixture:
                                            weapon = state.setdefault('weapon', WeaponState(selected_fixture(self.weapon_fixture, state.get('winter_choice')), state['actor_uid']))
                                            weapon.available_loot.update(state.get('loot_spawned_uids', set()))
                                            weapon.loot_available = state.get('loot_spawned', False)
                                            if state.get('scene_position'):
                                                weapon.update_position(state['scene_position'])
                                            if self.shared_loot and not self.shared_loot.attach(state):
                                                continue
                                            payload = weapon.inventory()
                                        if command == 0x4a0 and len(payload) == 20:
                                            weapon = state.get('weapon')
                                            actor, slot, _, _ = struct.unpack('>QIII', payload)
                                            if (isinstance(weapon, WeaponState) and weapon.fixture.starter_items
                                                    and actor == state['actor_uid'] and slot in weapon.guns):
                                                # Сценарий содержит старый Citori clip2: после
                                                # выбранного пистолета он не должен сбрасывать магазин.
                                                payload = weapon.ammunition_sync(slot=slot)
                                        if self.shared_vehicles and command==0x654b:
                                            self.register_fixture_entity(state,command,payload)
                                            payload=self.shared_vehicles.register(state,command,payload)
                                        if batch:
                                            batched_responses.append((command, payload))
                                        else:
                                            self.send_application(d,remote,state,command,payload)
                                        self.register_fixture_entity(state, command, payload)
                                        if command == 0x5fb and self.weapon_fixture and not state.get('winter_kit_initialized'):
                                            kit_responses = state['weapon'].kit_sync()
                                            kit_responses.append(state['weapon'].capacity_sync())
                                            if kit_responses:
                                                if batch:
                                                    batched_responses.extend(kit_responses)
                                                else:
                                                    self.send_application_batch(d, remote, state, kit_responses)
                                                state['winter_kit_initialized'] = True
                                                self.capture.record('winter_kit_initialized', synthetic=True,
                                                                    definition=state['weapon'].equipment.get(11),
                                                                    starter_items=list(state['weapon'].fixture.starter_items),
                                                                    starter_item_source=('INITITEM.XML/map16010/stage1'
                                                                        if state['weapon'].fixture.starter_items else 'diagnostic_fixture'),
                                                                    starter_magazine_policy='full_capacity_local',
                                                                    weapon_slots=state['weapon'].fixture.weapon_slots)
                                        if command == 0x5fb and self.weapon_fixture:
                                            magazine_packets = state['weapon'].magazine_syncs()
                                            if batch:
                                                batched_responses.extend(magazine_packets)
                                            else:
                                                self.send_application_batch(d, remote, state, magazine_packets)
                                        if command == 0x5fb and self.weapon_fixture and 'weapon' not in state:
                                            state['weapon'] = WeaponState(selected_fixture(self.weapon_fixture, state.get('winter_choice')), state['actor_uid'])
                                            state['weapon'].loot_available = state.get('loot_spawned', False)
                                            state['weapon'].available_loot.update(state.get('loot_spawned_uids', set()))
                                        self.capture.record('scene_rule_response', synthetic=True,
                                                            trigger=hex(trigger), command=hex(command),
                                                            body_length=len(payload), remote=remote)
                                    if batch:
                                        self.send_application_batch(d, remote, state, batched_responses)
                                if (self.environment_fixture and 'weapon' in state
                                        and not state.get('environment_initialized')
                                        and message.command == 0x1f49):
                                    server_seconds=int(time.time())&0xffffffff
                                    self.send_application_batch(d,remote,state,
                                        self.environment_fixture.messages(server_seconds))
                                    state['environment_initialized']=True
                                    self.capture.record('environment_initialized',synthetic=True,
                                        hour=self.environment_fixture.hour,
                                        temperature_raw=self.environment_fixture.temperature,
                                        server_seconds=server_seconds,
                                        original_temperature_algorithm=False)
                                if self.breakable_fixture and 'weapon' in state and state.get('room_sent'):
                                    if 'breakables' not in state:
                                        state['breakables'] = BreakableState(self.breakable_fixture, state['actor_uid'])
                                    breakables = state['breakables']
                                    position = state.get('last_movement_position', state.get('scene_position'))
                                    if message.command == 0x6f59:
                                        responses, event = breakables.handle(message.payload, position)
                                        self.send_application_batch(d, remote, state, responses)
                                        self.capture.record('breakable_probe', synthetic=True, remote=remote, **event)
                                    elif message.command == 0x1f49:
                                        responses = breakables.snapshot(position)
                                        self.send_application_batch(d, remote, state, responses)
                                        if responses:
                                            self.capture.record('breakable_snapshot', synthetic=True, remote=remote, messages=len(responses))
                                if self.door_fixture and 'weapon' in state and state.get('room_sent'):
                                    if 'doors' not in state:
                                        state['doors'] = DoorState(self.door_fixture)
                                    doors = state['doors']
                                    position = state.get('last_movement_position', state.get('scene_position'))
                                    if message.command == 0x6f57:
                                        responses, event = doors.handle(message.payload, position)
                                        self.send_application_batch(d, remote, state, responses)
                                        self.capture.record('door_probe', synthetic=True, remote=remote, **event)
                                    elif message.command == 0x1f49:
                                        responses = doors.snapshot(position)
                                        self.send_application_batch(d, remote, state, responses)
                                        if responses:
                                            self.capture.record('door_snapshot', synthetic=True, remote=remote, messages=len(responses))
                                if self.shared_loot and 'weapon' in state and message.command == 0x1f49:
                                    if self.shared_loot.attach(state) and not state.get('shared_loot_snapshot_sent'):
                                        snapshot = self.shared_loot.snapshot(state)
                                        self.send_application_batch(d, remote, state, snapshot)
                                        state['shared_loot_snapshot_sent'] = True
                                        self.capture.record('shared_loot_snapshot', synthetic=True,
                                                            account_uid=hex(state['actor_uid']),
                                                            messages=len(snapshot))
                                if (self.peer_avatars and 'weapon' in state and 'scene_position' in state
                                        and message.command == 0x1f49 and not state.get('peer_avatar_admitted')):
                                    tick = int((time.monotonic()-self.started)*25)&0xffffffff
                                    outputs, events = self.peer_avatars.admit(state,tick,time.monotonic())
                                    self.emit_peer_avatars(outputs,events)
                                    state['peer_avatar_admitted'] = True
                                if self.peer_combat and message.command == 0x11dd:
                                    outputs,event,victim = self.peer_combat.hit(state,message.payload,time.monotonic())
                                    self.emit_peer_avatars(outputs,[])
                                    self.capture.record('shared_combat_probe',synthetic=True,**event)
                                    if victim is not None:
                                        state.setdefault('match_statistics',MatchStatistics()).observe(event)
                                        self.emit_peer_avatars(*self.peer_avatars.health(victim,time.monotonic()))
                                        anchor = victim['peer_avatar_anchor']
                                        self.emit_own_death_inventory(anchor[0],anchor[1],victim)
                                        self.cancel_dead_actions(victim,anchor[1])
                                if self.actor_fixture and 'weapon' in state:
                                    self.handle_targets(d, remote, state, message)
                                if self.world_fixture and 'weapon' in state:
                                    if 'world' not in state:
                                        if self.shared_world_clock and not self.shared_loot.attach(state):
                                            continue
                                        joined = time.monotonic()
                                        state['world'] = WorldState(self.world_fixture, state['actor_uid'], joined)
                                        if self.shared_world_clock:
                                            started = self.shared_loot.world_start(state, joined)
                                            if started < joined:
                                                state['world'].align_clock(started, joined)
                                            self.capture.record('shared_world_clock', account_uid=hex(state['actor_uid']),
                                                room_uid=state['room_uid'], epoch=state['shared_loot_epoch'],
                                                elapsed_at_join=joined-started)
                                        state.setdefault('match_statistics', MatchStatistics()).begin(joined)
                                        if state.get('scene_position'):
                                            event = state['world'].update_position(state['scene_position'], time.monotonic())
                                            if event:
                                                self.capture.record('world_probe', synthetic=True, remote=remote, **event)
                                    world = state['world']
                                    if message.command == 0x2a:
                                        movement = decode_move_request(message.payload)
                                        if movement['points']:
                                            event = world.update_position(movement['points'][-1]['position'], time.monotonic())
                                            if event:
                                                self.capture.record('world_probe', synthetic=True, remote=remote, **event)
                                    if message.command == 0x1f49:
                                        vehicles = state.get('vehicles')
                                        protected = bool(vehicles and vehicles.seated
                                            and vehicles.vehicles[vehicles.seated]['configuration'] == 6)
                                        responses, events = world.poll(time.monotonic(), protected=protected)
                                        for command, payload in responses:
                                            self.send_application(d, remote, state, command, payload)
                                        for event in events:
                                            self.capture.record('world_probe', synthetic=True, remote=remote, **event)
                                    if self.peer_avatars:
                                        self.emit_peer_avatars(*self.peer_avatars.health(state, time.monotonic()))
                                    self.emit_own_death_inventory(d, remote, state)
                                self.cancel_dead_actions(state, remote)
                                if self.check_match_end(d, remote, state, time.monotonic()):
                                    continue
                                death_handled = False
                                if 'death_parcels' in state and 'weapon' in state:
                                    corpses = state['death_parcels']
                                    if corpses.matches(message.command, message.payload):
                                        responses, event = corpses.handle(message.command, message.payload, state['weapon'])
                                        state.setdefault('match_statistics', MatchStatistics()).observe(event)
                                        self.send_application_batch(d, remote, state, responses)
                                        if self.shared_loot and self.shared_loot.share_death_parcels:
                                            self.emit_shared_loot(self.shared_loot.death_outputs(state,responses,contents=True))
                                            self.emit_shared_loot(self.shared_loot.publish_external_drops(state,responses))
                                        self.capture.record('death_parcel_probe', synthetic=True, remote=remote, **event)
                                        death_handled = True
                                parcel_pick = (message.command == 0x3b63 and len(message.payload) == 33
                                               and struct.unpack_from('>I', message.payload, 4)[0] != 0)
                                if 'weapon' in state and message.command == 0x2a:
                                    movement = decode_move_request(message.payload)
                                    if movement['points']:
                                        state.setdefault('match_statistics', MatchStatistics()).move(
                                            [point['position'] for point in movement['points']])
                                        state['last_movement_position'] = movement['points'][-1]['position']
                                        state['weapon'].update_position(state['last_movement_position'])
                                        if self.peer_avatars:
                                            now = time.monotonic()
                                            outputs, events = self.peer_avatars.move(state,state['last_movement_position'],int((now-self.started)*25)&0xffffffff,now,movement)
                                            self.emit_peer_avatars(outputs,events)
                                if self.loot_catalog and 'weapon' in state and message.command == 0x1f49:
                                    if 'loot_catalog' not in state:
                                        state['loot_catalog'] = LootCatalogState(self.loot_catalog, state['weapon'])
                                    responses, events = state['loot_catalog'].poll()
                                    self.send_application_batch(d, remote, state, responses)
                                    for event in events:
                                        self.capture.record('loot_catalog_probe', synthetic=True,
                                                            remote=remote, **event)
                                if 'parcels' in state and 'weapon' in state and not death_handled and (message.command == 0x656f or parcel_pick):
                                    responses, event = state['parcels'].handle(message.command, message.payload, state['weapon'])
                                    state.setdefault('match_statistics', MatchStatistics()).observe(event)
                                    self.send_application_batch(d, remote, state, responses)
                                    self.capture.record('parcel_probe', synthetic=True, remote=remote, **event)
                                if 'weapon' in state:
                                    responses, reload_events = state['weapon'].poll(time.monotonic())
                                    responses = self.reconcile_resume_reload(remote, state, responses, reload_events)
                                    self.send_application_batch(d, remote, state, responses)
                                    for reload_event in reload_events:
                                        self.capture.record('weapon_probe', synthetic=True, remote=remote, **reload_event)
                                medical_handled = False
                                if 'weapon' in state and 'world' in state:
                                    if 'medical' not in state:
                                        state['medical'] = MedicalState(state['weapon'], state['world'])
                                    medical = state['medical']
                                    result = medical.handle(message.command, message.payload, time.monotonic())
                                    if result is not None:
                                        medical_handled = True
                                        responses, events = result
                                    else:
                                        responses, events = medical.poll(time.monotonic())
                                    self.send_application_batch(d, remote, state, responses)
                                    for event in events:
                                        self.capture.record('medical_probe', synthetic=True, remote=remote, **event)
                                if medical_handled and self.peer_avatars:
                                    self.emit_peer_avatars(*self.peer_avatars.health(state, time.monotonic()))
                                if 'weapon' in state and state['weapon'].fixture.throwable_actions:
                                    grenades = state.setdefault('throwable_actions', ThrowableActions())
                                    now = time.monotonic()
                                    if message.command == 0x1004:
                                        responses, event = grenades.launch(state['weapon'], message.payload, now)
                                        self.send_application_batch(d, remote, state, responses)
                                        self.capture.record('throwable_probe', synthetic=True, remote=remote, **event)
                                    elif message.command == 0x1007:
                                        tick = int((now-self.started)*25) & 0xffffffff
                                        responses, event, finished = grenades.finish(message.payload, state['actor_uid'], now, tick)
                                        self.send_application_batch(d, remote, state, responses)
                                        self.capture.record('throwable_probe', synthetic=True, remote=remote, **event)
                                        if finished is not None:
                                            self.apply_diagnostic_grenade(d, remote, state, finished)
                                    elif message.command == 0x1f49:
                                        for identifier in grenades.expire(now):
                                            self.capture.record('throwable_probe', synthetic=True, remote=remote,
                                                                action='throw_expired', identifier=identifier,
                                                                original_server_physics=False)
                                if 'weapon' in state and message.command in (0x49e, 0x49c, 0x11da, 0x3b63, 0x3e80) and not parcel_pick and not medical_handled:
                                    if self.shared_loot:
                                        responses, event, shared_outputs = self.shared_loot.handle(state, message.command, message.payload)
                                        self.emit_shared_loot(shared_outputs)
                                    else:
                                        responses, event = state['weapon'].handle(message.command, message.payload)
                                    state.setdefault('match_statistics', MatchStatistics()).observe(event)
                                    for command, payload in responses:
                                        self.send_application(d, remote, state, command, payload)
                                    self.capture.record('weapon_probe', synthetic=True, remote=remote, **event)
                                    if message.command == 0x11da and self.peer_combat:
                                        self.peer_combat.note_fire(state,message.payload,event,time.monotonic())
                                    if message.command == 0x11da and 'vehicles' in state:
                                        state['vehicles'].note_fire(message.payload, event)
                                    if message.command == 0x11da and 'target_roster' in state:
                                        state['target_roster'].note_fire(message.payload, event)
                                if 'vehicles' in state and message.command == 0x1f49:
                                    now=time.monotonic()
                                    responses, events = state['vehicles'].poll(now,int((now-self.started)*25)&0xffffffff)
                                    self.send_application_batch(d, remote, state, responses)
                                    for event in events:
                                        self.capture.record('vehicle_probe', synthetic=True, remote=remote, **event)
                                    if state['vehicles'].evacuation_finished:
                                        self.finish_gameplay(state, remote, 'rescued')
                                parcel_motion = None
                                if (message.command == 0x6549 and 'parcels' in state
                                        and 'weapon' in state and hasattr(state['parcels'], 'observe_motion')):
                                    parcel_motion = state['parcels'].observe_motion(message.payload, state['weapon'])
                                    if parcel_motion:
                                        self.capture.record('parcel_probe', synthetic=True,
                                                            remote=remote, **parcel_motion)
                                if 'vehicles' in state and parcel_motion is None and message.command in (0x6541, 0x6543, 0x6547, 0x6549, 0x657a, 0x11de):
                                    if (self.shared_evacuation and message.command == 0x6541
                                            and (not self.shared_vehicles or len(message.payload)==12
                                                 and state['vehicles'].vehicles.get(
                                                     struct.unpack_from('>Q',message.payload)[0],{}).get('configuration')==6)):
                                        self.shared_evacuation.sync(self.peer_avatars)
                                        responses, event = self.shared_evacuation.geton(state, message.payload, time.monotonic())
                                        if event['action'] == 'shared_evacuation_geton':
                                            self.broadcast_shared_geton(state, responses)
                                    elif self.shared_vehicles:
                                        now=time.monotonic()
                                        self.shared_vehicles.sync(self.peer_avatars,now)
                                        responses,event,outputs=self.shared_vehicles.handle(
                                            state,message.command,message.payload,now)
                                        self.emit_peer_avatars(outputs,[])
                                    else:
                                        responses, event = state['vehicles'].handle(message.command, message.payload)
                                    if 'world' in state and event['action'] in ('vehicle_move', 'getoff'):
                                        world_event = state['world'].update_position(event['position'], time.monotonic())
                                        if world_event:
                                            self.capture.record('world_probe',synthetic=True,remote=remote,**world_event)
                                    for command, payload in responses:
                                        self.send_application(d, remote, state, command, payload)
                                    self.capture.record('vehicle_probe', synthetic=True, remote=remote, **event)
                except ValueError as error:
                    self.capture.record('decrypt_error',command=hex(frame.command),error=str(error),remote=remote)
        except ValueError as error:
            self.capture.record('frame_error', error=str(error), remote=remote)

    def send(self, d, remote, sequence, acknowledgement, flags, data=b''):
        clock = int((time.monotonic()-self.started)*1000)&0xffff
        raw = encode_datagram(d.destination_port, d.source_port, sequence, acknowledgement, flags, clock, d.clock,data)
        if self.reliable_udp and (data or flags & 2):
            state = self.sessions[(remote, d.source_port, d.destination_port)]
            if not state['sender'].remember(raw, sequence, len(data) + bool(flags & 2), time.monotonic()):
                self.capture.record('udp_delivery_failed', remote=remote, reason='sender_limit')
                return
        self.transport.sendto(raw, remote)
        self.capture.record('send', raw, transport='udp', remote=remote)

    def retry_pending(self):
        """Повторяет байты без вызова игровых обработчиков и AES-сериализации."""
        self.stop_retries()
        for identity, state in list(self.sessions.items()):
            if state.get('transport_retired'):
                continue
            sender = state.get('sender')
            if sender is None:
                continue
            for sequence, raw, attempt in sender.due(time.monotonic()):
                self.transport.sendto(raw, identity[0])
                self.capture.record('udp_retry', remote=identity[0], udp_sequence=sequence,
                                    length=len(raw), attempt=attempt)
            if sender.failed and not state.get('delivery_failed_logged'):
                state['delivery_failed_logged'] = True
                self.capture.record('udp_delivery_failed', remote=identity[0], reason='retry_limit')
        self.retry_timer = asyncio.get_running_loop().call_later(.05, self.retry_pending)

    def stop_retries(self):
        if self.retry_timer is not None:
            self.retry_timer.cancel()
            self.retry_timer = None

    def connection_lost(self, exc):
        self.stop_retries()
        self.stop_peer_timer()
        self.match_timers_enabled = False
        if self.match_timer is not None:
            self.match_timer.cancel()
            self.match_timer = None

    def stop_peer_timer(self):
        if self.peer_timer is not None:
            self.peer_timer.cancel()
            self.peer_timer = None

    def poll_peer_rooms(self):
        self.peer_timer = None
        if self.peer_avatars:
            now = time.monotonic()
            self.emit_peer_avatars(*self.peer_avatars.equipment(now))
            self.emit_peer_avatars(*self.peer_avatars.pose_snapshots(now,int((now-self.started)*25)&0xffffffff))
            self.emit_peer_avatars(*self.peer_avatars.settle_motion(now,int((now-self.started)*25)&0xffffffff))
        for state, reason in expired_members(self.peer_avatars, self.shared_loot, time.monotonic()):
            if self.peer_avatars:
                outputs, events = self.peer_avatars.detach(state, reason)
                self.emit_peer_avatars(outputs, events)
            reset = self.shared_loot.detach(state) if self.shared_loot else False
            # Итог завершённого матча ещё доставляется и допускает frozen
            # RELAY30с. Удаление из мира не должно уничтожать этот контракт.
            if reason != 'match_finished':
                state.update(transport_retired=True, room_sent=False)
            state['clock_started'] = False
            state.pop('handoff_at', None)
            self.capture.record('peer_room_expired', synthetic=True, reason=reason,
                                account_uid=hex(state['actor_uid']), room_uid=hex(state['room_uid']),
                                room_reset=reset)
        if self.shared_vehicles:
            now=time.monotonic()
            self.shared_vehicles.sync(self.peer_avatars,now)
            self.emit_peer_avatars(*self.shared_vehicles.snapshots(now))
        if self.shared_evacuation:
            self.shared_evacuation.sync(self.peer_avatars)
            self.poll_shared_evacuation(time.monotonic())
        if self.peer_spectators:
            self.emit_peer_avatars(*self.peer_spectators.poll(self.peer_avatars, time.monotonic()))
        delay = .1 if self.peer_avatars and self.peer_avatars.replicate_trajectories else 1
        self.peer_timer = asyncio.get_running_loop().call_later(delay, self.poll_peer_rooms)

    def broadcast_shared_geton(self, state, packets):
        """Собственный GETON остаётся own; другим адресуется remote Unit UID."""
        key = (state['room_uid'], state['actor_uid'])
        member = self.peer_avatars.members.get(key)
        if member is None:
            return
        outputs = []
        for other_key, other in self.peer_avatars.members.items():
            if other_key[0] != key[0] or other_key == key:
                continue
            translated = []
            for command, payload in packets:
                body = bytearray(payload)
                if command == 0x6542:
                    struct.pack_into('>Q', body, 16, member['avatar'])
                translated.append((command,bytes(body)))
            outputs.append((other['state'], translated))
        self.emit_peer_avatars(outputs, [])

    def poll_shared_evacuation(self, now):
        decisions, events = self.shared_evacuation.poll(now)
        for event in events:
            self.capture.record('shared_evacuation_probe', synthetic=True, **event)
        for decision in decisions:
            room_uid, seats = decision['room_uid'], decision['seats']
            prepared = []
            try:
                for account, state in decision['members'].items():
                    statistics = state['match_statistics']
                    report = statistics.snapshot(decision['ended_at'])
                    rescued = account in seats
                    report['rescued'] = int(rescued)
                    packets = []
                    for passenger, seat in seats.items():
                        source = decision['members'][passenger]
                        unit = (passenger if passenger == account else
                                self.peer_avatars.members[(room_uid,passenger)]['avatar'])
                        packets.append((0x6580,survivor_event(decision['helicopter_uid'],
                            unit, source.get('actor_display_name',self.room_display_name),seat)))
                    packets.extend(self.evacuation_result_fixture.messages(account,room_uid,
                        report,state.get('actor_display_name',self.room_display_name)))
                    packets.append((0x6589,struct.pack('>BQ',int(rescued),
                                   decision['helicopter_uid'] if rescued else 0)))
                    prepared.append((state,packets,rescued))
            except (ValueError,KeyError) as error:
                self.capture.record('shared_evacuation_invalid_result',synthetic=True,
                                    room_uid=hex(room_uid),error=str(error))
                continue
            self.shared_evacuation.commit(decision)
            for state, packets, rescued in prepared:
                state['match_statistics'].finish(decision['ended_at'],rescued=rescued)
                state['match_terminal_packets'] = tuple(packets)
                vehicles = state.get('vehicles')
                if vehicles is not None:
                    vehicles.evacuation_finished = True
                anchor = state.get('peer_avatar_anchor')
                if anchor:
                    self.send_application_batch(anchor[0],anchor[1],state,packets)
                self.finish_gameplay(state,anchor[1] if anchor else None,
                                     'rescued' if rescued else decision['reason'])
            self.capture.record('shared_evacuation_probe',synthetic=True,
                action='shared_evacuation_finish',room_uid=hex(room_uid),
                reason=decision['reason'],rescued=len(seats),
                recipients=len(prepared),original_rule_verified=False)

    def poll_match_ends(self):
        """Лимит матча не зависит от heartbeat или потерянного C2S."""
        self.match_timer = None
        now = time.monotonic()
        for identity, state in list(self.sessions.items()):
            if (state.get('transport_retired') or state.get('match_finished')
                    or not state.get('room_sent')):
                continue
            header = state.get('transport_header')
            if header is not None:
                self.check_match_end(header, identity[0], state, now)
        if self.match_timers_enabled:
            self.match_timer = asyncio.get_running_loop().call_later(.1, self.poll_match_ends)

    def check_match_end(self, d, remote, state, now):
        if state.get('match_finished'):
            self.capture.record('finished_action_rejected', synthetic=True, remote=remote)
            return True
        fixture = self.evacuation_result_fixture
        world, statistics = state.get('world'), state.get('match_statistics')
        if fixture is None or world is None or statistics is None:
            return False
        policy = state.setdefault('match_end_policy',
            MatchEndPolicy(fixture.result_on_death, fixture.timeout_seconds))
        if not policy.enabled:
            return False
        vehicles = state.get('vehicles')
        packets, event = policy.poll(now, world, statistics, fixture,
            state['actor_uid'], state.get('room_uid', 1),
            state.get('actor_display_name', self.room_display_name),
            already_rescued=bool(vehicles and vehicles.evacuation_finished))
        if event is None:
            return False
        state['match_terminal_packets'] = tuple(packets)
        self.send_application_batch(d, remote, state, packets)
        self.finish_gameplay(state, remote, event['cause'])
        self.capture.record('match_result', synthetic=True, remote=remote, **event)
        return True

    def finish_gameplay(self, state, remote, cause):
        """Сохраняет итог, отменяет pending действия; transport доставляет ACK/retry."""
        if state.get('match_finished'):
            return
        state['match_finished'] = True
        state['match_finished_at'] = time.monotonic()
        state['clock_started'] = False
        weapon, medical = state.get('weapon'), state.get('medical')
        if weapon is not None:
            weapon.pending_reload = None
        if medical is not None:
            medical.pending = medical.completed_at = None
        grenades = state.get('throwable_actions')
        if grenades is not None:
            grenades.pending.clear()
        vehicles = state.get('vehicles')
        if vehicles is not None:
            vehicles.seated = vehicles.seat = vehicles.seated_at = None
            vehicles.climb_until = 0
        # Итог и transport остаются для доставки/аудита. Mutable игровые
        # объекты прежней комнаты больше не нужны новому поиску/сеансу.
        released = []
        for field in ('world', 'weapon', 'medical', 'throwable_actions', 'vehicles',
                      'parcels', 'target_actor', 'target_inventory', 'target_roster', 'bot_controller', 'death_parcels',
                      'loot_catalog', 'live_control', 'loot_spawned_uids'):
            if field in state:
                state.pop(field)
                released.append(field)
        self.capture.record('match_gameplay_finished', synthetic=True, remote=remote,
                            cause=cause, pending_actions_cancelled=True,
                            released_gameplay_fields=released)

    @staticmethod
    def target_actors(state):
        roster = state.get('target_roster')
        if roster is not None:
            return tuple(roster.actors.values())
        actor = state.get('target_actor')
        return (actor,) if actor else ()

    def live_control_for(self, state):
        if 'live_control' not in state:
            sent = self.live_sent_by_actor.setdefault(state['actor_uid'], set())
            state['live_control'] = LiveSceneCommands(self.live_commands, sent=sent)
        return state['live_control']

    @staticmethod
    def target_inventory_for(state, actor):
        roster = state.get('target_roster')
        return (roster.inventories.get(actor.fixture.uid) if roster is not None
                else state.get('target_inventory'))

    def transfer_target_death(self, d, remote, state, actor):
        inventory = self.target_inventory_for(state, actor)
        if actor.hp != 0 or inventory is None:
            return
        if actor.fixture.armor_definition:
            inventory.equipment_durability[12] = actor.armor_durability
        corpses = state.setdefault('death_parcels', DeathParcelState())
        packets, event = corpses.transfer(inventory, actor.position, self.death_reserved_indexes(state))
        self.send_application_batch(d, remote, state, packets)
        self.capture.record('death_parcel_probe', synthetic=True, remote=remote, **event)

    def handle_targets(self, d, remote, state, message):
        fixtures = self.actor_fixtures if len(self.actor_fixtures) > 1 else (self.actor_fixture,)
        legacy = state.get('target_actor')
        current = state.get('target_roster')
        legacy_changed = (len(fixtures) == 1 and legacy is not None
                          and (current is None or current.actors.get(legacy.fixture.uid) is not legacy))
        if current is None or legacy_changed:
            roster = TargetRoster(fixtures, state['weapon'].fixture, state['actor_uid'])
            if legacy_changed:
                roster.actors[fixtures[0].uid] = legacy
            state['target_roster'] = roster
            # Имена одиночного профиля сохранены для диагностических tools/tests.
            first = next(iter(roster.actors.values()))
            state['target_actor'] = first
            if first.fixture.uid in roster.inventories:
                state['target_inventory'] = roster.inventories[first.fixture.uid]
        roster = state['target_roster']
        if message.command == 0x11dd:
            responses, event, actor = roster.hit(message.payload, state['actor_uid'])
            state.setdefault('match_statistics', MatchStatistics()).observe(event)
            self.send_application_batch(d, remote, state, responses)
            self.capture.record('actor_probe', synthetic=True, **event)
            if event.get('action') == 'hit_damage' and actor is not None:
                self.transfer_target_death(d, remote, state, actor)
        elif message.command == 0x1f49:
            now = time.monotonic()
            tick = int((now-self.started)*25) & 0xffffffff
            world, vehicles = state.get('world'), state.get('vehicles')
            protected = bool(vehicles and (vehicles.seated or vehicles.climb_protected(now))) or not state['weapon'].gun_owned or bool(world and getattr(world, 'dead', False))
            for actor in roster.actors.values():
                if not actor.started:
                    self.send_application_batch(d, remote, state, actor.begin(tick))
                    self.capture.record('actor_probe', action='actor_created', uid=hex(actor.fixture.uid),
                                        synthetic=True, target_count=len(roster.actors))
                if actor.fixture.behavior and world:
                    if 'bot_controller' not in state:
                        state['bot_controller'] = BotController(actor, state['weapon'])
                    controller = state['bot_controller']
                    bot_packets, bot_events = controller.poll(now, state['weapon'], world, vehicles)
                    roster.inventories[actor.fixture.uid] = controller.inventory
                    state['target_inventory'] = controller.inventory
                    self.send_application_batch(d, remote, state, bot_packets)
                    for event in bot_events:
                        self.capture.record('actor_probe', synthetic=True, **event)
                responses, events = actor.poll(now, tick, world.position if world else None, protected=protected)
                self.send_application_batch(d, remote, state, responses)
                for event in events:
                    self.capture.record('actor_probe', synthetic=True, **event)
                    if event['action'] == 'bot_attack' and world:
                        damage, armor_packets, armor_event = state['weapon'].absorb_combat_damage(event['damage'])
                        damage_packets, damage_event = world.apply_damage(damage, actor.fixture.uid)
                        damage_event['validation'] = event['validation']
                        self.send_application_batch(d, remote, state, armor_packets + damage_packets)
                        self.capture.record('weapon_probe', synthetic=True, remote=remote, **armor_event)
                        self.capture.record('world_probe', synthetic=True, remote=remote, **damage_event)

    def send_frame(self,d,remote,state,command,sequence,plain,extra=b'', applications=()):
        body=encrypt(plain,state['key'])
        frame=struct.pack('>HHHHBIII',0x3366,10,10,command,1,sequence,21+len(extra),len(body))+extra+body
        if applications:
            # Только маршрутизация собственных ответов; payload/ключи не журналируются.
            self.capture.record('gameplay_frame_send', remote=remote,
                                commands=[hex(code) for code in applications],
                                frame_sequence=sequence, udp_sequence_start=(state['seq']+1)&0xffffffff,
                                source_port=d.destination_port, destination_port=d.source_port,
                                frame_length=len(frame), encrypted_body_length=len(body))
        # В захватах длинные TGCP рамки разделены на потоковые сегменты по 500 байт.
        for at in range(0,len(frame),500):
            chunk=frame[at:at+500]
            self.send(d,remote,state['seq']+1,state['next_client'],0x18,chunk)
            state['seq']+=len(chunk)

    @staticmethod
    def death_reserved_indexes(state):
        indexes = set(state['weapon'].loot_registry)
        parcels = state.get('parcels')
        containers = getattr(parcels, 'containers', ())
        for container in containers:
            indexes.add(container.fixture.index)
            indexes.update(x.index for x in container.fixture.items)
        if parcels is not None and not containers:
            fixture = parcels.fixture
            indexes.update((fixture.index, fixture.item_index))
        return indexes

    def emit_own_death_inventory(self, d, remote, state):
        world, weapon = state.get('world'), state.get('weapon')
        if (world is None or not getattr(world, 'dead', False) or weapon is None
                or state.get('own_death_inventory_processed')):
            return
        corpses = state.setdefault('death_parcels', DeathParcelState())
        try:
            packets, event = corpses.transfer(weapon, world.position,
                                               self.death_reserved_indexes(state))
        except ValueError as error:
            self.capture.record('death_parcel_probe', synthetic=True, remote=remote,
                                action='own_death_inventory_blocked', reason=str(error))
        else:
            self.send_application_batch(d, remote, state, weapon.reconcile_inventory() + packets)
            if self.shared_loot and self.shared_loot.share_death_parcels:
                self.emit_shared_loot(self.shared_loot.death_outputs(state,packets))
            self.capture.record('death_parcel_probe', synthetic=True, remote=remote, **event)
        state['own_death_inventory_processed'] = True

    def apply_diagnostic_grenade(self, d, remote, state, finished):
        """Opt-in учебный frag: flat damage, радиус и известные AABB стенда.

        Client-list сам по себе не наносит урон. Проверяем принятую grenade
        lifecycle, тип, живую цель, серверную позицию и известные преграды.
        Полный LOS карты и оригинальная формула/световая слепота ещё открыты.
        """
        damage = state['weapon'].fixture.diagnostic_frag_damage
        if finished.definition != 50001 or not damage:
            return
        radius = THROWABLE_EFFECT_PROFILES[50001][1]
        actors = self.target_actors(state)
        boxes = actors[0].fixture.collision_boxes or () if actors else ()

        def reachable(point):
            if point is None or sum((a-b)**2 for a,b in zip(point, finished.point)) > radius**2:
                return False
            return not any(segment_box_entry(finished.point, point, lower, upper) is not None
                           for lower, upper in boxes)

        reported = set(finished.actors) | {uid for uid, _ in finished.actor_fields}
        for actor in actors:
            if actor.fixture.uid in reported and reachable(actor.position):
                packets, event = actor.diagnostic_area_damage(damage)
                state.setdefault('match_statistics', MatchStatistics()).observe(event)
                self.send_application_batch(d, remote, state, packets)
                self.capture.record('throwable_probe', synthetic=True, remote=remote,
                                    identifier=finished.identifier, **event)
                self.transfer_target_death(d, remote, state, actor)
        world = state.get('world')
        if world and not world.dead and reachable(world.position):
            hurt, armor_packets, armor_event = state['weapon'].absorb_combat_damage(damage)
            packets, event = world.apply_damage(hurt, state['actor_uid'])
            self.send_application_batch(d, remote, state, armor_packets + packets)
            self.capture.record('weapon_probe', synthetic=True, remote=remote, **armor_event)
            self.capture.record('world_probe', synthetic=True, remote=remote, **event)
            if self.peer_avatars:
                self.emit_peer_avatars(*self.peer_avatars.health(state, time.monotonic()))
            self.emit_own_death_inventory(d, remote, state)
            self.cancel_dead_actions(state, remote)

    def cancel_dead_actions(self, state, remote):
        world = state.get('world')
        if world is None or not getattr(world, 'dead', False):
            return
        statistics = state.get('match_statistics')
        if statistics is not None and statistics.ended_at is None:
            report = statistics.finish(time.monotonic(), rescued=False)
            self.capture.record('match_statistics', synthetic=True, remote=remote,
                                terminal='death', **report)
        vehicles = state.get('vehicles')
        if vehicles is not None:
            event = vehicles.cancel_on_death()
            if event is not None:
                self.capture.record('vehicle_probe', synthetic=True, remote=remote, **event)
        weapon, medical = state.get('weapon'), state.get('medical')
        if weapon is not None and weapon.pending_reload is not None:
            weapon.pending_reload = None
            self.capture.record('weapon_probe', action='reload_cancelled_on_death',
                                synthetic=True, remote=remote)
        if medical is not None:
            if medical.pending is not None:
                medical.pending = None
                self.capture.record('medical_probe', action='medical_cancelled_on_death',
                                    synthetic=True, remote=remote)
            # Не отправлять status27 после смерти: это окончание живого action.
            medical.completed_at = None

    def accept_living_action(self, state, message, remote):
        world = state.get('world')
        if (world is not None and getattr(world, 'dead', False) and message.command in (
                0x6f57, 0x6f59, 0x2a, 0x49e, 0x49c, 0x11da, 0x11dd, 0x11de, 0x3b63, 0x3e80, 0x536, 0x1004,
                0x6541, 0x6543, 0x6547, 0x6549, 0x657a, 0x656f, 0xbce)):
            self.capture.record('dead_action_rejected', command=hex(message.command),
                                synthetic=True, remote=remote)
            return False
        return True

    def accept_inventory_action(self, state, message, remote):
        """Один эффект известного gameplay-запроса текущего упорядоченного транспорта.

        Native2022 увеличивает первое BE32 каждого application message.
        Проверяем serial32 для pickup/discard/reload/fire/hand, не payload:
        новый id проходит этот guard; fire отдельно проверяет счётчик выстрела.
        При новом AUTH граница новая; журнал прежнего транспорта не переносим.
        Ответы старого inventory не пересылаем: они откатили бы HUD после
        промежуточного действия. ACK потока уже отправлен datagram_received.
        """
        sequence = message.sequence
        if type(sequence) is not int or not 0 <= sequence <= 0xffffffff:
            self.capture.record('inventory_action_rejected', reason='missing_sequence',
                                command=hex(message.command), remote=remote, synthetic=True)
            return False
        previous = state.get('inventory_action_sequence')
        if previous is not None:
            delta = (sequence - previous) & 0xffffffff
            if delta == 0 or delta >= 0x80000000:
                self.capture.record('inventory_action_rejected',
                                    reason='repeated_sequence' if delta == 0 else 'stale_sequence',
                                    command=hex(message.command), application_sequence=sequence,
                                    previous_sequence=previous, remote=remote, synthetic=True)
                return False
        state['inventory_action_sequence'] = sequence
        return True

    def resume_gameplay(self, identity, state, now, relay_actor_uid=None):
        """Однократный перенос явно закрытой локальной диагностической сессии.

        Ключ, TGCP frame/stream sequence и ACK остаются у нового транспорта.
        Это стенд с synthetic AUTH, не серверная авторизация для LAN.
        """
        if not state.get('auth_sent') or not state.get('identity') or state.get('room_sent'):
            return False
        if (self.peer_avatars or self.shared_loot) and relay_actor_uid is None:
            # В диагностическом лобби identity нескольких аккаунтов совпадает.
            # Ждём UID C2S RELAY, иначе AUTH может забрать состояние другого игрока.
            return False
        candidates = [(key, value) for key, value in self.sessions.items()
                      if value is not state and value.get('room_sent')
                      and value.get('auth_sent') and value.get('identity') == state['identity']
                      and not getattr(value.get('vehicles'), 'evacuation_finished', False)
                      and not value.get('match_finished')
                      and not value.get('transport_retired')
                      and (not (self.peer_avatars or self.shared_loot)
                           or value.get('actor_uid') == relay_actor_uid)
                      and key[0][0] == identity[0][0] and key[2] == identity[2]
                      and (0 <= now-value.get('handoff_at', -1000000) <= 30
                           or (self.idle_handoff and self.reliable_udp
                               and relay_actor_uid == value.get('actor_uid')
                               and relay_actor_uid is not None
                               and 5 <= now-value.get('last_application_at', now) <= 30))]
        if len(candidates) != 1:
            return False
        previous_identity, previous = candidates[0]
        handoff_mode = ('explicit_close' if 0 <= now-previous.get('handoff_at', -1000000) <= 30
                        else 'authenticated_idle_relay')
        idle_seconds = now-previous.get('last_application_at', now)
        fields = ('actor_uid', 'room_uid', 'actor_display_name', 'scene_position', 'scene_position_sync', 'last_movement_position', 'movement_guard', 'scene_rules_sent', 'clock_started',
                  'selection_deadline', 'weapon', 'medical', 'vehicles', 'parcels', 'target_actor',
                  'target_inventory', 'target_roster', 'bot_controller', 'death_parcels', 'throwable_actions',
                  'own_death_inventory_processed',
                  'world', 'match_statistics', 'match_end_policy', 'live_control', 'loot_spawned', 'loot_spawned_uids',
                  'winter_kit_initialized', 'winter_choice', 'born_point', 'loot_catalog', 'environment_initialized',
                  'shared_loot_epoch', 'doors', 'breakables')
        for name in fields:
            if name in previous:
                state[name] = previous.pop(name)
        state['room_sent'] = True
        state['gameplay_resumed'] = True
        previous['room_sent'] = False
        previous.pop('handoff_at', None)
        previous['clock_started'] = False
        previous['transport_retired'] = True
        if 'breakables' in state:
            state['breakables'].resume()
        if 'doors' in state:
            state['doors'].resume()
        if self.shared_loot and 'weapon' in state:
            self.shared_loot.attach(state)
        if self.peer_avatars and 'scene_position' in state:
            tick = int((now-self.started)*25) & 0xffffffff
            outputs, events = self.peer_avatars.admit(state, tick, time.monotonic())
            self.emit_peer_avatars(outputs, events)
            state['peer_avatar_admitted'] = True
        sender = previous.get('sender')
        if sender is not None:
            sender.pending.clear()
            sender.bytes = 0
        # Только диагностические игровые поля; ключи/identity не журналируем.
        world, weapon = state.get('world'), state.get('weapon')
        # Клиентский RELAY может сбросить actor к стартовой позиции. Сохраняем
        # последнюю позицию до новых2a и возвращаем её известным27 после7083.
        state['resume_position_snapshot'] = (getattr(world, 'position', None)
                                             or state.get('last_movement_position')
                                             or state.get('scene_position'))
        self.capture.record('gameplay_handoff_complete', synthetic=True,
                            handoff_mode=handoff_mode, previous_idle_seconds=idle_seconds,
                            previous_remote=previous_identity[0], remote=identity[0],
                            experimental=True,
                            target_count=len(self.target_actors(state)),
                            target_states=[dict(uid=hex(actor.fixture.uid), hp=actor.hp,
                                                armor_durability=actor.armor_durability)
                                           for actor in self.target_actors(state)],
                            world_position=getattr(world, 'position', None),
                            world_hp=getattr(world, 'hp', None),
                            world_started=getattr(world, 'started', None),
                            world_stage_index=getattr(world, 'stage_index', None),
                            world_warning_index=getattr(world, 'warning_index', None),
                            clip=getattr(weapon, 'clip', None), reserve=getattr(weapon, 'reserve', None),
                            ammunition_definition=(weapon.gun_ammunition if isinstance(weapon, WeaponState) else None),
                            ammunition_quantity=(weapon.ammunition_quantity(weapon.gun_ammunition)
                                                 if isinstance(weapon, WeaponState) else None),
                            door_state_changes=({str(identifier): status
                                for identifier, status in state['doors'].status.items()
                                if status != state['doors'].fixture.doors[identifier][1]}
                                if isinstance(state.get('doors'), DoorState) else None),
                            picked_loot_count=len(getattr(weapon, 'picked_loot', ())),
                            available_loot_count=len(getattr(weapon, 'available_loot', ())),
                            frame_sequence=state['frame_seq'])
        return True

    def resume_finished_result(self, identity, d, state, now, relay_actor_uid):
        """Только frozen проигрышный итог после AUTH/RELAY, без новой игры.

        Cold177: C2S blackout закрыл старый канал до timer result; новый
        AUTH дошёл после deadline. Старый retry не достигает нового ключа.
        Граница30с/identity/actor/IP/virtual destination совпадает с local
        handoff. Это не возможность продолжить завершённый матч.
        """
        if (not self.idle_handoff or not self.reliable_udp or not state.get('auth_sent')
                or not state.get('identity') or state.get('room_sent')
                or relay_actor_uid is None):
            return False
        candidates = [(key, value) for key, value in self.sessions.items()
                      if value is not state and value.get('room_sent')
                      and value.get('auth_sent') and value.get('match_finished')
                      and value.get('match_terminal_packets')
                      and not value.get('transport_retired')
                      and value.get('identity') == state['identity']
                      and value.get('actor_uid') == relay_actor_uid
                      and key[0][0] == identity[0][0] and key[2] == identity[2]
                      and 0 <= now-value.get('match_finished_at', -1000000) <= 30]
        if len(candidates) != 1:
            return False
        previous_identity, previous = candidates[0]
        for field in ('actor_uid','room_uid','actor_display_name','match_statistics',
                      'match_end_policy','match_finished_at','match_terminal_packets'):
            if field in previous:
                state[field] = previous[field]
        state.update(room_sent=True, match_finished=True, clock_started=False)
        previous.update(room_sent=False, transport_retired=True)
        sender = previous.get('sender')
        if sender is not None:
            sender.pending.clear()
            sender.bytes = 0
        # Сначала штатный ответ RELAY, затем уже зафиксированный итог.
        for rule in self.scene_rules:
            if rule[0] == 0xdcd:
                for response in rule[1]:
                    if response[0] == 0x7083:
                        self.send_application(d, identity[0], state, 0x7083, response[1])
        self.send_application_batch(d, identity[0], state, state['match_terminal_packets'])
        self.capture.record('match_terminal_replayed', synthetic=True,
                            previous_remote=previous_identity[0], remote=identity[0],
                            actor_uid=hex(relay_actor_uid), restored_gameplay=False,
                            seconds_after_finish=now-state['match_finished_at'])
        return True

    def restore_resume_position(self, d, remote, state):
        """Однократный27 текущей позиции; не повторять сцену/лут/инвентарь."""
        if state.get('resume_position_sent'):
            return
        template = state.get('scene_position_sync')
        position = state.get('resume_position_snapshot')
        if (not isinstance(template, bytes) or len(template) != 40
                or not position or len(position) != 3
                or any(type(n) is not int or not -2**31 <= n < 2**31 for n in position)):
            self.capture.record('gameplay_resume_position_missing', synthetic=True, remote=remote)
            return
        payload = bytearray(template)
        struct.pack_into('>Q3i', payload, 0, state['actor_uid'], *position)
        struct.pack_into('>I', payload, 31, int((time.monotonic()-self.started)*25)&0xffffffff)
        payload = bytes(payload)
        self.send_application(d, remote, state, 0x27, payload)
        state['resume_position_sent'] = True
        self.register_fixture_entity(state, 0x27, payload)
        self.capture.record('gameplay_resume_position_sync', synthetic=True,
                            remote=remote, position=position, command='0x27')

    def restore_resume_world(self, d, remote, state):
        """Стадия и действующее предупреждение481 после смены транспорта."""
        if state.get('resume_world_sent'):
            return
        world = state.get('world')
        if not isinstance(world, WorldState) or not world.fixture.restore_stage_on_resume:
            return
        now = time.monotonic()
        stages_advanced, warnings_advanced = world.catch_up_zone(now)
        if stages_advanced or warnings_advanced:
            self.capture.record('world_probe', action='zone_schedule_catchup', synthetic=True,
                                remote=remote, stages_advanced=stages_advanced,
                                warnings_advanced=warnings_advanced)
        snapshot = world.stage_snapshot(now)
        warning = world.warning_snapshot(now)
        state['resume_world_sent'] = True
        if snapshot is not None:
            body, timing = snapshot
            self.send_application(d, remote, state, 0x481, body)
            self.capture.record('world_probe', action='zone_stage_resume', synthetic=True,
                                remote=remote, **timing)
        if warning is not None:
            body, timing = warning
            self.send_application(d, remote, state, 0x481, body)
            self.capture.record('world_probe', action='zone_warning_resume', synthetic=True,
                                remote=remote, **timing)

    def restore_resume_inventory(self, d, remote, state):
        """Однократное согласование известных слотов/HP после потери финальных RPC."""
        if state.get('resume_inventory_sent'):
            return
        weapon, world, medical = state.get('weapon'), state.get('world'), state.get('medical')
        if not isinstance(weapon, WeaponState):
            return
        self.cancel_dead_actions(state, remote)
        if weapon.pending_reload:
            # Native361: первый финальный4A0 удаляет совпавшее предсказание
            # reload, но не публикует магазин после старого handoff snapshot.
            pending = weapon.pending_reload
            state['resume_reload_reconcile'] = (pending['slot'], pending['uid'])
        now = time.monotonic()
        if medical is not None:
            _, events = medical.poll(now)
            for event in events:
                self.capture.record('medical_probe', synthetic=True, remote=remote, **event)
        packets = weapon.reconcile_inventory()
        if 'death_parcels' in state:
            packets.extend(state['death_parcels'].reconcile(state['actor_uid']))
        if world is not None:
            packets.append((0x1069, encode_health(weapon.actor_uid, world.hp)))
        if (medical is not None and medical.pending is None and medical.completed_at is not None
                and 0 <= now - medical.completed_at <= 30 and not weapon.pending_reload):
            packets.append(medical.finish_status())
        if world is not None and getattr(world, 'dead', False):
            # Новому transport повторяем актуальное состояние смерти, не эффект урона.
            packets.append(world.death_message())
        # Каждая короткая рамка отдельная: не добавляем крупный snapshot при handoff.
        for command, payload in packets:
            self.send_application(d, remote, state, command, payload)
        state['resume_inventory_sent'] = True
        self.capture.record('gameplay_resume_inventory_sync', synthetic=True, remote=remote,
                            gun_count=len(weapon.guns), medical_stacks=dict(weapon.medical),
                            hp=getattr(world, 'hp', None), messages=len(packets))

    def reconcile_resume_reload(self, remote, state, packets, events):
        """Один повтор финального магазина только для reload, пережившей handoff."""
        marker = state.get('resume_reload_reconcile')
        weapon = state.get('weapon')
        if marker is None or not isinstance(weapon, WeaponState):
            return packets
        if weapon.pending_reload is not None:
            return packets
        state.pop('resume_reload_reconcile', None)
        slot, uid = marker
        gun = weapon.guns.get(slot)
        if (gun is None or gun.uid != uid or not any(
                event.get('action') == 'reload' and event.get('slot') == slot
                for event in events)):
            return packets
        final = (0x4a0, weapon.ammunition_sync(slot=slot))
        if final not in packets:
            return packets
        self.capture.record('gameplay_resume_reload_reconcile', synthetic=True,
                            remote=remote, slot=slot, clip=gun.clip, counter=0,
                            repeats=1, experimental=True)
        # Новый application id; транспортный duplicate клиент отбрасывает.
        return packets + [final]

    def accept_movement(self, d, remote, state, payload):
        """Учебный бюджет пути до изменения world/loot-позиции; дефолт отключён."""
        limits = getattr(self.world_fixture, 'movement_limits', None)
        if limits is None:
            return True
        now = time.monotonic()
        movement = decode_move_request(payload)
        guard = state.get('movement_guard')
        if guard is None:
            anchor = state.get('scene_position')
            if anchor is None:
                self.capture.record('movement_validation_awaiting_anchor', remote=remote,
                                    reason='missing_server_anchor', experimental=True)
                return False
            guard = state['movement_guard'] = MovementState(limits, anchor, now)
        accepted, info = guard.accept(movement, now)
        self.capture.record('movement_validation_accepted' if accepted else 'movement_validation_rejected',
                            remote=remote, **info)
        if accepted:
            return True
        # Отказ не меняет anchor/budget. Native27 возвращает позицию, но не
        # регистрируется как новый разрешённый teleport и не выдаёт свежий burst.
        template = state.get('scene_position_sync')
        if isinstance(template, bytes) and len(template) == 40:
            correction = bytearray(template)
            struct.pack_into('>Q3i', correction, 0, state['actor_uid'], *guard.position)
            struct.pack_into('>I', correction, 31, int((now-self.started)*25)&0xffffffff)
            self.send_application(d, remote, state, 0x27, bytes(correction))
            self.capture.record('movement_validation_correction', remote=remote,
                                position=guard.position, command='0x27', experimental=True)
        return False

    def register_fixture_entity(self, state, command, payload):
        """Регистрировать только заранее описанный лут сцены или live-опыта."""
        if command == 0x27 and len(payload) == 40 and struct.unpack_from('>Q', payload)[0] == state['actor_uid']:
            state['scene_position'] = struct.unpack_from('>3i', payload, 8)
            state.setdefault('match_statistics', MatchStatistics()).reset_anchor(state['scene_position'])
            state['scene_position_sync'] = bytes(payload)
            if 'movement_guard' in state:
                state['movement_guard'].reset(state['scene_position'], time.monotonic())
            if 'weapon' in state:
                state['weapon'].update_position(state['scene_position'])
            if 'world' in state:
                event = state['world'].update_position(state['scene_position'], time.monotonic())
                if event:
                    self.capture.record('world_probe', synthetic=True, **event)
        state.setdefault('vehicles', VehicleState(state['actor_uid'],
                         None if getattr(self, 'shared_evacuation', None) else self.evacuation_delay,
                         survivor_name=state.get('actor_display_name', getattr(self, 'room_display_name', 'LOCAL')) if self.evacuation_delay is not None else None,
                         result_fixture=self.evacuation_result_fixture,
                         room_uid=state.get('room_uid', 1),
                         statistics=state.setdefault('match_statistics', MatchStatistics()),
                         diagnostic_pellet_damage=getattr(self, 'diagnostic_vehicle_pellet_damage', None))).register(command, payload)
        if getattr(self,'shared_vehicles',None):
            self.shared_vehicles.register(state,command,payload)
        if self.parcel_fixture:
            if 'parcels' not in state:
                state['parcels'] = make_parcel_state(self.parcel_fixture)
            state['parcels'].register(command, payload)
        if command != 0x821 or self.weapon_fixture is None or len(payload) < 12:
            return
        uid = struct.unpack_from('>Q', payload, 4)[0]
        if uid not in {item.entity_uid for item in self.weapon_fixture.all_loot}:
            return
        state.setdefault('loot_spawned_uids', set()).add(uid)
        primary = self.weapon_fixture.loot
        state['loot_spawned'] = bool(primary and uid == primary.entity_uid) or state.get('loot_spawned', False)
        if 'weapon' in state:
            state['weapon'].loot_available = state['loot_spawned']
            state['weapon'].available_loot.add(uid)

    def emit_peer_avatars(self,outputs,events):
        for recipient,messages in outputs:
            anchor = recipient.get('peer_avatar_anchor')
            if (anchor and recipient.get('auth_sent') and recipient.get('room_sent')
                    and not recipient.get('match_finished') and not recipient.get('transport_retired')
                    and time.monotonic()-anchor[2] <= 5):
                self.send_application_batch(anchor[0],anchor[1],recipient,messages)
        for event in events:
            self.capture.record('peer_avatar_probe',synthetic=True,shared_inventory=False,**event)

    def emit_shared_loot(self, outputs):
        for recipient, messages in outputs:
            anchor = recipient.get('peer_avatar_anchor')
            if (anchor and recipient.get('auth_sent') and recipient.get('room_sent')
                    and not recipient.get('match_finished') and not recipient.get('transport_retired')
                    and time.monotonic()-anchor[2] <= 5):
                self.send_application_batch(anchor[0], anchor[1], recipient, messages)
                self.capture.record('shared_loot_broadcast', synthetic=True,
                                    account_uid=hex(recipient['actor_uid']),
                                    commands=[hex(code) for code, _ in messages])

    def send_application(self,d,remote,state,command,payload):
        if getattr(self, 'shared_loot', None) and command == 0x821:
            payload = self.shared_loot.filter_spawn(state, payload)
            if payload is None:
                return
        stamp=int((time.monotonic()-self.started)*25)&0xffffffff
        plain=struct.pack('>IHI',stamp,command,command)+payload
        state['frame_seq']+=1
        self.send_frame(d,remote,state,0x4013,state['frame_seq'],plain,bytes(4),applications=(command,))

    def send_application_batch(self, d, remote, state, messages):
        """Прикладные сообщения одной команды опыта в одном TGCP-заголовке.

        Первичные4013: extra[3] задаёт количество BE16-длин, последняя
        длина определяется остатком. Предел не даёт разрастаться рамке.
        """
        stamp = int((time.monotonic()-self.started)*25) & 0xffffffff
        packets = []
        for code, payload in messages:
            if getattr(self, 'shared_loot', None) and code == 0x821:
                payload = self.shared_loot.filter_spawn(state, payload)
                if payload is None:
                    continue
            if not 0 <= code <= 65535 or len(payload) > 16384:
                raise ValueError('Прикладное сообщение вне пределов опыта')
            packets.append(struct.pack('>IHI', stamp, code, code) + payload)
        batch, size = [], 0
        for packet in packets + [None]:
            if batch and (packet is None or size + len(packet) > 32768 or len(batch) == 64):
                extra = bytes([0, 0, 0, len(batch)-1]) + b''.join(
                    struct.pack('>H', len(part)) for part in batch[:-1])
                state['frame_seq'] += 1
                self.send_frame(d, remote, state, 0x4013, state['frame_seq'], b''.join(batch), extra,
                                applications=tuple(struct.unpack_from('>H',part,4)[0] for part in batch))
                batch, size = [], 0
            if packet is not None:
                batch.append(packet)
                size += len(packet)

    def send_clock(self,d,remote,state):
        elapsed=time.monotonic()-self.started
        # Decoder 140bd40c0: четыре BE32; третье слово native задаёт 40 мс/тик.
        payload=struct.pack('>4I',int(elapsed*25)&0xffffffff,int(elapsed*50)&0xffffffff,40,2)
        self.send_application(d,remote,state,0x1f57,payload)
        self.capture.record('clock_tick',synthetic=True,tick_duration_ms=40,remote=remote)


async def main(args):
    capture = Capture(args.output)
    loop = asyncio.get_running_loop()
    stop = asyncio.Event()
    # Proactor loop Windows не поддерживает add_signal_handler; Ctrl+C
    # отменяет main через asyncio.run и выполняет блок finally ниже.
    if sys.platform != 'win32':
        for signum in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(signum, stop.set)
    rules = load_scene_rules(args.scene_rules)
    weapon_path = getattr(args, 'weapon_config', None)
    weapon_fixture = WeaponFixture.load(weapon_path) if weapon_path else None
    catalog_path = getattr(args, 'loot_catalog', None)
    loot_catalog = None
    if catalog_path:
        if not weapon_fixture or not weapon_fixture.all_loot:
            raise ValueError('loot-catalog требует weapon-config с проверенным ground821')
        loot_catalog = LootCatalog.load(catalog_path, weapon_fixture.all_loot[0].entity)
        loot_catalog.validate_fixture(weapon_fixture)
    world_path = getattr(args, 'world_config', None)
    world_fixture = WorldFixture.load(world_path) if world_path else None
    actor_path = getattr(args, 'actor_config', None)
    actor_fixture = load_actor_fixtures(actor_path) if actor_path else None
    if actor_fixture and any(f.attack for f in actor_fixture) and world_fixture is None:
        raise ValueError('Экспериментальная атака бота требует world-config для общих HP')
    parcel_path = getattr(args, 'parcel_config', None)
    parcel_fixture = load_parcel_fixture(parcel_path, weapon_fixture, loot_catalog) if parcel_path else None
    result_path = getattr(args, 'evacuation_result_config', None)
    result_fixture = EvacuationUIFixture.load(result_path) if result_path else None
    environment_path=getattr(args,'environment_config',None)
    environment_fixture=EnvironmentFixture.load(environment_path) if environment_path else None
    peer_avatar_fixture = ActorFixture.load(args.peer_avatar_config) if getattr(args,'peer_avatar_config',None) else None
    transport, endpoint = await loop.create_datagram_endpoint(lambda:Endpoint(capture,args.handshake,args.ident,args.grant,args.auth,args.room_template,rules,args.scene_clock,args.selection_seconds,weapon_fixture,getattr(args,'live_commands',None),world_fixture,actor_fixture,getattr(args,'evacuation_delay_seconds',None),parcel_fixture,result_fixture,loot_catalog,environment_fixture,getattr(args,'reliable_udp',False),getattr(args,'idle_handoff',False),getattr(args,'diagnostic_vehicle_pellet_damage',None),peer_avatar_fixture,getattr(args,'shared_ground_loot',False),getattr(args,'shared_world_clock',False),getattr(args,'shared_peer_health',False),getattr(args,'peer_avatar_trajectories',False),getattr(args,'peer_spectator',False),getattr(args,'shared_evacuation',False),getattr(args,'shared_vehicles',False),getattr(args,'peer_equipment',False),getattr(args,'peer_pellet_damage',None),getattr(args,'shared_death_loot',False),door_fixture=DoorFixture.load(args.door_config) if getattr(args,'door_config',None) else None,breakable_fixture=BreakableFixture.load(args.breakable_config) if getattr(args,'breakable_config',None) else None), local_addr=('127.0.0.1',args.port))
    try:
        await asyncio.wait_for(stop.wait(),args.duration)
    except asyncio.TimeoutError:
        pass
    finally:
        endpoint.stop_retries()
        endpoint.stop_peer_timer()
        transport.close()
        capture.record('stopped', sessions=len(endpoint.sessions))
        capture.events.close()


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--port',type=int,default=18001)
    p.add_argument('--duration',type=float,default=330)
    p.add_argument('--reliable-udp',action='store_true',help='Экспериментальные ACK/retry и ограниченная входная сборка')
    p.add_argument('--diagnostic-vehicle-pellet-damage', type=int, choices=range(1,5001), metavar='1..5000', help='Учебный урон по корпусу102/109; исходная формула не восстановлена')
    p.add_argument('--idle-handoff',action='store_true',help='Экспериментальный перенос послеAUTH/RELAY при5..30с idle; требует reliable-udp')
    p.add_argument('--handshake',action='store_true',help='Экспериментальный ответ 1002 с новым локальным ключом')
    p.add_argument('--ident',action='store_true',help='Экспериментальный 2002 с identity из текущего клиента')
    p.add_argument('--grant',action='store_true',help='Экспериментальный 6002; требует ident и handshake')
    p.add_argument('--auth',action='store_true',help='Экспериментальный успешный CONN_AUTH_RSP после согласованного synthetic запроса')
    p.add_argument('--room-template',type=Path,help='Явное тело room-ответа; локальные идентификаторы подставляются из запроса')
    p.add_argument('--scene-rules',type=Path,help='JSON одноразовых ответов на команды клиента после входа в комнату')
    p.add_argument('--scene-clock',action='store_true',help='Локальные TIME_SYN_CMD/CUR_TICK_TEL после уведомления загрузки; 40 мс/тик')
    p.add_argument('--selection-seconds',type=int,help='Экспериментальная готовность 1/1 и таймер выбора; требует scene-clock')
    p.add_argument('--weapon-config',type=Path,help='Экспериментальная Citori, reload и опциональный pickup12ga; JSON с проверенными fixture')
    p.add_argument('--breakable-config', type=Path, help='Разрушение однокомпонентных сущностей16010; учебное подтверждение')
    p.add_argument('--door-config', type=Path, help='Обратимые двери16010; учебный радиус/одиночное состояние')
    p.add_argument('--loot-catalog',type=Path,help='Явный каталог поддержанного лута; собственная выдача по радиусу, требует weapon-config')
    p.add_argument('--live-commands',type=Path,help='Локальный JSON одноразовых команд после AUTH/room; диагностический опыт')
    p.add_argument('--peer-avatar-config',type=Path,help='Аватары комнаты и выбранные позы; общий лут/HP отдельными флагами')
    p.add_argument('--shared-evacuation',action='store_true',help='Учебные четыре общих места/итог комнаты; all_boarded интерпретация, требует shared-peer-health/evacuation-result-config/delay')
    p.add_argument('--shared-vehicles',action='store_true',help='Учебные общие места/driver ownership/transform102/109, одноместный203; требует shared-peer-health')
    p.add_argument('--peer-spectator',action='store_true',help='Учебное наблюдение живого участника после смерти; требует shared-peer-health')
    p.add_argument('--peer-avatar-trajectories',action='store_true',help='Диагностические плавные SC25; требует peer-avatar-config/scene-clock')
    p.add_argument('--shared-ground-loot',action='store_true',help='Общий наземный лут комнаты; без каталога и контейнеров; диагностический reset после последнего выхода')
    p.add_argument('--shared-world-clock',action='store_true',help='Общий календарь зон текущей комнаты; требует shared-ground-loot/world-config')
    p.add_argument('--shared-peer-health',action='store_true',help='Репликация HP участников через1069/533; требует peer-avatar-config/world-config/shared-ground-loot')
    p.add_argument('--actor-config',type=Path,help='Одна мишень/бот либо группа1..10 пассивных мишеней; требует weapon-config')
    p.add_argument('--parcel-config',type=Path,help='Экспериментальный аирдроп с содержимым 12ga; требует weapon-config')
    p.add_argument('--evacuation-delay-seconds',type=float,help='Одиночный опыт: отлёт через 2..60 секунд после посадки')
    p.add_argument('--evacuation-result-config',type=Path,help='Явный диагностический мост к газете с архивной статистикой; только после посадки')
    p.add_argument('--world-config',type=Path,help='Экспериментальный пресет зимних зон и опасного участка; требует weapon-config')
    p.add_argument('--environment-config',type=Path,help='Явные начальные час суток/температура зимней карты; требует weapon-config')
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--shared-death-loot',action='store_true',help='Opt-in общий остаток пакетов погибших; требует shared-peer-health')
    p.add_argument('--peer-pellet-damage',type=int,choices=range(1,101),metavar='1..100',help='Opt-in учебный PvP комнаты; требует shared-peer-health и death_on_zero/hp_floor0')
    p.add_argument('--peer-equipment',action='store_true',help='Опциональная текущая экипировка удалённых игроков через547; требуетshared-peer-health')
    args = p.parse_args()
    if args.peer_equipment and not args.shared_peer_health:
        p.error('peer-equipment требует shared-peer-health')
    if args.shared_vehicles and not args.shared_peer_health:
        p.error('shared-vehicles требует shared-peer-health')
    if args.shared_evacuation and (not args.shared_peer_health or not args.evacuation_result_config or args.evacuation_delay_seconds is None):
        p.error('shared-evacuation требует shared-peer-health/evacuation-result-config/evacuation-delay-seconds')
    if args.peer_spectator and not args.shared_peer_health:
        p.error('peer-spectator требует shared-peer-health')
    if args.peer_avatar_trajectories and (not args.peer_avatar_config or not args.scene_clock):
        p.error('peer-avatar-trajectories требует peer-avatar-config и scene-clock')
    if args.shared_peer_health and (not args.peer_avatar_config or not args.world_config or not args.shared_ground_loot):
        p.error('shared-peer-health требует peer-avatar-config/world-config/shared-ground-loot')
    if args.shared_world_clock and (not args.shared_ground_loot or not args.world_config):
        p.error('shared-world-clock требует shared-ground-loot и world-config')
    if args.shared_ground_loot and (not args.weapon_config or args.loot_catalog or args.parcel_config):
        p.error('shared-ground-loot требует weapon-config без loot-catalog/parcel-config')
    if ((args.ident and not args.handshake) or (args.grant and not args.ident)
            or (args.auth and not args.grant) or (args.room_template and not args.auth)
            or ((args.scene_rules or args.scene_clock or args.live_commands) and not args.room_template)):
        p.error('Нужна полная цепочка handshake → ident → grant → auth → room → scene-rules')
    if args.idle_handoff and not args.reliable_udp:
        p.error('idle-handoff требует reliable-udp')
    if args.evacuation_delay_seconds is not None and not 2 <= args.evacuation_delay_seconds <= 60:
        p.error('evacuation-delay-seconds должен быть 2..60')
    if args.evacuation_result_config and (args.evacuation_delay_seconds is None or not args.room_template):
        p.error('evacuation-result-config требует room-template и evacuation-delay-seconds')
    if args.actor_config and not args.weapon_config:
        p.error('actor-config требует weapon-config')
    if args.breakable_config and (not args.weapon_config or not args.scene_clock):
        p.error('breakable-config требует weapon-config и scene-clock')
    if args.door_config and (not args.weapon_config or not args.scene_clock):
        p.error('door-config требует weapon-config и scene-clock')
    if args.loot_catalog and not args.weapon_config:
        p.error('loot-catalog требует weapon-config')
    if args.parcel_config and not args.weapon_config:
        p.error('parcel-config требует weapon-config')
    if args.environment_config and not args.weapon_config:
        p.error('environment-config требует weapon-config')
    if args.world_config and (not args.weapon_config or not args.scene_clock):
        p.error('world-config требует weapon-config и scene-clock')
    if args.selection_seconds is not None and (not args.scene_clock or not 1<=args.selection_seconds<=120):
        p.error('selection-seconds требует scene-clock и значение 1..120')
    if args.weapon_config and (not args.scene_rules or args.selection_seconds is None):
        p.error('weapon-config требует scene-rules и selection-seconds')
    try:
        asyncio.run(main(args))
    except KeyboardInterrupt:
        pass
