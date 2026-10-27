"""Урон от падения пешком — собственная экспериментальная кривая, не исходная формула.

Клиент не просит урон за обычное падение (SKI_HURT_REQ0x100A — только лыжи), значит
сервер считал его сам. Таблица урона не найдена (analises/dano-por-queda-2026-10-27.md).
Кривая привязана к CharacterTable клиента (TableBin00000a11): Gravity1600 см/с²,
mMiddleFallVSpeed700, mHighFallVSpeed1400. Скорость удара — наибольшая измеренная скорость
снижения между соседними точками C2S0x2A в полёте (tick40мс + доля0..39мс):
  v < 1400 (mHighFallVSpeed) → 0; дальше линейно, смерть при3500 (половина HP при2450).
Калибровка по видео оригинала (пользователь27/10): прыжок на сноуборде с высоты ~2 сосен
(~30м, v ≈ 3100 см/с) оставил18 HP из100 → ~82% урона при3100.
Сессия27/10 (20261027T212632): по высоте «от вершины до приземления» прыжок вниз по склону
(2,7м, но снижение лишь ~575 см/с) давал16,6 HP. Сессия20261027T215844: падение6,4м
(1212 см/с) дало36,6 HP, а в оригинале с такой высоты урона нет (пользователь) — порог
поднят с mMiddleFallVSpeed700 до mHighFallVSpeed1400.
События C2S0x2A bytes[1] — E_EU_AT_*: 22 JUMP_UP / 4 FALL начинают полёт; 29 FALL_LAND,
1/2/3 (стойка/присед/лёжа), 30 LAND_TO_MOVE — приземление; планер, парашют, лыжи, лазание,
трос, вода, транспорт отменяют подсчёт без урона.
"""
import math

GRAVITY = 1600
SAFE_SPEED = 1400
HIGH_SPEED = 2450
LETHAL_SPEED = 3500
FULL_HP = 1000

START_EVENTS = frozenset((22, 4))
LAND_EVENTS = frozenset((29, 1, 2, 3, 30))
# PARACHUTE5, SWIN6, FLOAT7, ON_VEHICLE9, LAND_WATER23, FLY24, CLIMB36, тросы37..39,
# лыжи40/41/43, BEGIN_CLIMB42, BIKE48..50, GRAPPLE52..54, JET_UP55, SDV56/57.
CANCEL_EVENTS = frozenset((5, 6, 7, 9, 23, 24, 36, 37, 38, 39, 40, 41, 42, 43,
                           48, 49, 50, 52, 53, 54, 55, 56, 57))


def speed_damage(speed):
    """Урон (шкала HP1000) по скорости удара в см/с."""
    if speed < SAFE_SPEED:
        return 0
    return min(FULL_HP, round((speed-SAFE_SPEED)/(HIGH_SPEED-SAFE_SPEED)*FULL_HP/2))


def fall_damage(height_cm):
    """Урон по высоте свободного падения (v = √(2·g·h)); для справки и тестов."""
    return speed_damage(math.sqrt(2*GRAVITY*height_cm)) if height_cm > 0 else 0


def point_ms(point):
    return point['value']*40 + point['bytes'][2]


class FallTracker:
    """Полёт от START до LAND; observe возвращает (высота, скорость, урон) при приземлении."""

    def __init__(self):
        self.cancel()

    def cancel(self):
        self.peak = None
        self.last = None
        self.speed = 0.0

    def observe(self, points):
        result = None
        for point in points:
            z = point['position'][2]
            event = point['bytes'][1]
            if event in CANCEL_EVENTS:
                self.cancel()
                continue
            if self.peak is None:
                if event in START_EVENTS:
                    self.peak, self.last, self.speed = z, (z, point_ms(point)), 0.0
                continue
            previous_z, previous_ms = self.last
            elapsed = (point_ms(point)-previous_ms) % (2**32*40)
            if 20 <= elapsed <= 2000:
                self.speed = max(self.speed, (previous_z-z)*1000/elapsed)
            self.last = (z, point_ms(point))
            self.peak = max(self.peak, z)
            if event in LAND_EVENTS:
                height, speed = self.peak-z, self.speed
                self.cancel()
                result = (height, round(speed), speed_damage(speed))
        return result


def ski_hurt(payload):
    """0x100A SKI_HURT_REQ (декодер140bfec20, getter SKI_HURT_REQ_iSpeed): U32 iSpeed.
    Ответ0x100B SKI_HURT_RSP: U32 iRet (тот же декодер). Единица iSpeed не подтверждена
    (предположение см/с, как остальные скорости клиента); сырое значение пишется в журнал.
    Возвращает (скорость, урон, ответ)."""
    if len(payload) != 4:
        raise ValueError('SKI_HURT_REQ ожидает4байта')
    speed = int.from_bytes(payload, 'big')
    return speed, speed_damage(speed), (0x100b, bytes(4))
