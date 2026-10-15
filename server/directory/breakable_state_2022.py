"""Учебное подтверждение разрушения частей2022; не исходная физика сервера."""
from dataclasses import dataclass
import json
import math
from pathlib import Path
import struct


@dataclass(frozen=True)
class BreakableFixture:
    entities: dict
    interaction_radius_cm: int = 750

    @classmethod
    def load(cls, path):
        path = Path(path)
        if path.stat().st_size > 4 * 1024 * 1024:
            raise ValueError('Каталог разрушения превышает4МиБ')
        data = json.loads(path.read_text(encoding='utf-8'))
        if data.get('map') != 16010:
            raise ValueError('Разрушение проверяется только на карте16010')
        radius = data.get('interaction_radius_cm', 750)
        if type(radius) is not int or not 100 <= radius <= 1000:
            raise ValueError('Нужен радиус100..1000см')
        entities = {}
        rows = data.get('entities')
        if not isinstance(rows, list) or not 1 <= len(rows) <= 16384:
            raise ValueError('Нужно1..16384 сущностей')
        for row in rows:
            identifier, xyz, hp = row.get('id'), row.get('position_cm'), row.get('parts')
            if type(identifier) is not int or not 0 < identifier < 2**32 or identifier in entities:
                raise ValueError('Неверный/повторныйID')
            if not isinstance(xyz, list) or len(xyz) != 3 or any(type(v) not in (int,float) or not math.isfinite(v) for v in xyz):
                raise ValueError('Нужны конечныеXYZ')
            # Native379 подтверждает одну часть с threshold/status1; не расширяем
            # правила до деревянных стен/дверей и других материалов по имени.
            if hp != [1] or any(type(v) is not int for v in hp):
                raise ValueError('Проверенный профиль: одна часть с прочностью1')
            entities[identifier] = (tuple(xyz), tuple(hp))
        return cls(entities, radius)


def decode_damage(payload):
    # Primary140C9EBE0: entityU32,countU32,damageU32[count],lenB,extra.
    if len(payload) < 9:
        raise ValueError('Короткий запрос')
    identifier, count = struct.unpack_from('>II', payload)
    if not 1 <= count <= 10:
        raise ValueError('Неверное число частей')
    offset = 8 + count * 4
    if len(payload) < offset + 1:
        raise ValueError('Нет массива частей')
    damage = struct.unpack_from('>' + str(count) + 'I', payload, 8)
    size = payload[offset]
    if size != 72 or len(payload) != offset + 1 + size:
        raise ValueError('Нужен проверенный impactContext72')
    context = payload[offset + 1:]
    actor, part = struct.unpack_from('<QI', context)
    floats = struct.unpack_from('<13f', context, 12)
    if part >= count or any(v > 1000000 for v in damage) or any(not math.isfinite(v) or abs(v) > 10000000 for v in floats):
        raise ValueError('Неверные параметры удара')
    return identifier, damage, context, actor, part


def encode_broken(identifier, remaining, context):
    record = (struct.pack('>IBBB', identifier, 0, 0, len(remaining))
              + struct.pack('>' + str(len(remaining)) + 'I', *remaining)
              + bytes([len(context)]) + context + struct.pack('>Q', 0))
    return struct.pack('>I', 1) + record + b'\0'


class BreakableState:
    def __init__(self, fixture, actor_uid):
        self.fixture, self.actor_uid = fixture, actor_uid
        self.remaining = {identifier: list(value[1]) for identifier,value in fixture.entities.items()}
        self.contexts = {}
        self.visible = set()

    def handle(self, payload, position):
        try:
            identifier, damage, context, actor, part = decode_damage(payload)
        except ValueError as error:
            return [], dict(action='breakable_rejected', reason=str(error))
        event = dict(entity_id=identifier, part=part, damage=list(damage), original_server_physics=False)
        if identifier not in self.fixture.entities or len(damage) != len(self.remaining[identifier]):
            return [], dict(action='breakable_rejected', reason='unknown_entity_or_parts', **event)
        if actor != self.actor_uid:
            return [], dict(action='breakable_rejected', reason='foreign_actor', **event)
        if not isinstance(position, (list,tuple)) or len(position) != 3 or any(type(v) not in (int,float) or not math.isfinite(v) for v in position):
            return [], dict(action='breakable_rejected', reason='position', **event)
        distance = math.dist(position, self.fixture.entities[identifier][0])
        if distance > self.fixture.interaction_radius_cm:
            return [], dict(action='breakable_rejected', reason='distance', distance_cm=distance, **event)
        previous = self.remaining[identifier][:]
        current = [max(0,hp-value) for hp,value in zip(previous,damage)]
        self.remaining[identifier] = current
        changed = current != previous
        if changed:
            self.contexts[identifier] = context
        # Повтор не расходует прочность ниже0 и не заменяет сохранённый контекст.
        response_context = self.contexts.get(identifier, context)
        self.visible.add(identifier)
        return [(0x6f56, encode_broken(identifier,current,response_context))], dict(
            action='breakable_damage', previous=previous, remaining=current, changed=changed,
            distance_cm=distance, **event)

    def resume(self):
        self.visible.clear()

    def snapshot(self, position):
        if not isinstance(position,(tuple,list)) or len(position) != 3:
            return []
        messages = []
        for identifier,context in self.contexts.items():
            if identifier not in self.visible and math.dist(position,self.fixture.entities[identifier][0]) <= 6000:
                messages.append((0x6f56,encode_broken(identifier,self.remaining[identifier],context)))
                self.visible.add(identifier)
                if len(messages) >= 16:
                    break
        return messages
