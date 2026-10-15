"""Учёт собственного диагностического матча; награды ROE не вычисляются."""
from dataclasses import dataclass, field
import math


@dataclass
class MatchStatistics:
    started_at: float | None = None
    ended_at: float | None = None
    anchor: tuple | None = None
    distance_cm: float = 0
    damage_raw: int = 0
    kills: int = 0
    loot_actions: int = 0
    loot_quantity: int = 0
    rescued: bool = False
    killed_targets: set = field(default_factory=set)

    def begin(self, now):
        if self.started_at is None:
            self.started_at = now

    def reset_anchor(self, position):
        """Разрешённый серверный перенос не увеличивает пройденное расстояние."""
        self.anchor = tuple(position)

    def move(self, points):
        """Только точки принятого C2S движения; валидация выполняется до вызова."""
        if self.ended_at is not None:
            return
        for point in points:
            point = tuple(point)
            if len(point) != 3 or not all(math.isfinite(x) for x in point):
                raise ValueError('Неверная точка учёта движения')
            if self.started_at is not None and self.anchor is not None:
                self.distance_cm += math.dist(self.anchor, point)
            self.anchor = point

    def observe(self, event):
        if self.started_at is None or self.ended_at is not None:
            return
        if event.get('action') in ('hit_damage', 'area_damage'):
            damage = event.get('damage', 0)
            if type(damage) is not int or damage < 0:
                raise ValueError('Неверный подтверждённый урон')
            self.damage_raw += damage
            target = event.get('target')
            if damage and event.get('hp') == 0 and target and target not in self.killed_targets:
                self.killed_targets.add(target)
                self.kills += 1
        if event.get('action') in ('pickup', 'parcel_pickup', 'death_parcel_pickup'):
            amount = event.get('quantity', 0)
            if type(amount) is not int or amount < 0:
                raise ValueError('Неверное количество подтверждённого подбора')
            if amount:
                self.loot_actions += 1
                self.loot_quantity += amount

    def finish(self, now, rescued=False):
        if self.ended_at is None:
            self.ended_at = now
            self.rescued = bool(rescued)
        return self.snapshot(now)

    def snapshot(self, now):
        end = self.ended_at if self.ended_at is not None else now
        return dict(survival_seconds=int(max(0, end-self.started_at)) if self.started_at is not None else 0,
                    distance_cm=int(self.distance_cm), damage_raw=self.damage_raw,
                    damage_hp=self.damage_raw//10, kills=self.kills,
                    loot_actions=self.loot_actions, loot_quantity=self.loot_quantity,
                    rescued=int(self.rescued), original_reward_formula=False,
                    distance_policy='accepted_c2s_polyline_3d',
                    damage_policy='diagnostic_raw_hp_divided_by_10')
