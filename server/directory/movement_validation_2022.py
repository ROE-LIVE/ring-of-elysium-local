"""Ограниченная учебная проверка MOVE_1 по серверному времени, без физики карты."""
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class MovementLimits:
    horizontal_speed: float = 5000
    vertical_speed: float = 20000
    burst_seconds: float = 2

    @classmethod
    def load(cls, value):
        if not isinstance(value, dict) or set(value) - {
                'horizontal_speed_cm_s', 'vertical_speed_cm_s', 'burst_seconds'}:
            raise ValueError('Неизвестные параметры учебной валидации движения')
        numbers = [value.get('horizontal_speed_cm_s', 5000),
                   value.get('vertical_speed_cm_s', 20000), value.get('burst_seconds', 2)]
        if (any(type(x) not in (int, float) or not math.isfinite(x) for x in numbers)
                or not 100 <= numbers[0] <= 20000 or not 100 <= numbers[1] <= 50000
                or not .2 <= numbers[2] <= 5):
            raise ValueError('Пределы движения: XY100..20000, Z100..50000см/с, burst0.2..5с')
        return cls(*numbers)


class MovementState:
    def __init__(self, limits, position, now):
        self.limits = limits
        self.reset(position, now)

    def reset(self, position, now):
        """Только явный server27/restore разрешает новую опорную позицию."""
        if len(position) != 3 or any(type(x) not in (int, float) or not math.isfinite(x) for x in position):
            raise ValueError('Неверная опорная позиция')
        self.position = tuple(position)
        self.updated_at = now
        self.horizontal_budget = self.limits.horizontal_speed * self.limits.burst_seconds
        self.vertical_budget = self.limits.vertical_speed * self.limits.burst_seconds

    def accept(self, movement, now):
        if not math.isfinite(now) or now < self.updated_at:
            return False, dict(reason='server_time')
        if any(not math.isfinite(x) for x in movement['floats']):
            return False, dict(reason='nonfinite_orientation')
        if not movement['points']:
            return True, dict(reason='empty')
        # Не доверяем client ticks и не выдаём новый burst на каждый пакет.
        elapsed = now-self.updated_at
        horizontal = min(self.horizontal_budget + elapsed*self.limits.horizontal_speed,
                         self.limits.horizontal_speed*self.limits.burst_seconds)
        vertical = min(self.vertical_budget + elapsed*self.limits.vertical_speed,
                       self.limits.vertical_speed*self.limits.burst_seconds)
        position, xy_used, z_used = self.position, 0.0, 0.0
        for point in movement['points']:
            target = tuple(point['position'])
            xy_used += math.hypot(target[0]-position[0], target[1]-position[1])
            z_used += abs(target[2]-position[2])
            position = target
        info = dict(position=position, previous_position=self.position,
                    horizontal_cm=xy_used, vertical_cm=z_used,
                    horizontal_budget_cm=horizontal, vertical_budget_cm=vertical,
                    elapsed_seconds=elapsed, experimental=True)
        if xy_used > horizontal+.001 or z_used > vertical+.001:
            return False, dict(reason='movement_budget', **info)
        self.position, self.updated_at = position, now
        self.horizontal_budget, self.vertical_budget = horizontal-xy_used, vertical-z_used
        return True, dict(reason='within_budget', **info)
