"""Урон от падения пешком — собственная экспериментальная кривая, не исходная формула.

Клиент не просит урон за обычное падение (SKI_HURT_REQ0x100A — только лыжи), значит
сервер считал его сам. Таблица урона не найдена (analises/dano-por-queda-2026-10-27.md).
Кривая привязана к CharacterTable клиента (TableBin00000a11): Gravity1600 см/с²,
mMiddleFallVSpeed700, mHighFallVSpeed1400. Скорость удара v = √(2·g·h), h — от высшей
точки полёта до точки приземления по C2S0x2A:
  v < 700 → 0; 700..1400 → 0..50% HP линейно; дальше та же прямая, смерть при2100 (≈14м).
События C2S0x2A bytes[1] — E_EU_AT_*: 22 JUMP_UP / 4 FALL начинают полёт; 29 FALL_LAND,
1/2/3 (стойка/присед/лёжа), 30 LAND_TO_MOVE — приземление; планер, парашют, лыжи, лазание,
трос, вода, транспорт отменяют подсчёт без урона.
"""
import math

GRAVITY = 1600
SAFE_SPEED = 700
HIGH_SPEED = 1400
LETHAL_SPEED = 2100
FULL_HP = 1000

START_EVENTS = frozenset((22, 4))
LAND_EVENTS = frozenset((29, 1, 2, 3, 30))
# PARACHUTE5, SWIN6, FLOAT7, ON_VEHICLE9, LAND_WATER23, FLY24, CLIMB36, тросы37..39,
# лыжи40/41/43, BEGIN_CLIMB42, BIKE48..50, GRAPPLE52..54, JET_UP55, SDV56/57.
CANCEL_EVENTS = frozenset((5, 6, 7, 9, 23, 24, 36, 37, 38, 39, 40, 41, 42, 43,
                           48, 49, 50, 52, 53, 54, 55, 56, 57))


def fall_damage(height_cm):
    """Урон (шкала HP1000) по высоте падения в см."""
    if height_cm <= 0:
        return 0
    speed = math.sqrt(2*GRAVITY*height_cm)
    if speed < SAFE_SPEED:
        return 0
    damage = (speed-SAFE_SPEED)/(HIGH_SPEED-SAFE_SPEED)*FULL_HP/2
    return min(FULL_HP, round(damage))


class FallTracker:
    """Высшая точка текущего полёта; observe возвращает (высота, урон) при приземлении."""

    def __init__(self):
        self.peak = None

    def cancel(self):
        self.peak = None

    def observe(self, points):
        result = None
        for point in points:
            z = point['position'][2]
            event = point['bytes'][1]
            if event in CANCEL_EVENTS:
                self.peak = None
                continue
            if event in START_EVENTS:
                self.peak = z if self.peak is None else max(self.peak, z)
                continue
            if self.peak is None:
                continue
            self.peak = max(self.peak, z)
            if event in LAND_EVENTS:
                height = self.peak - z
                self.peak = None
                result = (height, fall_damage(height))
        return result
