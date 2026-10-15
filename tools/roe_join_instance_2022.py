"""Тело JOIN_INSTANCE_RSP 0xd76 по decoder EXE 2022 0x140c4a4f0.

Транспортный заголовок и native command-tag сюда не входят. Назначение двух
16-байтовых блоков окончательно не установлено; они исключены из repr.
"""

from dataclasses import dataclass, field
import struct


@dataclass(frozen=True)
class JoinInstanceResponse:
    result: int
    route: bytes
    block_88: bytes = field(repr=False)
    block_98: bytes = field(repr=False)
    connection_id_a8: int
    unknown_ac: int
    flag_b0: int


@dataclass(frozen=True)
class JoinInstanceNotification:
    """Поля decoder 0x140c4a7e0; unknown_* — смещения без native command-tag."""
    unknown_00: int
    instance_id: int
    unknown_0c: int
    unknown_14: int
    unknown_18: int
    unknown_20: int
    unknown_28: int
    unknown_2c: int


def _uint(value, bits, name):
    if type(value) is not int or not 0 <= value < (1 << bits):
        raise ValueError(f"{name}: требуется U{bits}")
    return value


def _route(value):
    if not isinstance(value, bytes) or len(value) > 127 or b"\0" in value:
        raise ValueError("route: максимум 127 байт без внутренних NUL")
    return value + b"\0"


def encode_join_instance_response(message):
    """Собрать тело; соответствие Training и валидность авторизации не обещаются."""
    route = _route(message.route)
    for block in (message.block_88, message.block_98):
        if not isinstance(block, bytes) or len(block) != 16:
            raise ValueError("Блок должен содержать ровно 16 байт")
    return (
        struct.pack(">II", _uint(message.result, 32, "result"), len(route))
        + route + message.block_88 + message.block_98
        + struct.pack(">IIB", _uint(message.connection_id_a8, 32, "connection_id_a8"),
                      _uint(message.unknown_ac, 32, "unknown_ac"),
                      _uint(message.flag_b0, 8, "flag_b0"))
    )


def decode_join_instance_response(payload):
    """Строгий разбор одного тела без хвоста; байты блоков не печатаются."""
    if not isinstance(payload, (bytes, bytearray, memoryview)):
        raise ValueError("Требуется байтовое тело пакета")
    payload = bytes(payload)
    if len(payload) < 8:
        raise ValueError("Обрезанный заголовок JOIN_INSTANCE_RSP")
    result, length = struct.unpack_from(">II", payload)
    if not 1 <= length <= 128:
        raise ValueError("Длина route с NUL должна быть от 1 до 128")
    if len(payload) != 49 + length:
        raise ValueError("Обрезанное тело или лишний хвост JOIN_INSTANCE_RSP")
    route = payload[8:8 + length]
    if route[-1:] != b"\0" or b"\0" in route[:-1]:
        raise ValueError("route должен иметь единственный конечный NUL")
    at = 8 + length
    connection_id, unknown, flag = struct.unpack_from(">IIB", payload, at + 32)
    return JoinInstanceResponse(result, route[:-1], payload[at:at + 16],
                                payload[at + 16:at + 32], connection_id, unknown, flag)


def encode_join_instance_request(instance_id):
    """Тело JOIN_INSTANCE_REQ 0xd75: один BE64, decoder 0x140c45fe0."""
    return struct.pack(">Q", _uint(instance_id, 64, "instance_id"))


def decode_join_instance_request(payload):
    if not isinstance(payload, (bytes, bytearray, memoryview)) or len(payload) != 8:
        raise ValueError("JOIN_INSTANCE_REQ должен содержать ровно 8 байт")
    return struct.unpack(">Q", payload)[0]


def encode_join_instance_notification(message):
    """Тело 0xd77: 48 байт; значения неизвестных полей не подбираются."""
    names = ("unknown_00", "instance_id", "unknown_0c", "unknown_14",
             "unknown_18", "unknown_20", "unknown_28", "unknown_2c")
    widths = (32, 64, 64, 32, 64, 64, 32, 32)
    values = [_uint(getattr(message, name), bits, name)
              for name, bits in zip(names, widths)]
    return struct.pack(">IQQIQQII", *values)


def decode_join_instance_notification(payload):
    if not isinstance(payload, (bytes, bytearray, memoryview)) or len(payload) != 48:
        raise ValueError("JOIN_INSTANCE_NOTIFY должен содержать ровно 48 байт")
    return JoinInstanceNotification(*struct.unpack(">IQQIQQII", payload))
