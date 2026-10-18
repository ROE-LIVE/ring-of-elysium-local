"""Ограниченный стенд нескольких пассивных мишеней с независимым состоянием.

Позиции задаёт исследователь; это не исходные AI, спавнер или сервер ROE.
Шаблоны565/BE7/MOVE и обработка hit остаются общими с одиночной мишенью.
"""
from dataclasses import replace
import json
import math
from pathlib import Path
import struct

from actor_probe_2022 import ActorFixture, ActorState
from death_parcel_2022 import target_inventory


def load_actor_fixtures(path):
    path = Path(path)
    config = json.loads(path.read_text())
    if 'passive_targets' not in config:
        return (ActorFixture.load(path),)
    if set(config) != {'template_file', 'passive_targets'}:
        raise ValueError('Группа требует только template_file/passive_targets')
    targets = config['passive_targets']
    if not isinstance(targets, list) or not 1 <= len(targets) <= 10:
        raise ValueError('Нужно1..10 пассивных мишеней')
    template = ActorFixture.load(path.parent / config['template_file'])
    if (template.attack or template.behavior or template.ground_route
            or template.speed or len(template.waypoints) != 1):
        raise ValueError('Группа поддерживает только неподвижный пассивный шаблон')
    fixtures = []
    identifiers = set()
    instances = set()
    for item in targets:
        if not isinstance(item, dict) or set(item) != {'uid', 'position'}:
            raise ValueError('Для мишени нужны uid/position')
        uid = int(str(item['uid']), 0)
        point = item['position']
        if (not 0 < uid < 2**64 or uid in identifiers
                or not isinstance(point, list) or len(point) != 3
                or any(type(v) not in (int, float) or not math.isfinite(v)
                       or abs(v) > 10000000 for v in point)):
            raise ValueError('Неверные/повторные UID или координаты мишени')
        point = tuple(round(v) for v in point)
        listing, profile, movement = map(bytearray, (template.listing, template.profile, template.movement))
        struct.pack_into('>iii', listing, 1, *point)
        struct.pack_into('>Q', listing, 14, uid)
        struct.pack_into('>Q', profile, 8, uid)
        struct.pack_into('>iii', profile, 1051, *point)
        struct.pack_into('>Q', movement, 0, uid)
        equipment = bytearray(template.equipment)
        instance = 0x1e00000700000000 + (uid & 0xffffffff)
        if instance in instances:
            raise ValueError('Младшие32бита UID должны различаться для экипировки')
        if equipment:
            struct.pack_into('>Q', equipment, 0, uid)
            struct.pack_into('>Q', equipment, 16, instance)
        identifiers.add(uid)
        instances.add(instance)
        fixtures.append(replace(template, uid=uid, position=point, waypoints=(point,),
            listing=bytes(listing), profile=bytes(profile), movement=bytes(movement),
            equipment=bytes(equipment)))
    return tuple(fixtures)


class TargetRoster:
    def __init__(self, fixtures, weapon_fixture, own_uid):
        fixtures = tuple(fixtures)
        if (not 1 <= len(fixtures) <= 10 or own_uid in {f.uid for f in fixtures}
                or len({f.uid for f in fixtures}) != len(fixtures)):
            raise ValueError('Нужны1..10 уникальных мишеней, отличных от игрока')
        self.actors = {f.uid: ActorState(f) for f in fixtures}
        self.inventories = {}
        self.hit_owners = {}
        for uid, actor in self.actors.items():
            inventory = target_inventory(actor, weapon_fixture)
            if inventory is not None:
                self.inventories[uid] = inventory

    def note_fire(self, payload, event):
        for actor in self.actors.values():
            actor.note_fire(payload, event)
        accepted = next(iter(self.actors.values())).shots
        self.hit_owners = {key: owner for key, owner in self.hit_owners.items() if key[:2] in accepted}

    def find(self, payload):
        # Полную структуру и collision records проверит ActorState.hit.
        if len(payload) < 12:
            raise ValueError('Слишком короткий hit report')
        return self.actors.get(struct.unpack_from('>Q', payload, 4)[0])

    def hit(self, payload, shooter_uid):
        actor = self.find(payload)
        if actor is None:
            return [], {'action': 'hit_rejected', 'reason': 'unknown_target',
                        'target': hex(struct.unpack_from('>Q', payload, 4)[0])}, None
        if len(payload) < 106:
            raise ValueError('Слишком короткий hit report')
        identity = (struct.unpack_from('>I', payload, 88)[0],
                    struct.unpack_from('>I', payload, 96)[0],
                    struct.unpack_from('>I', payload, 0)[0])
        previous = self.hit_owners.get(identity)
        if len(self.actors) > 1 and previous is not None and previous != actor.fixture.uid:
            # Ограничение стенда: межцелевое пробитие одной пулей не исследовано.
            return [], {'action': 'hit_rejected', 'reason': 'pellet_reused_target',
                        'target': hex(actor.fixture.uid)}, actor
        packets, event = actor.hit(payload, shooter_uid)
        if event.get('action') == 'hit_damage':
            self.hit_owners[identity] = actor.fixture.uid
        return packets, event, actor
