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
Запрос 0x11D5 (замер): первый float — наклон прицела в градусах (до ~17,5 вверх),
остальные нули; в 0x2F z всегда 0. Поэтому pitch для 0x30 берём из 0x11D5,
а при каждом 0x11D5 повторяем0x30 с последним направлением (гипотеза, проверяется в игре).
0x11EC SCENE_BROADCAST (декодер 140c42f80, кодер 140bd8360): I32 n (0..1024) + n байт,
одинаково в обе стороны — клиент просит разослать блок другим. Пересылаем как есть,
заменяя U64 UID отправителя (memo['actor']) на UID удалённой модели.
0x0BEE ACTOR_USE_ITEM_NTF (декодер 140bfec90): U64 entity, U32 — гипотеза: определение
предмета; шлём другим при начале лечения (3E80 action3, как в medical_probe_2022).
Запрос 0x11DA: 6f, U32 счётчик, U8 режим, U32 tick, U32, f, U32, U32.
"""
import math
import struct

from peer_motion_2022 import packed_direction
from weapon_probe_2022 import MEDICAL_SLOTS

RELAY = {0x2f: 0x30, 0x11d5: 0x11d6, 0x11da: 0x11d4, 0x11d7: 0x11d8, 0x11ec: 0x11ec, 0x3e80: 0xbee,
         0x536: 0x2b}
# Только амостры в журнал: CAMERA_ROTATE (луч выстрела), LOAD_BULLET, SET_HAND, SHOOT_TARGET_WITH_DIR.
SAMPLE_ONLY = frozenset((0x11d9, 0x49c, 0x49e, 0x11dd))

# 0x2B SCENE_MSGID_STATUS_ENTER: U64 unit, U32 E_EU_ST_*. Значения перечислений взяты из
# регистрации имён в клиенте2022 (lea имени + mov значения, 140621260..): NOT_USE_ITEM=27
# совпадает с уже проверенным статусом конца лечения medical_probe_2022.
ST_USE_ITEM, ST_MEDICAL, ST_AIMING, ST_NOT_USE_ITEM = 16, 22, 24, 27
ST_SCOPE_AIMING, ST_STOP_AIM, ST_LOAD_BULLET = 39, 40, 41
# 0x536 ACTOR_EU_ACTION_REQ: U32 E_EU_AT_* (AIM=16, DIS_AIM=17, STOP_USE_ITEM=20, SCOPE_AIM=35).
ACTION_STATUS = {16: ST_AIMING, 35: ST_SCOPE_AIMING, 17: ST_STOP_AIM}
# События сервера (weapon/medical) → статус удалённой модели.
EVENT_STATUS = {'reload_started': ST_LOAD_BULLET, 'reload': ST_NOT_USE_ITEM,
                'medical_started': ST_MEDICAL, 'medical_finished': ST_NOT_USE_ITEM,
                'medical_cancelled': ST_NOT_USE_ITEM}


def status_body(entity, status):
    return 0x2b, struct.pack('>QI', entity, status)


def event_status(event, memo):
    """Статус для других по событию сервера; конец перезарядки — только после её начала."""
    action = event.get('action') if isinstance(event, dict) else None
    status = EVENT_STATUS.get(action)
    if action == 'reload_started':
        memo['reloading'] = True
    elif action == 'reload':
        if not memo.pop('reloading', False):
            return None
    return status


def turn_body(entity, memo):
    """0x30 из последнего направления 0x2F и наклона прицела 0x11D5."""
    x, y = memo.get('direction', (1.0, 0.0))
    pitch = math.radians(max(-89.0, min(89.0, memo.get('pitch', 0.0))))
    horizontal = math.cos(pitch)
    yaw, packed_pitch = packed_direction((x*horizontal, y*horizontal, math.sin(pitch)))
    return 0x30, struct.pack('>QHHII', entity, yaw, packed_pitch, 0, 0)


def relay_packets(command, payload, entity, memo, tick=None):
    """Все SYNC для других участников (возможно пусто).

    tick — текущий tick сцены (25/с): 0x11D6 с устаревшим tick клиент, видимо, отбрасывает.
    """
    if tick is not None:
        memo['now_tick'] = tick
    if command == 0x2f and len(payload) == 12:
        x, y, _ = struct.unpack('>3f', payload)
        if not (math.isfinite(x) and math.isfinite(y)) or math.hypot(x, y) < 1e-6:
            return []
        memo['direction'] = (x, y)
        return [turn_body(entity, memo)]
    if command == 0x11d5 and len(payload) == 12:
        pitch = struct.unpack_from('>f', payload)[0]
        packets = [relay_body(command, payload, entity, memo)]
        if math.isfinite(pitch):
            memo['pitch'] = pitch
            if 'direction' in memo:
                packets.append(turn_body(entity, memo))
        return packets
    relay = relay_body(command, payload, entity, memo)
    return [] if relay is None else [relay]


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
            '>II', memo.get('now_tick', memo.get('tick', 0)), memo.get('counter', 0))
    if command == 0x11da and len(payload) == 49:
        counter, mode, tick = struct.unpack_from('>IBI', payload, 24)
        memo.update(tick=tick, counter=counter)
        return 0x11d4, struct.pack('>Q', entity) + payload[:24] + struct.pack('>BII', mode, tick, counter)
    if command == 0x11ec and len(payload) >= 4:
        size = struct.unpack_from('>i', payload)[0]
        if not 0 <= size <= 1024 or len(payload) != 4+size:
            return None
        actor = memo.get('actor')
        if actor is not None:
            # Замер: внутри блока UID записан little-endian (тип3 = SET_HAND, тип4 = после бинта).
            for order in '<>':
                payload = payload.replace(struct.pack(order+'Q', actor), struct.pack(order+'Q', entity))
        return 0x11ec, payload
    if command == 0x3e80 and len(payload) == 10 and payload[0] == 3:
        _, container, slot = struct.unpack_from('>BBH', payload)
        definition = next((d for d, s in MEDICAL_SLOTS.items() if s == slot), None)
        if container != 2 or definition is None:
            return None
        return 0xbee, struct.pack('>QI', entity, definition)
    if command == 0x536 and len(payload) == 4:
        status = ACTION_STATUS.get(struct.unpack('>I', payload)[0])
        return None if status is None else status_body(entity, status)
    if command == 0x11d7 and len(payload) == 1:
        return 0x11d8, payload + struct.pack('>Q', entity)
    return None
