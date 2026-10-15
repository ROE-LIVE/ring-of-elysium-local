"""Штатные grenade wire2022 и ограниченная политика локального peer.

QSWeaponConfigTable задаёт fuse/speed/range. Серверная физика, LOS и
исходная формула урона не восстановлены: конечная точка проверяется
относительно принятого броска, клиентские массивы не задают HP напрямую.
"""
from dataclasses import dataclass
import math
import struct


# Первичные строки5468..5485 QSWeaponConfigTable; native cold141/142.
PROFILES = {50001: (5.0, 1000), 50002: (5.0, 0), 50003: (2.5, 1000)}


def position(data, offset):
    xyz = struct.unpack_from('>3i', data, offset)
    if data[offset + 12] != 0 or any(abs(v) > 10000000 for v in xyz):
        raise ValueError('Неподдержанный POS13 гранаты')
    return xyz


@dataclass(frozen=True)
class ThrowRequest:
    definition: int
    origin: tuple
    direction: tuple
    predicted: tuple
    identifier: int
    speed: int


def decode_throw(payload):
    if len(payload) != 51:
        raise ValueError('Бросок требует51 байт')
    definition = struct.unpack_from('>I', payload)[0]
    if definition not in PROFILES:
        raise ValueError('Неподдержанный тип гранаты')
    origin, direction, predicted = (position(payload, at) for at in (4, 17, 30))
    identifier, speed = struct.unpack_from('>II', payload, 43)
    if speed not in (1000, 2500) or not 9500 <= math.sqrt(sum(v*v for v in direction)) <= 10500:
        raise ValueError('Неподдержанные скорость/направление броска')
    return ThrowRequest(definition, origin, direction, predicted, identifier, speed)


@dataclass(frozen=True)
class ThrowFinish:
    definition: int
    actors: tuple
    actor_fields: tuple
    entities: tuple
    point: tuple
    identifier: int


def decode_finish(payload):
    if len(payload) < 33 or len(payload) > 4833:
        raise ValueError('Неверный размер окончания гранаты')
    definition = struct.unpack_from('>I', payload)[0]
    if definition not in PROFILES:
        raise ValueError('Неподдержанный тип гранаты')
    offset, arrays = 4, []
    for maximum, fmt in ((120, '>Q'), (120, '>QI'), (300, '>Q')):
        if offset + 4 > len(payload):
            raise ValueError('Нет счётчика массива гранаты')
        count = struct.unpack_from('>I', payload, offset)[0]
        offset += 4
        size = struct.calcsize(fmt)
        if count > maximum or offset + count*size > len(payload):
            raise ValueError('Неверный массив гранаты')
        arrays.append(tuple(struct.unpack_from(fmt, payload, offset + i*size)
                            for i in range(count)))
        offset += count*size
    if offset + 17 != len(payload):
        raise ValueError('Неверный хвост окончания гранаты')
    return ThrowFinish(definition, tuple(x[0] for x in arrays[0]), arrays[1],
                       tuple(x[0] for x in arrays[2]), position(payload, offset),
                       struct.unpack_from('>I', payload, offset+13)[0])


def launch_broadcast(request, actor_uid, tick=0):
    # Native1410ef930: def,id,owner,origin,direction,speed,clockWords.
    return struct.pack('>IIQ3iB3iBIII', request.definition, request.identifier,
                       actor_uid, *request.origin, 0, *request.direction, 0,
                       request.speed, 0, tick)


def finish_broadcast(finish, actor_uid, tick=0):
    # Native1410efb90→140e8b8e0: id и позиция; effectField оставлен0.
    return struct.pack('>II3iBQIII', finish.definition, finish.identifier,
                       *finish.point, 0, actor_uid, 0, 0, tick)


class ThrowableActions:
    """Один расход на принятый ID; собственные пределы, не исходный баланс."""
    def __init__(self):
        self.pending = {}
        self.completed = set()

    def launch(self, weapon, payload, now):
        request = decode_throw(payload)
        def reject(reason):
            return [(0x1005, struct.pack('>III', request.definition,
                                        request.identifier, 1))], {
                'action': 'throw_rejected', 'reason': reason,
                'definition': request.definition, 'identifier': request.identifier}
        if request.identifier in self.pending or request.identifier in self.completed:
            # Повтор не должен удалить уже летящий native-снаряд.
            return [], {'action': 'throw_rejected', 'reason': 'duplicate_identifier'}
        if len(self.pending) >= 32 or len(self.completed) >= 4096:
            return reject('throw_limit')
        owned = weapon.equipped_throwables.get(weapon.hand_slot)
        if not owned or owned[0] != request.definition or owned[1] < 1:
            return reject('throw_not_in_hand')
        if weapon.pending_reload:
            return reject('reload_pending')
        if weapon.position is None or sum((a-b)**2 for a,b in zip(request.origin, weapon.position)) > 300**2:
            return reject('throw_origin')
        if sum((a-b)**2 for a,b in zip(request.origin, request.predicted)) > 20000**2:
            return reject('throw_prediction_range')
        slot = weapon.hand_slot
        if owned[1] == 1:
            del weapon.equipped_throwables[slot]
            weapon.hand_slot = 0
        else:
            weapon.equipped_throwables[slot] = (owned[0], owned[1]-1)
        self.pending[request.identifier] = (request, now)
        return [(0x1005, struct.pack('>III', request.definition, request.identifier, 0)),
                weapon.slot_sync(1, slot), weapon.capacity_sync()], {
            'action': 'throw_started', 'definition': request.definition,
            'identifier': request.identifier, 'slot': slot, 'speed': request.speed,
            'origin': request.origin, 'predicted': request.predicted,
            'fuse_seconds': PROFILES[request.definition][0], 'original_server_physics': False}

    def finish(self, payload, actor_uid, now, tick=0):
        finish = decode_finish(payload)
        accepted = self.pending.get(finish.identifier)
        def reject(reason):
            return [], {'action': 'throw_finish_rejected', 'reason': reason,
                        'definition': finish.definition, 'identifier': finish.identifier}, None
        if accepted is None:
            return reject('unknown_or_completed_throw')
        request, launched = accepted
        if request.definition != finish.definition:
            return reject('throw_type')
        age = now-launched
        fuse = PROFILES[request.definition][0]
        if not fuse-.25 <= age <= fuse+5:
            return reject('throw_fuse_window')
        if sum((a-b)**2 for a,b in zip(request.predicted, finish.point)) > 1000**2:
            return reject('throw_final_position')
        del self.pending[finish.identifier]
        self.completed.add(finish.identifier)
        replies = [(0x1008, struct.pack('>IIII', finish.definition, finish.identifier, 0, 0)),
                   (0x1009, finish_broadcast(finish, actor_uid, tick))]
        return replies, {'action': 'throw_finished', 'definition': finish.definition,
                         'identifier': finish.identifier, 'age_seconds': age,
                         'position': finish.point, 'reported_actor_count': len(finish.actors),
                         'reported_actor_field_count': len(finish.actor_fields),
                         'reported_entity_count': len(finish.entities),
                         'original_damage_formula': False}, finish

    def expire(self, now):
        expired = [key for key, (request, started) in self.pending.items()
                   if now-started > PROFILES[request.definition][0]+5]
        for key in expired:
            del self.pending[key]
            self.completed.add(key)
        return expired
