"""Ограниченный экспериментальный sender; параметры принадлежат нашему стенду."""
from collections import OrderedDict
from dataclasses import dataclass
import struct


MASK = 0xffffffff


@dataclass
class Pending:
    raw: bytes
    end: int
    deadline: float
    attempts: int = 0


class ReliableSender:
    """Cumulative ACK в serial32; повторяется исходная датаграмма целиком.

    Это не восстановленные константы клиента. Переполнение и исчерпание
    повторов останавливают sender явно, вместо молчаливой потери ответа.
    """
    def __init__(self, initial, interval=.25, maximum_interval=2., attempts=15,
                 maximum_packets=2048, maximum_bytes=1048576):
        self.ack = initial & MASK
        self.high = self.ack
        self.pending = OrderedDict()
        self.bytes = 0
        self.interval = interval
        self.maximum_interval = maximum_interval
        self.attempts = attempts
        self.maximum_packets = maximum_packets
        self.maximum_bytes = maximum_bytes
        self.failed = False

    def remember(self, raw, sequence, length, now):
        if self.failed:
            return False
        if (len(self.pending) >= self.maximum_packets or
                self.bytes + len(raw) > self.maximum_bytes):
            self.failed = True
            return False
        sequence &= MASK
        if sequence != self.high or not 0 < length < 0x80000000:
            raise ValueError('Неупорядоченная исходящая граница sequence')
        self.high = (sequence + length) & MASK
        self.pending[sequence] = Pending(raw, self.high, now + self.interval)
        self.bytes += len(raw)
        return True

    def acknowledge(self, acknowledgement):
        acknowledgement &= MASK
        advance = (acknowledgement - self.ack) & MASK
        outstanding = (self.high - self.ack) & MASK
        if advance == 0 or advance >= 0x80000000 or advance > outstanding:
            return False
        previous = self.ack
        self.ack = acknowledgement
        for sequence, packet in list(self.pending.items()):
            distance = (packet.end - previous) & MASK
            if distance <= advance:
                self.bytes -= len(packet.raw)
                del self.pending[sequence]
        return True

    def due(self, now):
        if self.failed:
            return []
        ready = []
        for sequence, packet in self.pending.items():
            if now < packet.deadline:
                continue
            if packet.attempts >= self.attempts:
                self.failed = True
                return []
            packet.attempts += 1
            packet.deadline = now + min(self.maximum_interval,
                                        self.interval * 2 ** packet.attempts)
            ready.append((sequence, packet.raw, packet.attempts))
        return ready


class ReliableReceiver:
    """Окно byte-stream serial32 с ограниченными, согласованными перекрытиями.

    Подтверждается только непрерывный префикс. Уже потреблённый повтор
    игнорируется; противоречивое перекрытие ещё ожидающих данных отклоняется.
    """
    def __init__(self, initial, window=65535, maximum_segments=256):
        self.next = initial & MASK
        self.window = window
        self.maximum_segments = maximum_segments
        self.pending = []

    def accept(self, sequence, data):
        if not data:
            return b''
        sequence &= MASK
        distance = (sequence - self.next) & MASK
        if distance >= 0x80000000:
            consumed = (self.next - sequence) & MASK
            if consumed >= len(data):
                return b''
            data = data[consumed:]
            sequence = self.next
            distance = 0
        if distance + len(data) > self.window:
            raise ValueError('Сегмент вне ограниченного входного окна')
        candidates = self.pending + [(sequence, bytes(data))]
        candidates.sort(key=lambda entry: (entry[0] - self.next) & MASK)
        merged = []
        for start, body in candidates:
            offset = (start - self.next) & MASK
            if not merged:
                merged.append((offset, body))
                continue
            previous, value = merged[-1]
            end = previous + len(value)
            if offset > end:
                merged.append((offset, body))
                continue
            overlap = min(end - offset, len(body))
            if overlap and value[offset-previous:offset-previous+overlap] != body[:overlap]:
                raise ValueError('Противоречивое перекрытие входных сегментов')
            merged[-1] = (previous, value + body[overlap:])
        contiguous = b''
        if merged and merged[0][0] == 0:
            _, contiguous = merged.pop(0)
        if len(merged) > self.maximum_segments:
            raise ValueError('Превышен предел входных сегментов')
        # Мутация только после всех проверок; ошибочный сегмент не двигает ACK.
        self.pending = [((self.next + start) & MASK, body) for start, body in merged]
        self.next = (self.next + len(contiguous)) & MASK
        return contiguous


class FrameStream:
    """Выделяет целые TGCP3366 frames независимо от UDP/PSH границ."""
    def __init__(self, maximum_frame=65535, maximum_header=4096):
        self.maximum_frame = maximum_frame
        self.maximum_header = maximum_header
        self.buffer = bytearray()
        self.failed = False

    def feed(self, data):
        if self.failed:
            raise ValueError('Входной TGCP stream уже отклонён')
        if len(data) > 65535:
            raise ValueError('Слишком большой непрерывный входной блок')
        self.buffer.extend(data)
        frames = []
        try:
            while len(self.buffer) >= 21:
                magic = struct.unpack_from('>H', self.buffer)[0]
                header, body = struct.unpack_from('>II', self.buffer, 13)
                length = header + body
                if (magic != 0x3366 or not 21 <= header <= self.maximum_header
                        or length > self.maximum_frame):
                    raise ValueError('Недопустимая ограниченная TGCP frame')
                if len(self.buffer) < length:
                    break
                frames.append(bytes(self.buffer[:length]))
                del self.buffer[:length]
        except ValueError:
            self.buffer.clear()
            self.failed = True
            raise
        return frames
