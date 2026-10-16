"""Opt-in PvP комнаты2022: принятие выстрела, луч и атомарный учебный урон.

Это диагностический баланс1..100/pellet и окно2с, не исходный hurt/lagcomp.
AccountUID own HP и UnitUID remote actor никогда не подменяют друг друга.
"""
from collections import OrderedDict
from copy import copy
from dataclasses import replace
import math
import struct

from actor_probe_2022 import ActorState
from weapon_probe_2022 import ARMOR_DURABILITY
from shoot_target_records_2022 import decode_hit_records


class SharedCombatRooms:
    def __init__(self, avatars, pellet_damage):
        if type(pellet_damage) is not int or not 1 <= pellet_damage <= 100:
            raise ValueError('Учебный PvP требует целый урон1..100')
        self.avatars = avatars
        self.damage = pellet_damage

    def member(self, state, now):
        member = self.avatars.members.get((state.get('room_uid'), state.get('actor_uid')))
        anchor = state.get('peer_avatar_anchor')
        world = state.get('world')
        if (not member or member['state'] is not state or not world or world.dead
                or not anchor or not 0 <= now-anchor[2] <= 5
                or not state.get('auth_sent') or not state.get('room_sent')
                or state.get('transport_retired') or state.get('match_finished')):
            return None
        return member

    def note_fire(self, state, payload, event, now):
        member = self.member(state, now)
        if not member or event.get('action') != 'fire' or len(payload) != 49:
            return
        shot = struct.unpack_from('>6f', payload)
        position = state['world'].position
        # Проверяем origin относительно принятой сервером позиции игрока.
        # 300см допускают camera/weapon offset; это собственный предел стенда.
        if (position is None or not all(math.isfinite(x) for x in (*shot, *position))
                or sum((a-b)**2 for a,b in zip(shot[:3],position)) > 300**2):
            return
        counter, tick = struct.unpack_from('>I', payload,24)[0],struct.unpack_from('>I',payload,29)[0]
        shots = member.setdefault('combat_shots', OrderedDict())
        key = (counter,tick)
        # Даже повтор принятого frame не обновляет срок прежнего выстрела.
        shots.setdefault(key,(shot,event.get('gun_definition'),now))
        while len(shots) > 64:
            expired,_ = shots.popitem(last=False)
            member['combat_hits'] = {x for x in member.get('combat_hits',set()) if x[:2] != expired}

    def hit(self, state, payload, now):
        decode_hit_records(payload)
        target_uid = struct.unpack_from('>Q',payload,4)[0]
        source = self.member(state,now)
        target = next((m for (room,_),m in self.avatars.members.items()
                       if room == state.get('room_uid') and m['avatar'] == target_uid),None)
        reason = None
        if not source or not target or source is target:
            reason = 'room_member'
        elif not self.member(target['state'],now):
            reason = 'target_not_alive_or_current'
        else:
            for participant in (state,target['state']):
                vehicle = participant.get('vehicles')
                if vehicle and (vehicle.seated or vehicle.climb_protected(now)):
                    reason = 'on_foot_only'
        key = (struct.unpack_from('>I',payload,88)[0],struct.unpack_from('>I',payload,96)[0])
        accepted = source.get('combat_shots',{}).get(key) if source else None
        if not reason and (not accepted or not 0 <= now-accepted[2] <= 2):
            reason = 'unaccepted_or_expired_shot'
        if reason:
            return [],dict(action='peer_hit_rejected',reason=reason,target=hex(target_uid)),None
        victim = target['state']
        world,weapon = victim['world'],victim['weapon']
        position = world.position
        if position is None or not all(math.isfinite(x) for x in position):
            return [],dict(action='peer_hit_rejected',reason='target_position',target=hex(target_uid)),None
        definition = weapon.equipment.get(12,0)
        definition = definition if definition in ARMOR_DURABILITY else 0
        fixture = replace(self.avatars.fixture,uid=target_uid,position=tuple(position),
                          hp=world.hp,damage=self.damage,armor_definition=definition,
                          armor_durability=weapon.equipment_durability.get(12,0) if definition else 0,
                          armor_absorb_percent=weapon.fixture.combat_armor_absorb_percent,
                          collision_boxes=self.avatars.fixture.collision_boxes or ())
        validator = ActorState(fixture)
        validator.started = True
        validator.shots = source['combat_shots']
        validator.hits = set(source.get('combat_hits',set()))
        responses,event = validator.hit(payload, shooter_uid=state['actor_uid'])
        if event['action'] != 'hit_damage':
            return [],dict(event,action='peer_hit_rejected'),None
        # Только после проверки/кодирования всего результата фиксируем HP,
        # прочность и dedup одним синхронным участком event loop.
        staged_weapon,staged_world = copy(weapon),copy(world)
        staged_weapon.equipment_durability = dict(weapon.equipment_durability)
        damage,armor_packets,_ = staged_weapon.absorb_combat_damage(self.damage)
        own_packets,_ = staged_world.apply_damage(damage,source['avatar'])
        source_packets = [(code,body) for code,body in responses if code in (0x11ea, 0x11eb)]
        weapon.equipment_durability.update(staged_weapon.equipment_durability)
        world.__dict__.update(staged_world.__dict__)
        source['combat_hits'] = validator.hits
        event.update(action='hit_damage',source=hex(source['avatar']),
                     target_account=hex(victim['actor_uid']),shared_pvp=True,
                     original_damage_formula=False)
        return [(state,source_packets),(victim,armor_packets+own_packets)],event,victim
