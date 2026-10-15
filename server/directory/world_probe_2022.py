"""Локальный пресет зимней сцены: собственные таймеры и опасный прямоугольник.

Это экспериментальные правила, а не найденный оригинальный сервер. Wire0x481
проверен decoder140c3cd80; HP0x1069 —140be1e60/handler1412ebcf0.
"""
from dataclasses import dataclass
import json
import math
from pathlib import Path
import struct
from movement_validation_2022 import MovementLimits
from region_index_2022 import FastRegionIndex


def encode_health(actor_uid, current, maximum=1000):
    if not 0 <= current <= maximum <= 100000:
        raise ValueError('Неверные HP')
    return struct.pack('>QBBBII', actor_uid, 0, 1, 0, current, maximum)


def encode_shrink(duration, stage, future, previous, elapsed_seconds=0):
    if not 0 <= duration <= 3600 or not 0 <= stage <= 1000:
        raise ValueError('Неверная стадия/таймер')
    if (type(elapsed_seconds) not in (int, float) or not math.isfinite(elapsed_seconds)
            or not 0 <= elapsed_seconds <= 3600):
        raise ValueError('Неверное прошедшее время стадии')
    # Native 140e74030 восстанавливает начало стадии как clock - elapsed.
    body = bytearray(struct.pack('>IfI', 0, elapsed_seconds, duration))
    for ids in (future, previous):
        if len(ids) > 100 or len(set(ids)) != len(ids) or any(type(i) is not int or not 0 < i < 65536 for i in ids):
            raise ValueError('Неверный список регионов')
        body.extend(struct.pack('>II', 3 if ids else 0, len(ids)))
        body.extend(b''.join(struct.pack('>I', i) for i in ids))
        body.extend(bytes(4))
    body.extend(struct.pack('>I', stage))
    return bytes(body)


def encode_shrink_warning(duration):
    """481 kind1: первичные предупреждения120/90/60/...10, 40 байт.

    Нулевые списки здесь не закрывают карту; они обновляют предупреждение.
    """
    if type(duration) is not int or not 0 <= duration <= 3600:
        raise ValueError('Неверная длительность предупреждения')
    return struct.pack('>IfI', 1, 0, duration) + bytes(28)


@dataclass(frozen=True)
class RegionGrid:
    """Прежнее приближение REGIONMASKTEXTURE: четыре индекса на400см.

    Bounds в хвосте ресурса соответствуют сетке 200 см. Порядок четырёх
    подъячеек пока не подтверждён: урон на границе разрешён только когда
    все её индексы уже закрыты. Это консервативная экспериментальная модель.
    """
    data: bytes
    origin_x: int = 204800
    origin_y: int = 614400
    cell: int = 400
    width: int = 1024

    @classmethod
    def load(cls, path):
        path = Path(path)
        if path.stat().st_size != 4196002:
            raise ValueError('Нужен проверенный ресурс зимних регионов 4196002 байта')
        with path.open('rb') as source:
            if source.read(4) != struct.pack('<HH',1024,1024):
                raise ValueError('Неверные размеры индексов регионов')
            data = source.read(1024*1024*4)
            tail = source.read(1694)
        if (max(data) > 64 or struct.unpack_from('<HH',tail) != (65,65)
                or {struct.unpack_from('<H',tail,4+n*26)[0] for n in range(65)} != set(range(65))):
            raise ValueError('Неверная таблица регионов зимней карты')
        return cls(data)

    def regions(self, position):
        x = int((position[0]-self.origin_x)//self.cell)
        y = int((self.origin_y-position[1])//self.cell)
        if not 0 <= x < self.width or not 0 <= y < self.width:
            return frozenset()
        offset = (y*self.width+x)*4
        return frozenset(self.data[offset:offset+4]) - {0}


@dataclass(frozen=True)
class WorldFixture:
    hp: int
    hp_floor: int
    hazard: tuple
    damage: int
    interval: float
    stages: tuple
    region_grid: RegionGrid | FastRegionIndex | None = None
    zone_damage: int = 0
    stage_safe: tuple = ()
    warnings: tuple = ()
    correct_delayed_stage_elapsed: bool = True
    restore_stage_on_resume: bool = True
    death_on_zero: bool = False
    movement_limits: MovementLimits | None = None
    zone_interval: float | None = None
    zone_damage_profile: str = 'diagnostic'
    zero_region_is_frozen: bool = False
    hazard_enabled: bool = True

    @classmethod
    def load(cls, path):
        path = Path(path)
        c = json.loads(path.read_text())
        hp, floor = c['hp'], c['hp_floor']
        if type(hp) is not int or type(floor) is not int or not 0 <= floor <= hp <= 1000:
            raise ValueError('HP должны быть целыми 0..1000')
        h = c['hazard']
        hazard_enabled = h.get('enabled', True)
        if type(hazard_enabled) is not bool:
            raise ValueError('hazard.enabled требует bool')
        box = tuple(h['bounds_xy'])
        if len(box) != 4 or any(type(n) not in (int, float) or not math.isfinite(n) for n in box) or box[0] >= box[2] or box[1] >= box[3]:
            raise ValueError('Неверные границы опасного участка')
        damage, interval = h['damage'], h['interval_seconds']
        if type(damage) is not int or not 0 < damage <= 1000 or type(interval) not in (int, float) or not math.isfinite(interval) or not 0.2 <= interval <= 60:
            raise ValueError('Неверный урон/интервал')
        stages, safe, last = [], [], -1
        if not isinstance(c['stages'], list) or len(c['stages']) > 16:
            raise ValueError('Неверная последовательность стадий')
        for row in c['stages']:
            at = row['at_seconds']
            if type(at) not in (int, float) or not math.isfinite(at) or not last < at <= 3600:
                raise ValueError('Время стадий должно строго возрастать')
            payload = encode_shrink(row['duration'], row['stage'], row['future_regions'], row['previous_regions'], row.get('elapsed_seconds', 0))
            stages.append((at, row['stage'], payload));last = at
            safe.append(frozenset(row['previous_regions']))
        region = c.get('region_grid')
        grid = None
        if region:
            method = region.get('lookup', 'mask_conservative')
            if method not in ('mask_conservative', 'native_fast'):
                raise ValueError('Неизвестный способ определения региона')
            loader = FastRegionIndex if method == 'native_fast' else RegionGrid
            grid = loader.load(path.parent / region['file'])
        zone_damage = region.get('damage', 50) if region else 0
        if type(zone_damage) is not int or not 0 <= zone_damage <= 1000:
            raise ValueError('Неверный урон закрытой зоны')
        zone_interval = region.get('interval_seconds', interval) if region else interval
        if (type(zone_interval) not in (int,float) or not math.isfinite(zone_interval)
                or not 0.2 <= zone_interval <= 60):
            raise ValueError('Неверный независимый интервал закрытой зоны')
        zone_profile = region.get('damage_profile', 'diagnostic') if region else 'diagnostic'
        if zone_profile not in ('diagnostic', 'buff915_resource'):
            raise ValueError('Неизвестный профиль урона зоны')
        # AI1 CreateShrink -> buff915: Steam EuBuffLogical Life-150/1000ms.
        # Условия attach/первая фаза tick остаются реконструкцией peer.
        if zone_profile == 'buff915_resource' and (
                zone_damage != 150 or zone_interval != 1
                or region.get('lookup') != 'native_fast'):
            raise ValueError('Buff915 требует damage150, interval1, native_fast')
        zero_frozen = region.get('zero_region_is_frozen', False) if region else False
        if (type(zero_frozen) is not bool or (zero_frozen and not isinstance(grid, FastRegionIndex))):
            raise ValueError('Индекс0 Frozen требует bool и native_fast')
        if grid and any(not ids <= set(range(1,65)) for ids in safe):
            raise ValueError('Индексы зимних регионов должны быть 1..64')
        if region and region.get('lookup') == 'native_fast':
            previous_safe = frozenset(range(1,65))
            for row, current_safe in zip(c['stages'], safe):
                future = frozenset(row['future_regions'])
                if not current_safe <= previous_safe or not future <= current_safe:
                    raise ValueError('Закрытые регионы нельзя открывать следующей стадией')
                previous_safe = current_safe
        warnings, last_warning = [], -1
        raw_warnings = c.get('warnings', [])
        if not isinstance(raw_warnings, list) or len(raw_warnings) > 128:
            raise ValueError('Нужно не более128 предупреждений зон')
        for row in raw_warnings:
            at, duration = row['at_seconds'], row['duration']
            if type(at) not in (int, float) or not math.isfinite(at) or not last_warning < at <= 3600:
                raise ValueError('Время предупреждений должно строго возрастать')
            warnings.append((at, duration, encode_shrink_warning(duration)))
            last_warning = at
        correction = c.get('correct_delayed_stage_elapsed', True)
        if type(correction) is not bool:
            raise ValueError('Коррекция времени стадии должна быть bool')
        restore = c.get('restore_stage_on_resume', True)
        if type(restore) is not bool:
            raise ValueError('Восстановление стадии должно быть bool')
        death = c.get('death_on_zero', False)
        if type(death) is not bool:
            raise ValueError('Смерть при нулевых HP должна быть bool')
        movement_limits = None
        if 'movement_validation' in c:
            movement_limits = MovementLimits.load(c['movement_validation'])
        return cls(hp, floor, box, damage, interval, tuple(stages), grid, zone_damage, tuple(safe), tuple(warnings), correction, restore, death, movement_limits, zone_interval, zone_profile, zero_frozen, hazard_enabled)


class WorldState:
    def __init__(self, fixture, actor_uid, now):
        self.fixture, self.actor_uid = fixture, actor_uid
        self.started = now
        self.hp = fixture.hp
        self.position = None
        self.inside = False
        self.next_damage = None
        self.stage_index = 0
        self.warning_index = 0
        self.late_warning_pending = 0
        self.initialized = False
        self.closed = set()
        self.zone_inside = False
        self.next_zone_damage = None
        self.death_sent = False

    def align_clock(self, started, now):
        """Поздний вход: текущая стадия и ещё действующее предупреждение.

        HP и время первого урона остаются индивидуальными. Прошедшие
        предупреждения не повторяются; kind1 содержит только оставшееся время.
        """
        if (self.initialized or type(started) not in (int, float)
                or type(now) not in (int, float) or not math.isfinite(started)
                or not math.isfinite(now) or not 0 <= started <= now):
            raise ValueError('Неверное начало общего календаря')
        self.started = started
        elapsed = now - started
        due = [i for i, stage in enumerate(self.fixture.stages) if stage[0] <= elapsed]
        # Последняя наступившая стадия будет отправлена первым poll.
        self.stage_index = due[-1] if due else 0
        if self.fixture.region_grid:
            for i in range(self.stage_index):
                self.closed.update(set(range(1, 65)) - self.fixture.stage_safe[i])
        self.warning_index = sum(at <= elapsed for at, _, _ in self.fixture.warnings)
        self.late_warning_pending = self.warning_index

    @property
    def dead(self):
        # Явная терминальная модель локального матча; downed/revive отдельно.
        return self.fixture.death_on_zero and (self.death_sent or self.hp == 0)

    def death_message(self):
        # BC_UNIT_DEAD: decoder140be1a80, handler140d69550; cold119 own.
        return 0x533, struct.pack('>IQ', 0, self.actor_uid)

    def poll_death(self):
        if not self.dead or self.death_sent:
            return [], []
        self.death_sent = True
        return [self.death_message()], [{'action': 'own_death', 'hp': self.hp,
                                        'experimental': True}]

    def update_position(self, position, now):
        if len(position) != 3 or any(type(n) not in (int, float) or not math.isfinite(n) for n in position):
            raise ValueError('Неверная позиция actor')
        self.position = tuple(position)
        x0, y0, x1, y1 = self.fixture.hazard
        inside = self.fixture.hazard_enabled and x0 <= position[0] <= x1 and y0 <= position[1] <= y1
        if inside == self.inside:
            return None
        self.inside = inside
        self.next_damage = now + self.fixture.interval if inside else None
        return {'action': 'hazard_enter' if inside else 'hazard_leave', 'position': self.position, 'hp': self.hp}

    def apply_damage(self, damage, source_uid):
        """Экспериментальная атака по дистанции, без серверного raycast."""
        if type(damage) is not int or not 0 <= damage <= 100:
            raise ValueError('Неверный урон бота')
        before = self.hp
        self.hp = max(self.fixture.hp_floor,self.hp-damage)
        death_packets, _ = self.poll_death()
        return [(0x1069,encode_health(self.actor_uid,self.hp)), *death_packets], {
            'action':'bot_damage','source_uid':hex(source_uid),
            'damage':before-self.hp,'hp':self.hp,'experimental':True,
            'validation':'distance_only'}

    def _stage_message(self, at, stage, body, now):
        # 140e74030: начало = clock - elapsed. Повторное подключение
        # не должно сдвигать календарь на время отсутствия heartbeat.
        lateness = max(0.0, now-self.started-at)
        elapsed = struct.unpack_from('>f', body, 4)[0]
        if self.fixture.correct_delayed_stage_elapsed:
            body = body[:4]+struct.pack('>f', min(3600.0, elapsed+lateness))+body[8:]
        elapsed = struct.unpack_from('>f', body, 4)[0]
        duration = struct.unpack_from('>I', body, 8)[0]
        return body, dict(stage=stage, elapsed=now-self.started, scheduled_at=at,
                         lateness_seconds=lateness, stage_elapsed_sent=elapsed,
                         remaining_seconds=max(0.0, duration-elapsed))

    def stage_snapshot(self, now):
        """Текущая применённая стадия без повторного изменения мира/закрытия зон.

        Потерянный ответ прежнего транспорта заменяется новым состоянием,
        а не повтором старого elapsed0. Kind1 warnings требуют отдельного контракта.
        """
        if not self.initialized or not self.stage_index:
            return None
        at, stage, body = self.fixture.stages[self.stage_index-1]
        return self._stage_message(at, stage, body, now)

    def catch_up_zone(self, now):
        """При смене транспорта выбрать текущую стадию без старых переходных481."""
        if not self.initialized:
            return (0, 0)
        elapsed = now-self.started
        stages_before, warnings_before = self.stage_index, self.warning_index
        while (self.stage_index < len(self.fixture.stages)
               and self.fixture.stages[self.stage_index][0] <= elapsed):
            self.stage_index += 1
            if self.fixture.region_grid:
                self.closed.update(set(range(1, 65))-self.fixture.stage_safe[self.stage_index-1])
        while (self.warning_index < len(self.fixture.warnings)
               and self.fixture.warnings[self.warning_index][0] <= elapsed):
            self.warning_index += 1
        self.late_warning_pending = 0
        return self.stage_index-stages_before, self.warning_index-warnings_before

    def warning_snapshot(self, now):
        """Оставшееся время последнего kind1 после позднего входа/смены транспорта.

        Kind1 не содержит elapsed: native 140e73fa0 передаёт только duration
        в 140e86bc0. Передаём целые полные секунды до исходного deadline.
        """
        if (not self.initialized or not 0 < self.warning_index
                <= len(self.fixture.warnings)):
            return None
        at, duration, _ = self.fixture.warnings[self.warning_index-1]
        elapsed = now - self.started
        if (self.warning_index < len(self.fixture.warnings)
                and self.fixture.warnings[self.warning_index][0] <= elapsed):
            return None
        if (self.stage_index < len(self.fixture.stages)
                and self.fixture.stages[self.stage_index][0] <= elapsed):
            return None
        if self.stage_index and self.fixture.stages[self.stage_index-1][0] >= at:
            return None
        remaining = int(at + duration - elapsed)
        if remaining <= 0:
            return None
        return encode_shrink_warning(remaining), dict(
            scheduled_at=at, original_duration=duration,
            remaining_seconds=remaining)

    def poll(self, now, protected=False):
        responses, events = [], []
        zone_interval = self.fixture.zone_interval or self.fixture.interval
        if not self.initialized:
            self.initialized = True
            responses.append((0x1069, encode_health(self.actor_uid, self.hp)))
            events.append({'action': 'world_start', 'hp': self.hp, 'experimental': True})
        # Слияние двух расписаний сохраняет порядок при задержке heartbeat:
        # старое предупреждение не должно перекрывать новую стадию.
        while True:
            stage_at = (self.fixture.stages[self.stage_index][0]
                        if self.stage_index < len(self.fixture.stages) else math.inf)
            warning_at = (self.fixture.warnings[self.warning_index][0]
                          if self.warning_index < len(self.fixture.warnings) else math.inf)
            if min(stage_at, warning_at) > now-self.started:
                break
            if stage_at <= warning_at:
                at, stage, body = self.fixture.stages[self.stage_index]
                self.stage_index += 1
                if self.fixture.region_grid:
                    self.closed.update(set(range(1,65))-self.fixture.stage_safe[self.stage_index-1])
                body, timing = self._stage_message(at, stage, body, now)
                events.append(dict(action='zone_stage', **timing))
            else:
                at, duration, body = self.fixture.warnings[self.warning_index]
                self.warning_index += 1
                events.append({'action': 'zone_warning', 'duration': duration, 'elapsed': now-self.started})
            responses.append((0x481, body))
        if self.late_warning_pending:
            pending_index = self.late_warning_pending
            self.late_warning_pending = 0
            snapshot = self.warning_snapshot(now) if self.warning_index == pending_index else None
            if snapshot is not None:
                body, timing = snapshot
                responses.append((0x481, body))
                events.append(dict(action='zone_warning_late', **timing))
        if self.fixture.region_grid and self.position:
            regions = self.fixture.region_grid.regions(self.position)
            if self.fixture.zero_region_is_frozen:
                # Cold156: region2→0 включает native Frozen/Blizzard.
                # Оригинальный attach buff915 не найден; здесь общая политика
                # peer для Frozen. Вне сетки lookup не создаёт safe refuge.
                region = self.fixture.region_grid.region_id(self.position)
                if region in (None, 0):
                    regions = frozenset((0,))
            exposed = bool(regions) and regions <= (self.closed | {0})
            if exposed != self.zone_inside:
                self.zone_inside = exposed
                self.next_zone_damage = now+zone_interval if exposed else None
                events.append({'action': 'closed_zone_enter' if exposed else 'closed_zone_leave',
                               'regions': sorted(regions), 'position': self.position,
                               'hp': self.hp, 'experimental': True})
        if protected:
            if self.inside: self.next_damage = now+self.fixture.interval
            if self.zone_inside: self.next_zone_damage = now+zone_interval
        if not protected and self.inside and self.next_damage is not None and now >= self.next_damage:
            periods = int((now-self.next_damage)/self.fixture.interval) + 1
            self.next_damage += periods*self.fixture.interval
            before = self.hp
            self.hp = max(self.fixture.hp_floor, self.hp-self.fixture.damage*periods)
            if self.hp != before:
                responses.append((0x1069, encode_health(self.actor_uid, self.hp)))
                events.append({'action': 'hazard_damage', 'damage': before-self.hp, 'hp': self.hp, 'periods': periods,
                               'position': self.position, 'stage': self.fixture.stages[self.stage_index-1][1] if self.stage_index else None,
                               'damage_profile': 'diagnostic_rectangle'})
        if (not protected and self.zone_inside and self.next_zone_damage is not None
                and now >= self.next_zone_damage):
            periods = int((now-self.next_zone_damage)/zone_interval)+1
            self.next_zone_damage += periods*zone_interval
            before = self.hp
            self.hp = max(self.fixture.hp_floor, self.hp-self.fixture.zone_damage*periods)
            if self.hp != before:
                responses.append((0x1069, encode_health(self.actor_uid,self.hp)))
                events.append({'action': 'closed_zone_damage','damage': before-self.hp,
                               'hp': self.hp,'periods': periods,'experimental': True,
                               'damage_profile': self.fixture.zone_damage_profile,
                               'interval_seconds': zone_interval, 'position': self.position,
                               'regions': sorted(self.fixture.region_grid.regions(self.position)) if self.position else [],
                               'stage': self.fixture.stages[self.stage_index-1][1] if self.stage_index else None})
        death_packets, death_events = self.poll_death()
        return responses + death_packets, events + death_events
