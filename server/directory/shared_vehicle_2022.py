"""Учебные общие места/transform для102/109 и одноместного203.

Физика остаётся клиентской; сервер проверяет владельца водительского места,
комнату и порядок tick. Исходные столкновения/lag compensation не заявлены.
"""
import struct
import math


class SharedVehicleRooms:
    capacities = {102: 2, 109: 2, 203: 1}

    def __init__(self):
        self.rooms = {}

    def room(self, state):
        uid = state['room_uid']
        if uid not in self.rooms and len(self.rooms) >= 32:
            raise ValueError('Лимит общих транспортных комнат')
        return self.rooms.setdefault(uid, dict(members={}, vehicles={}, seats={},
                motion={}, ticks={}, admitted=False, snapshots={}, member_epochs={},
                rotations={}, owners={}, owner_updates=set(), seat_releases=[]))

    def register(self, state, command, payload):
        """Поздняя начальная fixture не возвращает старые HP/координаты."""
        if command != 0x654b or len(payload) not in (79,164):
            return payload
        uid,configuration,status,hp = struct.unpack_from('>QIII',payload)
        if configuration not in self.capacities or not uid:
            return payload
        room = self.room(state)
        vehicle = room['vehicles'].get(uid)
        if vehicle is None:
            vehicle = state['vehicles'].vehicles.get(uid)
            if vehicle is None:
                return payload
            room['vehicles'][uid] = vehicle
            room['rotations'][uid] = payload[33:49]
        elif vehicle['configuration'] != configuration:
            state['vehicles'].vehicles[uid]=vehicle
            raise ValueError('Повторный UID другой конфигурации транспорта')
        state['vehicles'].vehicles[uid] = vehicle
        body=bytearray(payload)
        struct.pack_into('>IIiii',body,12,vehicle['status'],vehicle['hp'],*vehicle['position'])
        return bytes(body)

    def sync(self, avatars, now):
        grouped={}
        for (room_uid,account),member in avatars.members.items():
            state=member['state']
            if not state.get('transport_retired') and not state.get('match_finished'):
                grouped.setdefault(room_uid,{})[account]=member
        for room_uid,room in list(self.rooms.items()):
            members=grouped.get(room_uid,{})
            if room['admitted'] and not members:
                del self.rooms[room_uid]
                continue
            previous=room['member_epochs'];previous_members=room['members'];room['members']=members
            if members:room['admitted']=True
            for account,member in members.items():
                state=member['state'];vehicles=state.get('vehicles')
                if vehicles is not None:
                    for uid,vehicle in room['vehicles'].items():
                        if uid in vehicles.vehicles:vehicles.vehicles[uid]=vehicle
                if previous.get(account) != id(state):
                    room['snapshots'][account]=(id(state),now+2,2)
            room['member_epochs']={account:id(member['state']) for account,member in members.items()}
            for uid,occupants in room['seats'].items():
                for seat,account in list(occupants.items()):
                    member=members.get(account);state=member['state'] if member else None
                    world=state.get('world') if state else None
                    vehicles=state.get('vehicles') if state else None
                    if (state is None or world is not None and world.dead
                            or vehicles is None or vehicles.seated != uid or vehicles.seat != seat):
                        source=member or previous_members.get(account)
                        if source:
                            room['seat_releases'].append((uid,seat,account,source['avatar']))
                        del occupants[seat]
            for uid,occupants in room['seats'].items():
                owner=occupants.get(1,0)
                if room['owners'].get(uid,0)!=owner:
                    room['owners'][uid]=owner;room['owner_updates'].add(uid)
            room['ticks']={key:value for key,value in room['ticks'].items()
                           if key[0] in members and id(members[key[0]]['state'])==key[1]}

    @staticmethod
    def translated(command, payload, unit):
        offsets={0x6542:16,0x6544:12,0x6548:8}
        if command not in offsets:return payload
        body=bytearray(payload);struct.pack_into('>Q',body,offsets[command],unit)
        return bytes(body)

    def fanout(self, room, state, packets):
        member=room['members'].get(state['actor_uid'])
        if member is None:return []
        return [(other['state'],[(code,self.translated(code,body,member['avatar']))
                                for code,body in packets])
                for other in room['members'].values() if other['state'] is not state]

    @staticmethod
    def owner_packet(room, uid, recipient):
        """Primary decoder140C9AAA0:52B; owner переводится отдельно от адресата."""
        owner=room['seats'].get(uid,{}).get(1,0)
        member=room['members'].get(owner)
        actor=owner if owner==recipient['actor_uid'] else member['avatar'] if member else 0
        motion=room['motion'].get(uid)
        position=motion[13:26] if motion else struct.pack('>iiiB',*room['vehicles'][uid]['position'],0)
        rotation=motion[53:69] if motion else room['rotations'].get(uid,struct.pack('>4f',0,0,0,1))
        # Начальный quaternion fixture может быть нулевым в model test;
        # native ориентация поступает с первым MOVE_REQ.
        values=struct.unpack('>4f',rotation)
        if not all(math.isfinite(v) for v in values) or sum(v*v for v in values)<1e-12:
            rotation=struct.pack('>4f',0,0,0,1)
        return (0x656d,struct.pack('>QIQ',uid,0,actor)+position+rotation+b'\0\0\0')

    def handle(self, state, command, payload, now):
        room=self.rooms.get(state['room_uid']);local=state['vehicles']
        uid=(struct.unpack_from('>Q',payload)[0] if command in (0x6541,0x6549)
             and len(payload)>=8 else local.seated)
        if command==0x11de and len(payload)>=12:
            uid=struct.unpack_from('>Q',payload,4)[0]
        if room is None or uid not in room['vehicles']:
            packets,event=local.handle(command,payload,now)
            return packets,event,[]
        member=room['members'].get(state['actor_uid']);world=state.get('world')
        if (member is None or member['state'] is not state or world is None or world.dead
                or state.get('transport_retired') or state.get('match_finished')):
            return [],dict(action='shared_vehicle_rejected',reason='invalid_member'),[]
        occupants=room['seats'].setdefault(uid,{})
        account=state['actor_uid']
        if command==0x6541:
            if len(payload)!=12:raise ValueError('GETON_REQ ожидает12байт')
            seat=struct.unpack_from('>I',payload,8)[0]
            if seat in occupants and occupants[seat]!=account:
                return [],dict(action='shared_vehicle_rejected',reason='seat_occupied',seat=seat),[]
        if command==0x6547:
            if len(payload)!=4:raise ValueError('SWITCH_SEAT_REQ ожидает4байта')
            seat=struct.unpack('>I',payload)[0]
            if seat in occupants and occupants[seat]!=account:
                return [],dict(action='shared_vehicle_rejected',reason='seat_occupied',seat=seat),[]
        if command==0x6549:
            if len(payload)!=73:raise ValueError('MOVE_REQ ожидает73байта')
            if occupants.get(1)!=account:
                return [],dict(action='shared_vehicle_rejected',reason='not_driver'),[]
            values=struct.unpack_from('>3f',payload,26)+struct.unpack_from('>3f',payload,39)+struct.unpack_from('>4f',payload,53)
            if not all(math.isfinite(v) for v in values) or sum(v*v for v in values[-4:])<1e-12:
                return [],dict(action='shared_vehicle_rejected',reason='invalid_motion'),[]
            tick=struct.unpack_from('>I',payload,8)[0];key=(account,id(state),uid)
            previous=room['ticks'].get(key)
            if previous is not None and not 0<(tick-previous)&0xffffffff<0x80000000:
                return [],dict(action='shared_vehicle_rejected',reason='stale_motion'),[]
        packets,event=local.handle(command,payload,now)
        action=event['action']
        if action in ('geton','seat_switch'):
            for seat,owner in list(occupants.items()):
                if owner==account:del occupants[seat]
            occupants[local.seat]=account
        elif action=='getoff':
            for seat,owner in list(occupants.items()):
                if owner==account:del occupants[seat]
        elif action=='vehicle_move':
            room['ticks'][key]=tick;room['motion'][uid]=bytes(payload)
            packets=[(0x6575,bytes(payload))]
        outputs=self.fanout(room,state,packets) if action in (
                'geton','seat_switch','getoff','vehicle_move','vehicle_hit') else []
        if action in ('geton','seat_switch','getoff'):
            room['owners'][uid]=occupants.get(1,0);room['owner_updates'].discard(uid)
            packets.append(self.owner_packet(room,uid,state))
            outputs=[(target,body+[self.owner_packet(room,uid,target)]) for target,body in outputs]
        # Водитель уже моделирует own physics; MOVE_BC только другим клиентам.
        return ([] if action=='vehicle_move' else packets),event,outputs

    def snapshots(self, now):
        outputs=[]
        for room in self.rooms.values():
            for uid,seat,account,avatar in room['seat_releases']:
                for member in room['members'].values():
                    target=member['state']
                    if target['actor_uid']==account:continue
                    body=struct.pack('>QIQIIiiiBiiiB',uid,1,avatar,seat,0,
                             *room['vehicles'][uid]['position'],0,0,0,0,0)
                    outputs.append((target,[(0x6544,body)]))
            room['seat_releases'].clear()
            for uid in sorted(room['owner_updates']):
                for member in room['members'].values():
                    outputs.append((member['state'],[self.owner_packet(room,uid,member['state'])]))
            room['owner_updates'].clear()
            for account,(identity,due,remaining) in list(room['snapshots'].items()):
                member=room['members'].get(account)
                if member is None or id(member['state'])!=identity:
                    del room['snapshots'][account];continue
                if now<due:continue
                packets=[self.owner_packet(room,uid,member['state']) for uid in room['vehicles']]
                packets.extend((0x6575,body) for body in room['motion'].values())
                for uid,occupants in room['seats'].items():
                    vehicle=room['vehicles'][uid]
                    for seat,passenger in occupants.items():
                        source=room['members'][passenger]
                        actor=passenger if passenger==account else source['avatar']
                        packets.append((0x6542,struct.pack('>QIIQIIiiiB',uid,
                              vehicle['configuration'],0,actor,seat,0,*vehicle['position'],0)))
                if packets:outputs.append((member['state'],packets))
                if remaining==1:del room['snapshots'][account]
                else:room['snapshots'][account]=(identity,now+2,remaining-1)
        return outputs,[]
