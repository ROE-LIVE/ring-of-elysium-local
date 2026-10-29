"""Комната: пересылка поворота, прицела, выстрела и анимации другим участникам.

Форматы SYNC восстановлены по декодерам клиента2022 (дамп кода работающего процесса,
таблицы switch 0x0A..0x4F → 140c5ba08 и 0x1132..0x11F7 → 140c73d04/140c73b98)
и по уже работающему боту actor_probe_2022 (0x11D4/0x11D6/0x11D8):
  0x30  BC_TURN_AROUND_SIMPLE 140c58bf0: U64 entity, U16 yaw, U16 pitch, U32, U32 (версия >= 0x57)
  0x11D6 SHOOT_IK_SYNC:   U64 entity, 3f, U32 tick, U32 счётчик выстрелов
  0x11D4 SHOOT_FIRE_SYNC: U64 entity, 6f (начало, конец), U8 режим, U32 tick, U32 счётчик
  0x11D8 MOTION_SYNC:     U8, U64 entity, U32 tick, U32 счётчик (декодер 140c3f310 требует оба
                          U32: 9 байт как у бота возвращают -2, и клиент выбрасывает пакет —
                          без него у других нет позы/отдачи выстрела, только звук и вспышка 0x11D4)
Запрос 0x2F (замер в игре): 3 float — единичный вектор взгляда (x, y, z); его
упаковка такая же, как направление движения SC25 (packed_direction).
Запрос 0x11D5 (сборка 140e7d4e0 ← 140e7cf40): первый float — смещение анимации из
140e7c990 (параметр анимграфа0x37, нормированный ±1), а не наклон прицела. Поэтому
pitch0x30 берётся только из z запроса0x2F.
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
         0x536: 0x2b, 0x1159: 0x1159}
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
# Выстрел без прицела: клиент не шлёт0x536, и удалённая модель с опущенным оружием не играет
# анимацию0x11D8 (сессия20261029T012734: с прицелом поза видна, без — нет). Поднимаем оружие
# статусом AIMING перед выстрелом и опускаем STOP_AIM, если за это время не было новых выстрелов.
HIP_FIRE_HOLD = 1.0
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


def relay_packets(command, payload, entity, memo, tick=None, now=None):
    """Все SYNC для других участников (возможно пусто).

    tick — текущий tick сцены (25/с): 0x11D6 с устаревшим tick клиент, видимо, отбрасывает.
    now — монотонное время в секундах: срок опускания оружия после выстрела без прицела.
    """
    if tick is not None:
        memo['now_tick'] = tick
    relay = relay_body(command, payload, entity, memo)
    if relay is None:
        return []
    if command == 0x536:
        action = struct.unpack('>I', payload)[0]
        if action in (16, 35):
            memo['aiming'] = True
            memo.pop('hip_until', None)
        elif action == 17:
            memo['aiming'] = False
    if command == 0x11d7 and now is not None and not memo.get('aiming'):
        packets = [] if 'hip_until' in memo else [status_body(entity, ST_AIMING)]
        memo['hip_until'] = now + HIP_FIRE_HOLD
        return packets + [relay]
    return [relay]


def hip_fire_release(entity, memo, now):
    """STOP_AIM для других, когда после выстрела без прицела прошло HIP_FIRE_HOLD."""
    until = memo.get('hip_until')
    if until is None or now < until:
        return []
    del memo['hip_until']
    return [status_body(entity, ST_STOP_AIM)]


def relay_body(command, payload, entity, memo=None):
    """(код SYNC, тело) для других участников или None, если запрос не того размера.

    memo — словарь отправителя: последний tick/счётчик выстрела для 0x11D6.
    """
    memo = {} if memo is None else memo
    if command == 0x2f and len(payload) == 12:
        direction = struct.unpack('>3f', payload)
        # Нулевой вектор развернул бы модель к углу0; такой запрос пропускаем.
        if not all(math.isfinite(v) for v in direction) or math.hypot(*direction) < 1e-6:
            return None
        yaw, pitch = packed_direction(direction)
        return 0x30, struct.pack('>QHHII', entity, yaw, pitch, 0, 0)
    if command == 0x11d5 and len(payload) == 12:
        return 0x11d6, struct.pack('>Q', entity) + payload + struct.pack(
            '>II', memo.get('now_tick', memo.get('tick', 0)), memo.get('counter', 0))
    if command == 0x11da and len(payload) == 49:
        counter, mode, tick = struct.unpack_from('>IBI', payload, 24)
        memo.update(tick=tick, counter=counter)
        return 0x11d4, struct.pack('>Q', entity) + payload[:24] + struct.pack('>BII', mode, tick, counter)
    # 0x1159 SCENE_AROUND_BROADCAST — тот же декодер140c42f80, что и0x11EC; клиент шлёт его
    # только на лыжах/сноуборде (сессия20261027T205950: 37/33 байта) — поза доски у других.
    if command in (0x11ec, 0x1159) and len(payload) >= 4:
        size = struct.unpack_from('>i', payload)[0]
        if not 0 <= size <= 1024 or len(payload) != 4+size:
            return None
        actor = memo.get('actor')
        if actor is not None:
            # Замер: внутри блока UID записан little-endian (тип3 = SET_HAND, тип4 = после бинта).
            for order in '<>':
                payload = payload.replace(struct.pack(order+'Q', actor), struct.pack(order+'Q', entity))
        return command, payload
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
        # Клиент шлёт только U8; tick и счётчик — как у 0x11D6 (текущий tick сцены, последний выстрел).
        return 0x11d8, payload + struct.pack('>QII', entity, memo.get('now_tick', memo.get('tick', 0)),
                                              memo.get('counter', 0))
    return None
