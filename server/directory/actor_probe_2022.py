"""Диагностическая мишень 2022: профиль, маршрут и проверенные сообщения HP.

Это собственные правила, не восстановленный серверный AI. Список565 и
профильBE7 отправляются одной TGCP-рамкой: отдельно профиль не создавался.
"""
from collections import OrderedDict
from dataclasses import dataclass, replace
import json
import math
from pathlib import Path
import struct

from world_probe_2022 import encode_health
from weapon_probe_2022 import ARMOR_DURABILITY, RELOAD_TIMES
from ground_route_2022 import GroundRoute
from peer_motion_2022 import encode_peer_trajectory, encode_peer_stop
from hit_feedback_2022 import encode_hit_broadcast
from collision_triangle_2022 import load_triangles, segment_triangle_entry
from collision_mesh_2022 import load_collision_meshes
from shoot_target_records_2022 import decode_hit_records
from projectile_materials_2022 import evaluate_rock


def segment_box_entry(origin, end, lower, upper):
    """Первая доля отрезка внутри замкнутого AABB; за концом цели не проверяем."""
    enter, leave = 0.0, 1.0
    for start, finish, minimum, maximum in zip(origin, end, lower, upper):
        delta = finish-start
        if abs(delta) < 1e-9:
            if not minimum <= start <= maximum:
                return None
            continue
        a, b = sorted(((minimum-start)/delta, (maximum-start)/delta))
        enter, leave = max(enter, a), min(leave, b)
        if enter > leave:
            return None
    return enter


@dataclass(frozen=True)
class ActorFixture:
    uid: int
    listing: bytes
    profile: bytes
    movement: bytes
    position: tuple
    waypoints: tuple
    speed: float
    hp: int
    damage: int
    equipment: bytes = b''
    attack: tuple | None = None
    armor_definition: int = 0
    armor_durability: int = 0
    armor_absorb_percent: int = 0
    # None сохраняет старый профиль; () включает контроль луча без преград.
    # Прямоугольные объёмы задаёт исследователь, это не коллизия исходной карты.
    collision_boxes: tuple | None = None
    # Только пассивная мишень: отдельный серверный инвентарь для death-loot.
    death_loot_reserve: int | None = None
    # Опциональный конечный боезапас проверенной Citori: magazine/reserve.
    attack_ammunition: tuple | None = None
    ground_route: GroundRoute | None = None
    movement_animation: bool = False
    attack_pause_seconds: float = 0.0
    behavior: dict | None = None
    # Выбранные world-грани задаются явно; исходная коллизия всей карты неизвестна.
    collision_triangles: tuple | None = None
    collision_meshes: tuple = ()
    material_penetration: bool = False
    # Только явно извлечённый и проверенный ресурс Iceland2022; по умолчанию нет.
    collision_heightfield: object | None = None

    @classmethod
    def load(cls, path):
        path = Path(path)
        c = json.loads(path.read_text())
        listing = (path.parent/c['listing_file']).read_bytes()
        profile = (path.parent/c['profile_file']).read_bytes()
        movement = (path.parent/c['movement_file']).read_bytes()
        uid = int(str(c['uid']), 0)
        if (len(listing) != 23 or listing[0] != 1 or len(profile) != 1516
                or struct.unpack_from('>II', profile) != (3, 1)
                or len(movement) != 40 or not 0 < uid < 2**64):
            raise ValueError('Нужны проверенные565/BE7/MOVE_POSITION_BC')
        points = c['waypoints']
        if not isinstance(points, list) or not 1 <= len(points) <= 16:
            raise ValueError('Нужно1..16 точек маршрута')
        points = tuple(tuple(p) for p in points)
        if any(len(p) != 3 or any(type(x) not in (int, float) or not math.isfinite(x) or abs(x) > 10000000 for x in p) for p in points):
            raise ValueError('Неверная позиция маршрута')
        ground_route = None
        if c.get('ground_route_file'):
            ground_route = GroundRoute.load(path.parent/c['ground_route_file'])
            points = ground_route.patrol_waypoints()
        animation = c.get('movement_animation',False)
        if type(animation) is not bool or animation and ground_route is None:
            raise ValueError('movement_animation требует bool и проверенный ground_route_file')
        speed, hp, damage = c['speed_cm_seconds'], c['hp'], c['pellet_damage']
        if type(speed) not in (int, float) or not math.isfinite(speed) or not 0 <= speed <= 600:
            raise ValueError('Скорость0..600см/с')
        if type(hp) is not int or not 1 <= hp <= 1000 or type(damage) is not int or not 1 <= damage <= 100:
            raise ValueError('Неверные HP/урон')
        a, b, m = bytearray(listing), bytearray(profile), bytearray(movement)
        struct.pack_into('>Q', a, 14, uid)
        struct.pack_into('>iii', a, 1, *map(round, points[0]))
        struct.pack_into('>Q', b, 8, uid)
        struct.pack_into('>iii', b, 1051, *map(round, points[0]))
        struct.pack_into('>Q', m, 0, uid)
        equipment = b''
        if c.get('equipment_file'):
            equipment = bytearray((path.parent/c['equipment_file']).read_bytes())
            if (len(equipment) != 82 or struct.unpack_from('>II',equipment,8) != (1,10402)
                    or struct.unpack_from('>I',equipment,24)[0] != 1):
                raise ValueError('Нужна проверенная EQUIP_CHANGE_TOALL с Citori')
            struct.pack_into('>Q',equipment,0,uid)
            equipment = bytes(equipment)
        attack = None
        if c.get('attack'):
            v = c['attack'];attack=(v['range_cm'],v['damage'],v['interval_seconds'],v['after_seconds'])
            if (not equipment or any(type(x) not in (int,float) or not math.isfinite(x) for x in attack)
                    or not 100 <= attack[0] <= 10000 or type(attack[1]) is not int or not 1 <= attack[1] <= 100
                    or not 1 <= attack[2] <= 30 or not 2 <= attack[3] <= 1800):
                raise ValueError('Неверные экспериментальные параметры атаки бота')
        pause = c.get('attack_pause_seconds',0)
        if (type(pause) not in (int,float) or not math.isfinite(pause) or not 0 <= pause <= 5
                or pause and (not animation or attack is None)):
            raise ValueError('attack_pause_seconds:0..5, требует animated route/attack')
        armor = c.get('armor')
        armor_definition = armor_durability = armor_absorb = 0
        if armor is not None:
            armor_definition = armor['definition']
            armor_durability = armor['durability']
            armor_absorb = armor['absorb_percent']
            if (type(armor_definition) is not int or armor_definition not in (201001,201002,201003,201004)
                    or type(armor_durability) is not int
                    or not 0 <= armor_durability <= ARMOR_DURABILITY[armor_definition]
                    or type(armor_absorb) is not int or not 0 <= armor_absorb <= 100):
                raise ValueError('Неверный экспериментальный пресет жилета мишени')
        boxes = None
        if 'collision_boxes' in c:
            boxes = c['collision_boxes']
            if not isinstance(boxes, list) or len(boxes) > 64:
                raise ValueError('Нужно0..64 диагностических преград')
            if any(not isinstance(box, list) or len(box) != 2
                   or any(not isinstance(p, list) or len(p) != 3
                          or any(type(x) not in (int, float) or not math.isfinite(x)
                                 or abs(x) > 10000000 for x in p) for p in box)
                   or any(a >= b for a, b in zip(*box)) for box in boxes):
                raise ValueError('Преграда: два конечных XYZ, min строго меньше max')
            boxes = tuple((tuple(a), tuple(b)) for a, b in boxes)
        death_loot_reserve = c.get('death_loot_reserve')
        if death_loot_reserve is not None and (type(death_loot_reserve) is not int
                or not 0 <= death_loot_reserve <= 999 or attack is not None):
            raise ValueError('death_loot_reserve: целое0..999, только пассивная мишень')
        ammunition = c.get('attack_ammunition')
        if ammunition is not None:
            ammunition = (ammunition['magazine'], ammunition['reserve'])
            if (attack is None or any(type(x) is not int for x in ammunition)
                    or not 0 <= ammunition[0] <= 2 or not 0 <= ammunition[1] <= 999):
                raise ValueError('attack_ammunition требует атаки Citori: magazine0..2/reserve0..999')
        behavior = c.get('behavior')
        if behavior is not None:
            if (not isinstance(behavior,dict) or ground_route is None or not animation
                    or equipment or attack or armor or death_loot_reserve is not None):
                raise ValueError('behavior требует animated ground route/пустой NPC без attack/armor')
            indexes = behavior.get('loot_indexes')
            after = behavior.get('after_seconds',15)
            pace = behavior.get('speed_cm_seconds',200)
            if (not isinstance(indexes,list) or not 1 <= len(indexes) <= 5
                    or any(type(i) is not int or not 0 <= i < 2**32 for i in indexes)
                    or len(set(indexes)) != len(indexes)
                    or type(after) not in (int,float) or not math.isfinite(after) or not 2 <= after <= 120
                    or type(pace) not in (int,float) or not math.isfinite(pace) or not 1 <= pace <= 400):
                raise ValueError('behavior:1..5loot_indexes, after2..120, speed1..400')
            behavior = dict(loot_indexes=list(indexes),after_seconds=after,speed_cm_seconds=pace)
        triangles = load_triangles(c['collision_triangles']) if 'collision_triangles' in c else None
        meshes = load_collision_meshes(path.parent/c['collision_mesh_file']) if 'collision_mesh_file' in c else ()
        penetration = c.get('material_penetration', False)
        if (type(penetration) is not bool
                or penetration and (len(meshes) != 1 or meshes[0].material_id != 305)):
            raise ValueError('material_penetration требует bool и один выбранный Rock305 mesh')
        terrain = None
        if 'collision_heightfield_file' in c:
            if not isinstance(c['collision_heightfield_file'],str) or not c['collision_heightfield_file'].strip():
                raise ValueError('collision_heightfield_file требует путь извлечённого PXBIN')
            if attack or behavior or speed:
                raise ValueError('collision_heightfield_file пока только для пассивной неподвижной мишени')
            from probe_iceland_heightfield_2022 import HeightField
            terrain = HeightField.load(path.parent/c['collision_heightfield_file'])
        return cls(uid, bytes(a), bytes(b), bytes(m), points[0], points, speed, hp, damage, equipment, attack,
                   armor_definition, armor_durability, armor_absorb, boxes, death_loot_reserve, ammunition, ground_route, animation, pause, behavior, triangles, meshes, penetration, terrain)


class ActorState:
    def __init__(self, fixture):
        self.fixture = fixture
        self.position = fixture.position
        self.hp = fixture.hp
        self.started = False
        self.last_move = None
        self.waypoint = 1 % len(fixture.waypoints)
        self.motion_path_once = False
        self.motion_sequence = 0
        self.motion_active = False
        self.motion_direction = (1.0,0.0,0.0)
        self.motion_pause_until = 0.0
        self.shots = OrderedDict()
        self.hits = set()
        self.started_at = None
        self.last_attack = None
        self.attack_counter = 0
        self.finish_at = None
        self.last_shot_target = None
        self.armor_durability = fixture.armor_durability
        self.armor_resend_at = None
        self.magazine, self.reserve = fixture.attack_ammunition or (None, None)
        self.reload_at = None
        self.spent_ammunition = 0

    def armor_sync(self):
        # 547 decoder140c356b0→140c35320, handler140e7dbd0:
        # actorQ/countI, definitionI/instanceQ/slotI/flagB, accessories countI,
        # 7 gun-propertiesI, 4I(metadata,durability,quantity,unknown), tailI/B.
        # 3e82 проверяет own UID и не обновляет чужую броню.
        uid = 0x1e00000200000000 + (self.fixture.uid & 0xffffffff)
        body = (struct.pack('>QI', self.fixture.uid, 1)
                + struct.pack('>IQIB', self.fixture.armor_definition, uid, 12, 0)
                + bytes(32) + struct.pack('>4I', 0, self.armor_durability, 1, 0)
                + bytes(5))
        return 0x547, body

    def cancel_dead_actions(self):
        """Смерть отменяет отложенный fire-stop и повтор экипировки."""
        self.finish_at = None
        self.last_shot_target = None
        self.armor_resend_at = None
        self.reload_at = None

    def begin(self, tick):
        self.started = True
        profile = bytearray(self.fixture.profile)
        struct.pack_into('>I', profile, 1064, tick)
        packets = [(0x565, self.fixture.listing), (0xbe7, bytes(profile)),
                   (0x1069, encode_health(self.fixture.uid, self.hp))]
        if self.fixture.equipment: packets.append((0x547,self.fixture.equipment))
        if self.fixture.armor_definition:
            packets.append(self.armor_sync())
        return packets

    def note_fire(self, payload, event):
        if event.get('action') != 'fire':
            return
        # Выстрел принимается только после расходования серверного патрона.
        counter = struct.unpack_from('>I', payload, 24)[0]
        tick = struct.unpack_from('>I', payload, 29)[0]
        # Запоминаем оружие именно принятого выстрела: рука может смениться до hit.
        self.shots[(counter, tick)] = (struct.unpack_from('>6f', payload), event.get('gun_definition'))
        while len(self.shots) > 64:
            key, _ = self.shots.popitem(last=False)
            self.hits = {hit for hit in self.hits if hit[:2] != key}

    def diagnostic_area_damage(self, damage):
        """Явный стендовый урон, без поддельного gun-hit/исходной формулы ROE."""
        if type(damage) is not int or not 1 <= damage <= 1000:
            raise ValueError('Учебный площадной урон требует1..1000')
        if not self.started or self.hp == 0:
            return [], {'action': 'area_damage_rejected', 'reason': 'target_not_alive'}
        absorbed = min(self.armor_durability,
                       damage * self.fixture.armor_absorb_percent // 100)
        before = self.hp
        self.armor_durability -= absorbed
        self.hp = max(0, self.hp-(damage-absorbed))
        packets = [(0x1069, encode_health(self.fixture.uid, self.hp))]
        if absorbed:
            packets.append(self.armor_sync())
        if self.hp == 0:
            self.cancel_dead_actions()
            packets.append((0x533, struct.pack('>IQ', 0, self.fixture.uid)))
        return packets, {'action': 'area_damage', 'target': hex(self.fixture.uid),
                         'damage': before-self.hp, 'hp': self.hp, 'absorbed': absorbed,
                         'armor_durability': self.armor_durability,
                         'original_damage_formula': False}
    def hit(self, payload, shooter_uid=None):
        records = decode_hit_records(payload)
        pellet = struct.unpack_from('>I', payload)[0]
        target = struct.unpack_from('>Q', payload, 4)[0]
        counter = struct.unpack_from('>I', payload, 88)[0]
        tick = struct.unpack_from('>I', payload, 96)[0]
        key = (counter, tick)
        identity = (*key, pellet)
        point = struct.unpack_from('>iii', payload, 37)
        accepted = self.shots.get(key)
        shot = accepted[0] if accepted is not None else None
        origin = shot[:3] if shot is not None else None
        geometry = {}
        # Имена подтверждены SWIG getters2022 15.10; decoder140C3FE00
        # сохраняет те же packed offsets. Native16.10: part1 включает head
        # feedback, part2/3 — обычный; исходные множители урона не восстановлены.
        # Поле83 — chShooter_path_use_c, не headshot.
        # Старые имена оставлены для совместимости журнальных анализаторов.
        fields = {'gun_definition': accepted[1] if accepted else None,
                  'collision_record_count': len(records), 'collision_records': records,
                  'hit_tag62': payload[62], 'hit_field71': struct.unpack_from('>I', payload, 71)[0],
                  'hit_field78': struct.unpack_from('>I', payload, 78)[0],
                  'hit_flag83': payload[83], 'hit_field100': struct.unpack_from('>I', payload, 100)[0],
                  'part_id': payload[62], 'target_path_id': struct.unpack_from('>I', payload, 71)[0],
                  'target_path_sequence': payload[75], 'target_path_use_c': payload[76],
                  'on_vehicle': payload[77], 'shooter_path_id': struct.unpack_from('>I', payload, 78)[0],
                  'shooter_path_sequence': payload[82], 'shooter_path_use_c': payload[83],
                  'shoot_id': pellet, 'bullet_id': counter,
                  'ratio': struct.unpack_from('>i', payload, 92)[0],
                  'pellet_index': struct.unpack_from('>i', payload, 100)[0],
                  'gun_origin': struct.unpack_from('>3f', payload, 25),
                  'target_stand': point, 'hit_impact': struct.unpack_from('>3f', payload, 50)}
        reason = None
        if not self.started or target != self.fixture.uid or self.hp == 0:
            reason = 'target'
        elif origin is None:
            reason = 'unaccepted_shot_or_pellet'
        elif identity in self.hits:
            reason = 'duplicate_hit'
        elif sum(hit[:2] == key for hit in self.hits) >= 12:
            # Поле +0 — последовательный счётчик попаданий всей сессии:
            # второй выстрел продолжил 7..11, третий 12..16. Ограничиваем
            # число записей одного принятого выстрела, а не значение счётчика.
            reason = 'shot_hit_limit'
        elif sum((a-b)**2 for a, b in zip(point, self.position)) > 250**2:
            reason = 'target_position'
        elif sum((a-b)**2 for a, b in zip(origin, self.position)) > 10000**2:
            reason = 'range'
        elif (self.fixture.collision_boxes is not None or self.fixture.collision_triangles is not None
              or self.fixture.collision_meshes or self.fixture.collision_heightfield is not None):
            reason, geometry = self.validate_ray(payload, shot, accepted[1])
        if reason:
            return [], {'action': 'hit_rejected', 'reason': reason, 'target': hex(target), 'counter': counter, 'tick': tick, 'pellet': pellet, **fields, **geometry}
        before = self.hp
        # Явный учебный баланс: absorbed расходует столько же raw durability.
        # Это не исходная формула ROE и не различение body/head hit zones.
        absorbed = min(self.armor_durability,
                       self.fixture.damage * self.fixture.armor_absorb_percent // 100)
        next_hp = max(0, self.hp - (self.fixture.damage - absorbed))
        feedback = None
        if shooter_uid is not None and accepted[1] is not None:
            try:
                feedback = encode_hit_broadcast(
                    shooter_uid, target,
                    tuple(a-b for a,b in zip(fields['hit_impact'], point)),
                    payload[62], before-next_hp, next_hp == 0, absorbed > 0,
                    tick, accepted[1])
            except (ValueError, OverflowError):
                return [], {'action': 'hit_rejected', 'reason': 'feedback_fields',
                            'target': hex(target), 'counter': counter, 'tick': tick,
                            'pellet': pellet, **fields, **geometry}
        self.hits.add(identity)
        self.armor_durability -= absorbed
        self.hp = next_hp
        # 16.10:11EA legacy handler разрешает EventPlayerHitTarget только EuRPG.
        # Для штатных QSRifle нужен11EB, подтверждённый decoder/consumer2022.
        acknowledgement = struct.pack('>IQIII', 0, target, 0, 0, 0) + bytes(8) + struct.pack('>I', before-self.hp)
        responses = [(0x1069, encode_health(target, self.hp)), (0x11ea, acknowledgement)]
        if feedback is not None:
            responses.append((0x11eb, feedback))
        if absorbed:
            responses.append(self.armor_sync())
        if self.hp == 0:
            self.cancel_dead_actions()
            # Native140be1a80/handler140d69550. В dione-combat-drop
            # сочетание HP0 и BC_UNIT_DEAD показало тело на снегу.
            responses.append((0x533, struct.pack('>IQ', 0, target)))
        return responses, {
            'action': 'hit_damage', 'target': hex(target), 'counter': counter,
            'tick': tick, 'pellet': pellet, 'damage': before-self.hp,
            'hp': self.hp, 'absorbed': absorbed, 'armor_durability': self.armor_durability,
            'armor_definition': self.fixture.armor_definition, 'experimental': True,
            'hit_feedback_command': '0x11eb' if feedback is not None else None,
            **fields, **geometry}

    def validate_ray(self, payload, shot, gun_definition=None):
        # Native decoder140c3fe00: +25 и +50 — float XYZ, +37 — int XYZ.
        # Primary hit-own-9091: +25 совпадает с origin11da, +50 — точка
        # поверхности, а +37 — положение actor. Пределы ниже наши, не баланс ROE.
        origin, aim = shot[:3], shot[3:]
        reported_origin = struct.unpack_from('>3f', payload, 25)
        impact = struct.unpack_from('>3f', payload, 50)
        validation = ('diagnostic_ray_terrain' if self.fixture.collision_heightfield is not None
                      else 'diagnostic_ray_mesh' if self.fixture.collision_meshes
                      else 'diagnostic_ray_triangles' if self.fixture.collision_triangles is not None
                      else 'diagnostic_ray_aabb')
        info = {'validation': validation, 'origin': origin,
                'aim': aim, 'impact': impact}
        if not all(math.isfinite(x) and abs(x) <= 10000000
                   for x in (*shot, *reported_origin, *impact)):
            # JSON журнала не должен содержать NaN/Infinity.
            return 'ray_nonfinite', {'validation': validation}
        if sum((a-b)**2 for a, b in zip(origin, reported_origin)) > 100**2:
            return 'shot_origin', info
        if sum((a-b)**2 for a, b in zip(impact, self.position)) > 250**2:
            return 'impact_position', info
        ray = tuple(b-a for a, b in zip(origin, aim))
        hit = tuple(b-a for a, b in zip(origin, impact))
        ray_sq, hit_sq = sum(x*x for x in ray), sum(x*x for x in hit)
        if not 1 <= hit_sq <= 10000**2:
            return 'impact_range', info
        along = sum(a*b for a, b in zip(ray, hit))
        # Конус10° допускает разброс; точная баллистика/разброс ещё не известны.
        if (ray_sq < 1 or along <= 0
                or along*along < ray_sq*hit_sq*math.cos(math.radians(10))**2):
            return 'shot_direction', info
        if self.fixture.collision_heightfield is not None:
            try:
                origin_floor = self.fixture.collision_heightfield.height_at(origin[0],origin[1])
                terrain_hit = self.fixture.collision_heightfield.intersect_segment(origin,impact)
            except (OSError,ValueError):
                # Неизвестная/недоступная геометрия не означает свободный LOS.
                return 'terrain_geometry_unavailable', info
            info['terrain_checked'] = True
            if origin[2] < origin_floor['terrain_z']-5:
                # Отрезок целиком под землёй может не пересечь поверхность.
                # Только политика этого opt-in стенда, без поддержки туннелей.
                return 'terrain_origin_below_surface', info
            if terrain_hit is not None:
                # Собственная допускаемая погрешность5см у поверхности цели;
                # это не установленный баланс или tolerance исходного сервера.
                if (1-terrain_hit['fraction'])*math.sqrt(hit_sq)>5:
                    return 'line_of_sight', {**info,'blocking_terrain':terrain_hit}
        for index, (lower, upper) in enumerate(self.fixture.collision_boxes or ()):
            if segment_box_entry(origin, impact, lower, upper) is not None:
                return 'line_of_sight', {**info, 'blocking_box': index}
        for index, triangle in enumerate(self.fixture.collision_triangles or ()):
            entry = segment_triangle_entry(origin, impact, triangle)
            if entry is not None:
                return 'line_of_sight', {**info, 'blocking_triangle': index,
                                         'blocking_fraction': entry}
        for mesh in self.fixture.collision_meshes:
            if self.fixture.material_penetration:
                try:
                    reason, penetration = evaluate_rock(mesh, origin, impact, gun_definition)
                except ValueError:
                    return 'penetration_geometry_limit', {**info, 'validation': 'diagnostic_ray_material'}
                return reason, {**info, 'validation': 'diagnostic_ray_material',
                                'penetration': penetration}
            hit = mesh.first_hit(origin,impact)
            if hit is not None:
                fraction,face = hit
                return 'line_of_sight', {**info,'blocking_mesh':mesh.identifier,
                                         'blocking_source_face':face,'blocking_fraction':fraction,
                                         'blocking_material_id':mesh.material_id}
        return None, info

    def poll(self, now, tick, player_position=None, protected=False):
        if not self.started or not self.hp:
            return [], []
        packets, events = [], []
        if self.started_at is None:
            self.started_at = now
            if self.fixture.armor_definition:
                self.armor_resend_at = now + 1
            # Повтор после завершения пакетного создания модели.
            if self.fixture.equipment: packets.append((0x547,self.fixture.equipment))
        if self.armor_resend_at is not None and now >= self.armor_resend_at:
            # BE7 создаёт модель асинхронно; повторяем уже текущую прочность.
            packets.append(self.armor_sync())
            self.armor_resend_at = None
        if self.finish_at is not None and now >= self.finish_at:
            packets.extend([(0x11d8,struct.pack('>BQ',3,self.fixture.uid)),
                            (0x11d4,self.fire_sync(tick,1,self.last_shot_target))])
            self.finish_at = None
        if self.reload_at is not None and now >= self.reload_at:
            loaded = min(2-self.magazine, self.reserve)
            self.magazine += loaded
            self.reserve -= loaded
            self.reload_at = None
            events.append({'action':'bot_reload_complete', 'uid':hex(self.fixture.uid),
                           'magazine':self.magazine, 'reserve':self.reserve,
                           'experimental':True})
        if self.fixture.attack and player_position and not protected:
            radius,damage,interval,delay = self.fixture.attack
            if (len(player_position) != 3 or not all(type(x) in (int,float)
                    and math.isfinite(x) and abs(x) <= 10000000 for x in player_position)):
                movement, motion_events = self.patrol(now,tick)
                return packets+movement, events+motion_events
            distance = sum((a-b)**2 for a,b in zip(self.position,player_position))
            origin = (*self.position[:2], self.position[2]+150)
            end = (*player_position[:2], player_position[2]+120)
            visible = (self.fixture.collision_boxes is None or not any(
                segment_box_entry(origin,end,lower,upper) is not None
                for lower,upper in self.fixture.collision_boxes))
            visible = visible and not any(segment_triangle_entry(origin, end, triangle) is not None
                                          for triangle in self.fixture.collision_triangles or ())
            visible = visible and not any(mesh.first_hit(origin,end) is not None
                                          for mesh in self.fixture.collision_meshes)
            eligible = (visible and now-self.started_at >= delay and distance <= radius**2
                    and (self.last_attack is None or now-self.last_attack >= interval))
            if eligible and self.magazine == 0 and self.reserve and self.reload_at is None:
                self.reload_at = now + RELOAD_TIMES[10402][0]
                if self.fixture.attack_pause_seconds:
                    self.motion_pause_until = self.reload_at
                events.append({'action':'bot_reload_begin', 'uid':hex(self.fixture.uid),
                               'seconds':RELOAD_TIMES[10402][0], 'magazine':0,
                               'reserve':self.reserve, 'experimental':True})
            if eligible and self.reload_at is None and self.magazine != 0:
                if self.magazine is not None:
                    self.magazine -= 1
                    self.spent_ammunition += 1
                self.attack_counter = (self.attack_counter+1)&0xffffffff
                self.last_attack = now
                self.finish_at = now+0.25
                self.last_shot_target = tuple(player_position)
                if self.fixture.attack_pause_seconds:
                    self.motion_pause_until = now+self.fixture.attack_pause_seconds
                dx,dy = player_position[0]-self.position[0],player_position[1]-self.position[1]
                yaw = math.degrees(math.atan2(dy,dx))
                packets.extend([(0x11d6,struct.pack('>Q3fII',self.fixture.uid,yaw,0,0,tick,self.attack_counter)),
                                (0x11d8,struct.pack('>BQ',0,self.fixture.uid)),
                                (0x11d4,self.fire_sync(tick,0,player_position))])
                events.append({'action':'bot_attack','uid':hex(self.fixture.uid),
                               'damage':damage,'counter':self.attack_counter,
                               'position':self.position,'target_position':tuple(player_position),
                               'validation':('diagnostic_ray_mesh' if self.fixture.collision_meshes
                                             else 'diagnostic_ray_triangles' if self.fixture.collision_triangles is not None
                                             else 'distance_only' if self.fixture.collision_boxes is None
                                             else 'diagnostic_ray_aabb'),
                               'magazine':self.magazine, 'reserve':self.reserve,
                               'spent_ammunition':self.spent_ammunition,
                               'experimental':True})
        movement, motion_events = self.patrol(now,tick)
        return packets+movement, events+motion_events

    def fire_sync(self,tick,mode,target):
        origin=(self.position[0],self.position[1],self.position[2]+150)
        end=(target[0],target[1],target[2]+120)
        return struct.pack('>Q6fBII',self.fixture.uid,*origin,*end,mode,tick,self.attack_counter)

    def patrol(self, now, tick):
        if self.last_move is None:
            self.last_move = now
        delta = min(2.0, max(0, now-self.last_move))
        paused = now < self.motion_pause_until
        if (self.fixture.speed == 0 or paused) and self.motion_active:
            self.motion_sequence = (self.motion_sequence+1)&0xffffffff
            body = encode_peer_stop(self.fixture.uid,tuple(map(round,self.position)),
                                    self.motion_sequence,tick,0,self.motion_direction)
            self.motion_active = False
            self.last_move = now
            return [(0x25,body)],[dict(action='patrol_stop',uid=hex(self.fixture.uid),experimental=True)]
        if paused:
            self.last_move = now
            return [], []
        if delta < 0.1 or self.fixture.speed == 0:
            return [], []
        self.last_move = now
        before = self.position
        if self.fixture.movement_animation:
            # Расходуем бюджет по рёбрам, сохраняя каждый пройденный угол
            # отдельным узлом SC25. Прямая start→end срезала бы преграду.
            movement_speed = self.fixture.speed
            budget = movement_speed*delta
            spent = 0.0
            previous_tick = (tick-max(1,round(delta*25)))&0xffffffff
            points = [dict(position=tuple(map(round,before)),value=previous_tick,bytes=(0,0,0))]
            for _ in range(19):
                destination = self.fixture.waypoints[self.waypoint]
                vector = tuple(b-a for a,b in zip(self.position,destination))
                length = math.sqrt(sum(x*x for x in vector))
                amount = min(length,budget-spent)
                self.position = (destination if length <= amount else
                                 tuple(a+v*amount/length for a,v in zip(self.position,vector)))
                spent += amount
                final_goal = (length <= amount and self.motion_path_once
                              and self.waypoint == len(self.fixture.waypoints)-1)
                if length <= amount and not final_goal:
                    self.waypoint = (self.waypoint+1)%len(self.fixture.waypoints)
                stamp = (previous_tick+round(spent/movement_speed*25))&0xffffffff
                points.append(dict(position=tuple(map(round,self.position)),value=stamp,bytes=(0,0,0)))
                if final_goal:
                    self.fixture = replace(self.fixture,speed=0)
                    break
                if spent >= budget:
                    break
            self.motion_sequence = (self.motion_sequence+1)&0xffffffff
            self.motion_direction = tuple(b-a for a,b in zip(points[-2]['position'],points[-1]['position']))
            self.motion_active = True
            movement = dict(points=points,word_1=round(movement_speed),bytes=(1,0,0),floats=self.motion_direction)
            body = encode_peer_trajectory(self.fixture.uid,movement,self.motion_sequence,tick)
            return [(0x25,body)],[dict(action='patrol_move',uid=hex(self.fixture.uid),position=self.position,
                                     hp=self.hp,movement='SC25',experimental=True)]
        destination = self.fixture.waypoints[self.waypoint]
        vector = tuple(b-a for a, b in zip(self.position, destination))
        length = math.sqrt(sum(x*x for x in vector))
        distance = self.fixture.speed*delta
        if length <= distance:
            self.position = destination
            self.waypoint = (self.waypoint+1) % len(self.fixture.waypoints)
        else:
            self.position = tuple(a+v*distance/length for a, v in zip(self.position, vector))
        body = bytearray(self.fixture.movement)
        struct.pack_into('>iii', body, 8, *map(round, self.position))
        struct.pack_into('>I', body, 31, tick)
        return [(0x27, bytes(body))], [{'action': 'patrol_move', 'uid': hex(self.fixture.uid), 'position': self.position, 'hp': self.hp}]
