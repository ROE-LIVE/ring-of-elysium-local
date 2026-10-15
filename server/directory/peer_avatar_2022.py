"""Опциональные аватары подключений; диагностические HP и выбранные позы2022.

Account UID заголовка отделён от назначенного Unit UID отображаемой сущности.
Используется проверенный диагностический профиль; внешность не профиль аккаунта.
"""
import math
import struct
from world_probe_2022 import encode_health
from peer_motion_2022 import encode_peer_trajectory, encode_peer_stop
from peer_equipment_2022 import encode_peer_equipment


class PeerAvatarRooms:
    def __init__(self,fixture,replicate_health=False,replicate_trajectories=False,replicate_equipment=False):
        self.fixture = fixture
        self.replicate_health = replicate_health
        self.replicate_trajectories = replicate_trajectories
        self.replicate_equipment = replicate_equipment
        self.members = {}
        self.next_avatar = 0x2040000100001
        self.pose_bootstrap = {}

    def packets(self,member,tick):
        uid,position = member['avatar'],member['position']
        listing,profile = bytearray(self.fixture.listing),bytearray(self.fixture.profile)
        struct.pack_into('>3i',listing,1,*position)
        struct.pack_into('>Q',listing,14,uid)
        struct.pack_into('>Q',profile,8,uid)
        struct.pack_into('>3i',profile,1051,*position)
        struct.pack_into('>I',profile,1064,tick)
        packets = [(0x565,bytes(listing)),(0xbe7,bytes(profile))]
        world = member['state'].get('world')
        if self.replicate_equipment and 'weapon' in member['state']:
            packets.append((0x547,encode_peer_equipment(member['state']['weapon'],uid,
                                                       bool(world and world.dead))))
        if self.replicate_health and world is not None:
            packets.append((0x1069, encode_health(uid, world.hp)))
            if world.dead:
                packets.append((0x533, struct.pack('>IQ', 0, uid)))
        return packets

    def equipment(self, now):
        """Изменения и handoff доставляются только другим живым транспортам комнаты."""
        outputs, events = [], []
        if not self.replicate_equipment:
            return outputs, events
        keys = set(self.members)
        for key, member in self.members.items():
            state = member['state']
            if 'weapon' not in state or state.get('match_finished') or state.get('transport_retired'):
                continue
            world = state.get('world')
            body = encode_peer_equipment(state['weapon'],member['avatar'],bool(world and world.dead))
            receipts = member.setdefault('equipment_targets', {})
            for expired in set(receipts)-keys:
                del receipts[expired]
            recipients = 0
            for other_key,other in self.members.items():
                target = other['state'];anchor = target.get('peer_avatar_anchor')
                if (other_key[0] != key[0] or other_key == key or not anchor
                        or now-anchor[2] > 5 or not target.get('auth_sent')
                        or not target.get('room_sent') or target.get('match_finished')
                        or target.get('transport_retired')):
                    continue
                receipt = (id(target),body)
                if receipts.get(other_key) != receipt:
                    outputs.append((target,[(0x547,body)]))
                    receipts[other_key] = receipt
                    recipients += 1
            if recipients:
                events.append(dict(action='peer_avatar_equipment',account_uid=hex(key[1]),
                                   avatar_uid=hex(member['avatar']),hand_slot=state['weapon'].hand_slot,
                                   recipients=recipients))
        return outputs, events

    def health(self, state, now=None):
        """Серверные HP одного игрока: own AccountUID и remote UnitUID различны."""
        if not self.replicate_health or 'world' not in state:
            return [], []
        key = (state['room_uid'], state['actor_uid'])
        member = self.members.get(key)
        if member is None or member['state'] is not state:
            return [], []
        world = state['world']
        current = (world.hp, world.dead)
        changed = member.get('last_health') != current
        member['last_health'] = current
        uid = member['avatar']
        packets = [(0x1069, encode_health(uid, world.hp))]
        if world.dead:
            packets.append((0x533, struct.pack('>IQ', 0, uid)))
        receipts = member.setdefault('health_targets', {})
        outputs = []
        for other_key, other in self.members.items():
            if other_key[0] != key[0] or other_key == key:
                continue
            target = other['state']
            # Не считать пропущенный stale transport получателем обновления.
            # После обычного heartbeat, даже без RELAY, вернём текущие HP.
            if now is not None:
                anchor = target.get('peer_avatar_anchor')
                if (not anchor or now-anchor[2] > 5 or not target.get('auth_sent')
                        or not target.get('room_sent') or target.get('match_finished')
                        or target.get('transport_retired')):
                    continue
            receipt = (id(target), *current)
            if receipts.get(other_key) != receipt:
                outputs.append((target, packets))
                receipts[other_key] = receipt
        if not changed and not outputs:
            return [], []
        return outputs, [dict(action='peer_avatar_health', account_uid=hex(key[1]),
                              avatar_uid=hex(uid), hp=world.hp, dead=world.dead,
                              recipients=len(outputs))]

    def admit(self,state,tick,now=None):
        account,room = state['actor_uid'],state['room_uid']
        if not 0 < account < 2**64 or not 0 < room < 2**64:
            raise ValueError('Нужны account UID и room UID')
        key = (room,account)
        previous = self.members.get(key)
        if previous:
            if previous['state'] is state:
                return [],[]
            if not state.get('gameplay_resumed'):
                return [],[dict(action='peer_avatar_duplicate_account',account_uid=hex(account),room_uid=hex(room))]
            previous['state'] = state
            member = previous
        else:
            if sum(k[0]==room for k in self.members) >= 8:
                return [],[dict(action='peer_avatar_room_limit',room_uid=hex(room))]
            member = dict(avatar=self.next_avatar,state=state,
                          position=tuple(state.get('last_movement_position',state['scene_position'])),last_emit=-10,pose=0)
            # Учебная задержка создания remote модели, не native ACK готовности.
            if now is not None:
                member['spectator_ready_at'] = now + 2
            self.next_avatar += 1
            self.members[key] = member
        outputs = []
        for other_key,other in self.members.items():
            if other_key[0] == room and other_key != key:
                outputs.append((other['state'],self.packets(member,tick)))
                outputs.append((state,self.packets(other,tick)))
                if now is not None:
                    # Два ограниченных повтора после async создания моделей.
                    self.pose_bootstrap[(key,other_key)] = (now+1, 2)
                    self.pose_bootstrap[(other_key,key)] = (now+1, 2)
        return outputs,[dict(action='peer_avatar_member',account_uid=hex(account),room_uid=hex(room),
                             avatar_uid=hex(member['avatar']),other_members=len(outputs)//2)]

    def movement_packet(self,member,tick,position=None):
        payload = bytearray(self.fixture.movement)
        struct.pack_into('>Q3i',payload,0,member['avatar'],*(position or member['position']))
        struct.pack_into('>I',payload,27,member.get('pose',0))
        if 'motion_sequence' in member:
            struct.pack_into('>I',payload,23,member['motion_sequence'])
        struct.pack_into('>I',payload,31,tick)
        return (0x27,bytes(payload))

    def pose_snapshots(self,now,tick):
        """Поздняя модель получает текущую позу, а не потерянный ранний27."""
        outputs,events = [],[]
        for pair,(due,remaining) in list(self.pose_bootstrap.items()):
            source,target = (self.members.get(key) for key in pair)
            if source is None or target is None:
                del self.pose_bootstrap[pair]
                continue
            if now < due:
                continue
            world = source['state'].get('world')
            if world is None or not world.dead:
                packets = [self.movement_packet(source,tick)]
                if self.replicate_equipment and 'weapon' in source['state']:
                    packets.insert(0,(0x547,encode_peer_equipment(source['state']['weapon'],source['avatar'])))
                outputs.append((target['state'],packets))
                events.append(dict(action='peer_avatar_pose_snapshot',avatar_uid=hex(source['avatar']),
                                   pose=source.get('pose',0),recipient=hex(pair[1][1])))
            if remaining == 1:
                del self.pose_bootstrap[pair]
            else:
                self.pose_bootstrap[pair] = (now+2,remaining-1)
        return outputs,events

    def settle_motion(self,now,tick):
        """Завершить предсказанную очередь одним авторитетным неподвижным якорем.

        Это политика диагностического peer, а не найденный серверный алгоритм.
        Последний узел SC25 имеет prediction marker; без нового якоря скорость
        анимации может остаться ненулевой после прекращения C2S.
        """
        outputs,events = [],[]
        if not self.replicate_trajectories:
            return outputs,events
        for key,member in self.members.items():
            due = member.get('motion_settle_at')
            if due is None or now < due:
                continue
            member.pop('motion_settle_at',None)
            state = member['state']
            world = state.get('world')
            if (state.get('match_finished') or state.get('transport_retired')
                    or (world is not None and world.dead)):
                continue
            sequence = (member['motion_sequence']+1)&0xffffffff
            body = encode_peer_stop(member['avatar'],member['position'],sequence,tick,
                                    member.get('pose',0),member['motion_direction'])
            member['motion_sequence'] = sequence
            for other_key,other in self.members.items():
                if other_key[0] == key[0] and other_key != key:
                    outputs.append((other['state'],[(0x25,body)]))
            events.append(dict(action='peer_avatar_motion_settle',avatar_uid=hex(member['avatar']),
                               position=member['position'],motion_sequence=sequence))
        return outputs,events

    def move(self,state,position,tick,now,movement=None):
        if len(position)!=3 or any(type(v) not in (int,float) or not math.isfinite(v) or abs(v)>10000000 for v in position):
            raise ValueError('Неверная позиция peer avatar')
        key = (state['room_uid'],state['actor_uid'])
        member = self.members.get(key)
        if member is None or member['state'] is not state:
            return [],[]
        member['position'] = tuple(round(v) for v in position)
        packets,transitions,unknown = [],[],[]
        trajectory,trajectory_error = False,None
        # Это подтверждённое подмножество событий C2S2a, а не полная enum игры.
        # bytes[1]==0 означает отсутствие перехода; стоя имеет код1.
        mapping = {1:0,2:1,3:2,22:3,4:9}
        if movement is not None:
            for point in movement['points']:
                event = point['bytes'][1]
                if event in mapping:
                    pose = mapping[event]
                    if member.get('pose',0) != pose:
                        member['pose'] = pose
                        packets.append(self.movement_packet(member,tick,point['position']))
                        transitions.append(dict(client_event=event,server_status=pose))
                elif event:
                    unknown.append(event)
        if now-member['last_emit'] >= .2 or packets:
            member['last_emit'] = now
            final = None
            if self.replicate_trajectories and movement is not None and member.get('pose',0) in (0,1,2):
                sequence = (member.get('motion_sequence',struct.unpack_from('>I',self.fixture.movement,23)[0])+1)&0xffffffff
                try:
                    body = encode_peer_trajectory(member['avatar'],movement,sequence,tick)
                except (ValueError,KeyError,TypeError,OverflowError,struct.error) as error:
                    trajectory_error = str(error)
                else:
                    member['motion_sequence'] = sequence
                    member['motion_direction'] = movement['floats']
                    member['motion_settle_at'] = now+.35
                    final,trajectory = (0x25,body),True
            if final is None:
                member.pop('motion_settle_at',None)
                final = self.movement_packet(member,tick)
            if not packets or packets[-1] != final:
                packets.append(final)
        outputs = [(other['state'],packets) for other_key,other in self.members.items()
                   if other_key[0]==key[0] and other_key!=key] if packets else []
        events = [dict(action='peer_avatar_move',account_uid=hex(key[1]),avatar_uid=hex(member['avatar']),
                       position=member['position'],recipients=len(outputs),pose_replicated=True,
                       server_status=member.get('pose',0),transitions=transitions,unknown_pose_events=unknown,
                       trajectory_replicated=trajectory,trajectory_fallback=trajectory_error)] if outputs or unknown else []
        return outputs,events

    def detach(self, state, reason):
        """SC583/8B удаляет native actor/cache2022; старый RELAY не удаляет новый."""
        key = (state.get('room_uid'), state.get('actor_uid'))
        member = self.members.get(key)
        if member is None or member['state'] is not state:
            return [], []
        del self.members[key]
        payload = struct.pack('>Q', member['avatar'])
        outputs = [(other['state'], [(0x583, payload)]) for other_key, other in self.members.items()
                   if other_key[0] == key[0]]
        return outputs, [dict(action='peer_avatar_leave', account_uid=hex(key[1]),
                              avatar_uid=hex(member['avatar']), reason=reason,
                              recipients=len(outputs))]
