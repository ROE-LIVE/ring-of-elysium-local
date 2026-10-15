"""Проверенные рамки игрового UDP/TGCP из захватов Shy за октябрь 2023.

Это офлайн reader, не реализация игрового сервера. Заголовки команд
с переменными union-полями пока сохраняются как байты.
"""
from dataclasses import dataclass
import struct

def packet_hash(data: bytes) -> int:
    """Хвостовой хеш tcp_pcb::on_packet_out, адрес 0x141a5e700 клиента 2022."""
    result = 0
    for value in data:
        result = (result * 33 + value) & 0xffffffff
    return result & 0x7fffffff

@dataclass(frozen=True)
class Datagram:
    source_port: int
    destination_port: int
    sequence: int
    acknowledgement: int
    flags: int
    window: int
    clock: int
    echoed_clock: int
    data: bytes
    extra_header: bytes = b''

def parse_datagram(data: bytes) -> Datagram:
    """Разобрать базовые20байт и объявленное расширение; проверить LE32-хеш."""
    if len(data) < 24:
        raise ValueError('Неполная UDP-рамка')
    if struct.unpack_from('<I', data, len(data) - 4)[0] != packet_hash(data[:-4]):
        raise ValueError('Неверный UDP-хеш')
    header_length = (data[12] >> 4) * 4
    if header_length < 20 or header_length + 4 > len(data):
        raise ValueError('Неверная длина UDP-заголовка')
    # Native2022 под reorder отправляет ACK с header24/28. Расширение пока
    # непрозрачное: не считать его TGCP body и не выводить семантику DWORD.
    source, destination, sequence, acknowledgement = struct.unpack_from('>HHII', data)
    window = struct.unpack_from('>H', data, 14)[0]
    echoed, clock = struct.unpack_from('<HH', data, 16)
    return Datagram(source, destination, sequence, acknowledgement, data[13], window,
                    clock, echoed, data[header_length:-4], data[20:header_length])

@dataclass(frozen=True)
class Frame:
    version: int
    command_version: int
    command: int
    flag: int
    sequence: int
    extra_header: bytes
    body: bytes
    size: int

def parse_frame(data: bytes, offset: int=0) -> Frame:
    """Разобрать одну полную TGCP-рамку; хвост может содержать следующую."""
    if offset < 0 or len(data) - offset < 21:
        raise ValueError('Неполный TGCP-заголовок')
    magic, version, command_version, command, flag, sequence, head, body = struct.unpack_from('>HHHHBIII', data, offset)
    if magic != 0x3366:
        raise ValueError('Неверная TGCP-сигнатура')
    if head < 21 or head + body > len(data) - offset:
        raise ValueError('Неполная или неверная TGCP-рамка')
    return Frame(version, command_version, command, flag, sequence, data[offset + 21:offset + head], data[offset + head:offset + head + body], head + body)

def direct_session_key(frame: Frame) -> bytes:
    """Только наблюдаемая ветка 1002/selector=2 с открытым ключевым блоком."""
    extra = frame.extra_header
    if frame.command != 0x1002 or frame.version != 10 or len(extra) != 27:
        raise ValueError('Неизвестная схема ключевого ответа')
    if extra[:2] != b'\x02\x10':
        raise ValueError('Неизвестный способ получения ключа')
    return extra[2:18]

def contiguous_streams(segments):
    """Соединить (sequence, bytes) без заполнения пропусков выдуманными байтами.

    Допускаются повторы и одинаковые перекрытия. Разные перекрывающиеся
    байты отвергаются. Поток должен занимать менее 2**31 sequence-позиций.
    Возвращает список (начальный sequence, bytes), раздельно для каждого
    участка без пропусков. SYN/FIN сюда не передаются.
    """
    segments = [(sequence, bytes(data)) for sequence, data in segments if data]
    if not segments:
        return []
    anchor = segments[0][0]
    positioned = sorted((((sequence - anchor + 0x80000000 & 0xffffffff) - 0x80000000, data) for sequence, data in segments))
    chunks = []
    start = None
    current = bytearray()
    for position, data in positioned:
        if start is None or position > start + len(current):
            if start is not None:
                chunks.append((anchor + start & 0xffffffff, bytes(current)))
            start, current = (position, bytearray(data))
            continue
        overlap = min(len(data), start + len(current) - position)
        relative = position - start
        if current[relative:relative + overlap] != data[:overlap]:
            raise ValueError('Противоречивое перекрытие UDP-сегментов')
        current.extend(data[overlap:])
    chunks.append((anchor + start & 0xffffffff, bytes(current)))
    return chunks

def decompress_lz4_block(data: bytes, maximum: int = 8 * 1024 * 1024) -> bytes:
    """Разобрать raw LZ4-блок с ограничением размера и проверкой смещений."""
    out = bytearray()
    at = 0
    while at < len(data):
        token = data[at]
        at += 1
        literal = token >> 4
        if literal == 15:
            while True:
                if at >= len(data):
                    raise ValueError('literal extension')
                n = data[at]
                at += 1
                literal += n
                if n < 255:
                    break
        if at + literal > len(data) or len(out) + literal > maximum:
            raise ValueError('literal length')
        out.extend(data[at:at + literal])
        at += literal
        if at == len(data):
            return bytes(out)
        if at + 2 > len(data):
            raise ValueError('offset')
        distance = struct.unpack_from('<H', data, at)[0]
        at += 2
        if not 0 < distance <= len(out):
            raise ValueError('match distance')
        match = (token & 15) + 4
        if token & 15 == 15:
            while True:
                if at >= len(data):
                    raise ValueError('match extension')
                n = data[at]
                at += 1
                match += n
                if n < 255:
                    break
        if len(out) + match > maximum:
            raise ValueError('output limit')
        for _ in range(match):
            out.append(out[-distance])
    raise ValueError('missing final literals')


@dataclass(frozen=True)
class ApplicationMessage:
    command: int
    stamp: int
    sequence: int | None
    payload: bytes
    decoded: bytes


def _parse_application_bytes(data: bytes, direction: str) -> ApplicationMessage:
    if direction == 'client':
        if len(data) < 34:
            raise ValueError('Неполный клиентский заголовок')
        sequence, length, command = struct.unpack_from('>IIH', data)
        if length != len(data) - 4:
            raise ValueError('Неверная длина клиентского сообщения')
        stamp = struct.unpack_from('>I', data, 14)[0]
        tag = struct.unpack_from('>I', data, 30)[0]
        payload = data[34:]
    else:
        if len(data) < 10:
            raise ValueError('Неполный серверный заголовок')
        stamp, command, tag = struct.unpack_from('>IHI', data)
        sequence = None
        payload = data[10:]
    if command != tag:
        raise ValueError('Код команды не совпадает с body-tag')
    return ApplicationMessage(command, stamp, sequence, payload, data)


def parse_applications(frame: Frame, plaintext: bytes, direction: str) -> list[ApplicationMessage]:
    """Распаковать и разделить сообщения 4013 наблюдаемой версии 10.

    Первый байт extra_header задаёт сжатие, четвёртый — количество
    BE16-длин первых сообщений. Последняя длина определяется остатком.
    Для selector=1/2 требуется другая union-схема, здесь она не поддержана.
    """
    extra = frame.extra_header
    if frame.command != 0x4013 or frame.version != 10 or len(extra) < 4:
        raise ValueError('Неизвестная схема прикладного заголовка')
    if extra[2] in (1, 2):
        raise ValueError('Неподдерживаемый union-selector')
    compression, count = extra[0], extra[3]
    if compression not in (0, 1) or count == 255 or len(extra) != 4 + 2 * count:
        raise ValueError('Неверный заголовок сжатия или объединения')
    if direction not in ('client', 'server'):
        raise ValueError('Неизвестное направление')
    data = plaintext
    if compression:
        data = (plaintext[:4] + decompress_lz4_block(plaintext[4:])
                if direction == 'client' else decompress_lz4_block(plaintext))
    sizes = [struct.unpack_from('>H', extra, 4 + 2 * i)[0] for i in range(count)]
    sizes.append(len(data) - sum(sizes))
    minimum = 34 if direction == 'client' else 10
    if any(size < minimum for size in sizes):
        raise ValueError('Неверные длины объединённых сообщений')
    messages, at = [], 0
    for size in sizes:
        messages.append(_parse_application_bytes(data[at:at + size], direction))
        at += size
    return messages


def parse_application(frame: Frame, plaintext: bytes, direction: str) -> ApplicationMessage:
    """Разобрать одиночное сообщение; объединённые читает parse_applications."""
    messages = parse_applications(frame, plaintext, direction)
    if len(messages) != 1:
        raise ValueError('В рамке несколько сообщений; используйте parse_applications')
    return messages[0]
