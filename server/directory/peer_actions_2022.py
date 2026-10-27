"""Комната: пересылка поворота, прицела, выстрела и анимации другим участникам.

Форматы SYNC восстановлены по декодерам клиента2022 (дамп кода работающего процесса,
таблицы switch 0x0A..0x4F → 140c5ba08 и 0x1132..0x11F7 → 140c73d04/140c73b98)
и по уже работающему боту actor_probe_2022 (0x11D4/0x11D6/0x11D8):
  0x30  BC_TURN_AROUND_SIMPLE 140c58bf0: U64 entity, U16 yaw, U16 pitch, U32, U32 (версия >= 0x57)
  0x11D6 SHOOT_IK_SYNC:   U64 entity, 3f, U32 tick, U32 счётчик выстрелов
  0x11D4 SHOOT_FIRE_SYNC: U64 entity, 6f (начало, конец), U8 режим, U32 tick, U32 счётчик
  0x11D8 MOTION_SYNC:     U8, U64 entity
Запрос 0x2F (замер в игре): 3 float — единичный вектор взгляда (x, y, z); его
упаковка такая же, как направление движения SC25 (packed_direction).
Запрос 0x11DA: 6f, U32 счётчик, U8 режим, U32 tick, U32, f, U32, U32.
"""
import struct

from peer_motion_2022 import packed_direction

RELAY = {0x2f: 0x30, 0x11d5: 0x11d6, 0x11da: 0x11d4, 0x11d7: 0x11d8}


def relay_body(command, payload, entity, memo=None):
    """(код SYNC, тело) для других участников или None, если запрос не того размера.

    memo — словарь отправителя: последний tick/счётчик выстрела для 0x11D6.
    """
    memo = {} if memo is None else memo
    if command == 0x2f and len(payload) == 12:
        try:
            yaw, pitch = packed_direction(struct.unpack('>3f', payload))
        except ValueError:
            return None
        return 0x30, struct.pack('>QHHII', entity, yaw, pitch, 0, 0)
    if command == 0x11d5 and len(payload) == 12:
        return 0x11d6, struct.pack('>Q', entity) + payload + struct.pack(
            '>II', memo.get('tick', 0), memo.get('counter', 0))
    if command == 0x11da and len(payload) == 49:
        counter, mode, tick = struct.unpack_from('>IBI', payload, 24)
        memo.update(tick=tick, counter=counter)
        return 0x11d4, struct.pack('>Q', entity) + payload[:24] + struct.pack('>BII', mode, tick, counter)
    if command == 0x11d7 and len(payload) == 1:
        return 0x11d8, payload + struct.pack('>Q', entity)
    return None
