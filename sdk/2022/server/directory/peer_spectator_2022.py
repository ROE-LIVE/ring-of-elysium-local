"""Учебный выбор наблюдаемого живого участника комнаты после смерти.

6FBB проверен в EXE2022; правила команд/режимов оригинального сервера неизвестны.
Account UID получателя и Unit UID наблюдаемой модели имеют разные роли.
"""
import struct
import math


class PeerSpectators:
    def __init__(self):
        self.receipts = {}
        self.camera_ticks = {}

    @staticmethod
    def connected(state, now):
        anchor = state.get('peer_avatar_anchor')
        return bool(anchor and now - anchor[2] <= 5
                    and state.get('auth_sent') and state.get('room_sent')
                    and not state.get('match_finished')
                    and not state.get('transport_retired'))

    def poll(self, rooms, now):
        outputs, events = [], []
        members = rooms.members
        for key in list(self.receipts):
            if key not in members:
                del self.receipts[key]
        for key, member in members.items():
            state = member['state']
            world = state.get('world')
            if world is not None and not world.dead:
                self.receipts.pop(key, None)
            if world is None or not world.dead or not self.connected(state, now):
                continue
            eligible = {other['avatar'] for other_key, other in members.items()
                        if other_key[0] == key[0] and other_key != key
                        and now >= other.get('spectator_ready_at', 0)
                        and self.connected(other['state'], now)
                        and other['state'].get('world') is not None
                        and not other['state']['world'].dead}
            previous = self.receipts.get(key)
            target = previous[1] if previous and previous[1] in eligible else min(eligible, default=0)
            receipt = (id(state), target)
            # Нулевой UID очищает цель, но native active остаётся 1.
            # Завершение матча — отдельное событие, не этот ответ.
            if previous == receipt or (previous is None and target == 0):
                continue
            self.receipts[key] = receipt
            if target:
                # Наблюдаемый клиент сам производит camera state через 6FBC.
                target_state = next(other['state'] for other_key,other in members.items()
                                    if other_key[0] == key[0] and other['avatar'] == target)
                outputs.append((target_state, [(0x6fbe,struct.pack('>Q',key[1]))]))
            outputs.append((state, [(0x6fbb, struct.pack('>Q', target))]))
            events.append(dict(action='peer_spectator_target',
                               account_uid=hex(key[1]), room_uid=hex(key[0]),
                               target_unit_uid=hex(target)))
        return outputs, events

    def relay_camera(self, rooms, state, payload, now):
        """Проверенный selector1: 61B LE внутри bounded BE byte-array.

        Ограничение опыта: оба внутренних UID равны собственному AccountUID.
        Другие камеры/селекторы и transport input events пока не пересылаются.
        """
        if (len(payload) != 66 or struct.unpack_from('>I',payload)[0] != 62
                or payload[4] != 1):
            return [], []
        key = (state['room_uid'],state['actor_uid'])
        member = rooms.members.get(key)
        world = state.get('world')
        if (member is None or member['state'] is not state or world is None
                or world.dead or not self.connected(state,now)):
            return [], []
        if struct.unpack_from('<QQ',payload,5) != (key[1],key[1]):
            return [], []
        if not all(math.isfinite(value) for value in struct.unpack_from('<9f',payload,29)):
            return [], []
        tick = struct.unpack_from('<I',payload,21)[0]
        tick_key = (*key,id(state))
        previous = self.camera_ticks.get(tick_key)
        if previous is not None and not 0 < (tick-previous)&0xffffffff < 0x80000000:
            return [], []
        body = bytearray(payload)
        struct.pack_into('<QQ',body,5,member['avatar'],member['avatar'])
        outputs = []
        for observer_key, receipt in self.receipts.items():
            observer = rooms.members.get(observer_key)
            if observer is None or observer_key[0] != key[0] or receipt[1] != member['avatar']:
                continue
            target = observer['state']
            if (receipt[0] != id(target) or not self.connected(target,now)
                    or target.get('world') is None or not target['world'].dead):
                continue
            outputs.append((target,[(0x6fbd,bytes(body))]))
        if not outputs:
            return [], []
        self.camera_ticks[tick_key] = tick
        # Ограничить историю старыми транспортами этой небольшой комнаты.
        active = {(*member_key,id(value['state'])) for member_key,value in rooms.members.items()}
        self.camera_ticks = {k:v for k,v in self.camera_ticks.items() if k in active}
        return outputs, []
