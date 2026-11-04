"""Небольшие подтверждённые wire-схемы сцены из клиента 2022 и PCAP 2023.

Имена неизвестных полей обозначают положение/тип, а не игровую семантику.
В частности, масштаб трёх координатных чисел здесь не предполагается.
"""
import struct


def decode_unit_attributes(payload: bytes) -> list[dict]:
    """0x106a, decoder 140c2ad90: 120 записей U8/BE32/BE32 без UID.

    Индекс определяется порядком. Семантика типа и слов пока не установлена.
    """
    if len(payload) != 1080:
        raise ValueError('Неверная длина BC_UNIT_ATTR_SYNC')
    return [dict(index=index, type=kind, word_0=first, word_1=second)
            for index, (kind, first, second) in
            enumerate(struct.iter_unpack('>BII', payload))]


def decode_move_request(payload: bytes) -> dict:
    """0x2a, decoder 0x140c56410: длина строго 27 + 28*N, 0 <= N <= 20."""
    if len(payload) < 27:
        raise ValueError('Неполный MOVE_1')
    count = struct.unpack_from('>i', payload)[0]
    if not 0 <= count <= 20 or len(payload) != 27 + 28 * count:
        raise ValueError('Неверное число точек или длина MOVE_1')
    points = []
    at = 4
    for _ in range(count):
        x, y, z, byte_0, byte_1, byte_2, value = struct.unpack_from('>iiiBBBI', payload, at)
        points.append(dict(position=(x, y, z), bytes=(byte_0, byte_1, byte_2), value=value))
        at += 19
    word_0, byte_0, float_0, float_1, float_2, word_1, byte_1, byte_2 = struct.unpack_from('>IBfffIBB', payload, at)
    at += 23
    extras = [struct.unpack_from('>BQ', payload, at + 9 * i) for i in range(count)]
    return dict(count=count, points=points, word_0=word_0,
                bytes=(byte_0, byte_1, byte_2), floats=(float_0, float_1, float_2),
                word_1=word_1, extras=extras)


def decode_bc_move(payload: bytes) -> dict:
    """0x25, decoder 0x140c59870: U64 сущность, 38 + 12*N байт, N <= 20."""
    if len(payload) < 38:
        raise ValueError('Неполный BC_MOVE_1')
    entity, word_0, x, y, z, byte_0, byte_1, value, count = struct.unpack_from('>QHiiiBBIB', payload)
    if count > 20 or len(payload) != 38 + 12 * count:
        raise ValueError('Неверное число точек или длина BC_MOVE_1')
    points = [struct.unpack_from('>hhhBBI', payload, 29 + 12 * i) for i in range(count)]
    tail = struct.unpack_from('>BHHI', payload, 29 + 12 * count)
    return dict(entity=entity, word_0=word_0, position=(x, y, z),
                bytes=(byte_0, byte_1), value=value, count=count, points=points, tail=tail)


def decode_bc_move_sync(payload: bytes) -> dict:
    """0x27, decoder 0x140c5a0e0: точные 40 байт синхронизации actor.

    Координатные числа и неизвестные слова сохраняются без смены масштаба.
    word_1 передаётся handler в 141185ee0 → 140e88150 как статус движения.
    """
    if len(payload) != 40:
        raise ValueError('Неверная длина BC_MOVE_SYNC_1')
    entity, x, y, z, byte_0, byte_1, byte_2, word_0, word_1, word_2, byte_3, word_3 = struct.unpack('>QiiiBBBIIIBI', payload)
    return dict(entity=entity, position=(x, y, z), bytes=(byte_0, byte_1, byte_2, byte_3),
                word_0=word_0, movement_status=word_1, word_2=word_2, word_3=word_3)


def decode_conn_auth_request(payload: bytes) -> dict:
    """0x406, decoder 0x140c3a730: U64, U32, 16 сырых байт, U32."""
    if len(payload) != 32:
        raise ValueError('Неверная длина CONN_AUTH_REQ')
    identifier, word_0 = struct.unpack_from('>QI', payload)
    return dict(identifier=identifier, word_0=word_0, token=payload[12:28],
                word_1=struct.unpack_from('>I', payload, 28)[0])


def decode_enter_room_request(payload: bytes) -> dict:
    """0xdce, decoder 0x140c3a870: U64, U32, U64."""
    if len(payload) != 20:
        raise ValueError('Неверная длина ENTER_ROOM_REQ')
    first, word, second = struct.unpack('>QIQ', payload)
    return dict(first_identifier=first, word=word, second_identifier=second)


def decode_scene_bootstrap(payload: bytes, code: int) -> dict:
    """Короткие схемы подготовки/выбора точки, подтверждённые EXE и PCAP.

    0x47a/0x482: decoder 0x140bcd260; 0x483: 0x140bcd1f0;
    0x484/0x486: 0x140c27d10. Для неизвестного байта запроса смысл не задан.
    Названия слов таймера описывают формат; связь с deadline — в отчёте.
    """
    schemas = {
        0x47a: ('>I', ('prepare_status',)),
        0x482: ('>I', ('selection_seconds',)),
        0x483: ('>B', ('request_byte',)),
        0x484: ('>II', ('tick_word', 'millisecond_word')),
        0x486: ('>II', ('loaded_count', 'total_count')),
    }
    if code not in schemas:
        raise ValueError('Неподдерживаемая команда подготовки сцены')
    fmt, names = schemas[code]
    if len(payload) != struct.calcsize(fmt):
        raise ValueError(f'Неверная длина сообщения {code:#x}')
    return dict(zip(names, struct.unpack(fmt, payload)))
