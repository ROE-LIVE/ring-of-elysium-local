"""Штатное уведомление11EB2022; баланс урона задаёт вызывающий серверный стенд.

Decoder140C413F0, handler14130FFA0→14130DE60→14117E080→14117D170.
EventPlayerHitTarget вызывает штатные OnHitTarget и Play_HUD_hitmarker.
"""
import math
import struct


def encode_hit_broadcast(shooter_uid, target_uid, offset, part_id, damage,
                         dead, armor, tick, weapon_definition):
    """48байт SHOOT_TARGET_BC_SYNC; offset относительно позиции цели, в сантиметрах."""
    for value in (shooter_uid, target_uid):
        if type(value) is not int or not 0 < value < 2**64:
            raise ValueError('Нужны ненулевые UID стрелка и цели')
    for value in (damage, tick, weapon_definition):
        if type(value) is not int or not 0 <= value < 2**32:
            raise ValueError('Неверное32-битное поле уведомления попадания')
    if type(part_id) is not int or not 0 <= part_id <= 127:
        raise ValueError('part_id должен помещаться в положительный signed char')
    if type(dead) is not bool or type(armor) is not bool:
        raise ValueError('dead/armor требуют bool')
    if len(offset) != 3 or any(type(v) not in (int, float) or not math.isfinite(v)
                               or not -2**31 <= round(v) < 2**31 for v in offset):
        raise ValueError('Неверное относительное XYZ попадания')
    # SWIG getters141478060..14147A5D0 подтверждают названия/packed offsets.
    # POS13 завершается нулём; iCli_offsetms=0 — явное ограничение стенда.
    return struct.pack('>QQ3iBBIBB3I', shooter_uid, target_uid, *map(round, offset),
                       0, part_id, damage, dead, armor, tick, 0, weapon_definition)
