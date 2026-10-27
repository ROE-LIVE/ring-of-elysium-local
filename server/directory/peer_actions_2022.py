"""Комната: пересылка поворота, прицела, выстрела и анимации другим участникам.

Форматы SYNC восстановлены по декодерам клиента2022 (дамп кода работающего процесса,
таблицы switch 0x0A..0x4F → 140c5ba08 и 0x1132..0x11F7 → 140c73d04/140c73b98):
  0x30  BC_TURN_AROUND_SIMPLE 140c58bf0: U64 entity, U16, U16, [U32, U32 при версии >= 0x57]
  0x11D6 SHOOT_IK_SYNC         140c3ed80: U64 entity, 3×4 байта, U32, U32
  0x11D4 SHOOT_FIRE_SYNC       140c3eb80: U64 entity, 3×4 байта, U32, U8, U32, U32
  0x11D8 MOTION_SYNC           140c3f310: U8, U64 entity, U32, U32
Соответствие полей запроса (0x2F/0x11D5/0x11DA/0x11D7) полям SYNC — наша гипотеза:
те же значения в том же порядке, неизвестные хвосты нулевые. Проверяется в игре.
"""
import struct

RELAY = {0x2f: 0x30, 0x11d5: 0x11d6, 0x11da: 0x11d4, 0x11d7: 0x11d8}


def relay_body(command, payload, entity):
    """(код SYNC, тело) для других участников или None, если запрос не того размера."""
    if command == 0x2f and len(payload) == 12:
        return 0x30, struct.pack('>Q', entity) + payload
    if command == 0x11d5 and len(payload) == 12:
        return 0x11d6, struct.pack('>Q', entity) + payload + bytes(8)
    if command == 0x11da and len(payload) == 49:
        # Запрос: 6×float, счётчик U32, режим U8, tick U32, U32, float, U32, U32.
        return 0x11d4, struct.pack('>Q', entity) + payload[:12] + payload[24:37]
    if command == 0x11d7 and len(payload) == 1:
        return 0x11d8, payload + struct.pack('>Q', entity) + bytes(8)
    return None
