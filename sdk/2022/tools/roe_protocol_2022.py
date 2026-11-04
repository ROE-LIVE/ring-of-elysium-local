"""Минимальный режим AES/DT клиента 2022 по session-06; не протокол матча."""
import os
import struct

MAGIC = b'\x55\x0e'
IV = bytes(range(16))
MARKER = b'tsf4g'
MAX_FRAME = 2 * 1024 * 1024


class FrameBuffer:
    """Собирает кадры из фрагментированного TCP-потока с пределом длины."""
    def __init__(self):
        self.pending = bytearray()

    def feed(self, data):
        self.pending.extend(data)
        frames = []
        while len(self.pending) >= 12:
            if self.pending[:2] != MAGIC:
                raise ValueError('Неверная сигнатура кадра')
            head, body = struct.unpack_from('>II', self.pending, 4)
            length = head + body
            if head < 12 or length > MAX_FRAME:
                raise ValueError('Недопустимая длина кадра')
            if len(self.pending) < length:
                break
            frames.append(bytes(self.pending[:length]))
            del self.pending[:length]
        return frames


def encrypt(plain, key):
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    if len(key) != 16:
        raise ValueError('Нужен 16-байтный session key')
    pad = (16 if len(plain) % 16 < 11 else 32) - len(plain) % 16
    padded = plain + os.urandom(pad - 6) + MARKER + bytes([pad])
    ctx = Cipher(algorithms.AES(key), modes.CBC(IV)).encryptor()
    return ctx.update(padded) + ctx.finalize()


def decrypt(cipher, key):
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    if len(key) != 16 or not cipher or len(cipher) % 16:
        raise ValueError('Неверная длина ключа или AES-тела')
    ctx = Cipher(algorithms.AES(key), modes.CBC(IV)).decryptor()
    padded = ctx.update(cipher) + ctx.finalize()
    if padded[-6:-1] != MARKER:
        raise ValueError('Не совпал маркер AES-padding; проверьте session key')
    pad = padded[-1]
    if not 6 <= pad <= 21 or pad > len(padded):
        raise ValueError('Неверная длина AES-padding')
    plain = padded[:-pad]
    expected = (16 if len(plain) % 16 < 11 else 32) - len(plain) % 16
    if pad != expected:
        raise ValueError('Несогласованная длина AES-padding')
    return plain


def dt_plain(frame, key):
    if len(frame) < 12 or frame[:2] != MAGIC:
        raise ValueError('Неверный кадр')
    head, body = struct.unpack_from('>II', frame, 4)
    if head < 12 or head + body != len(frame):
        raise ValueError('Несогласованная длина кадра')
    if frame[2] != 0:
        return None
    return decrypt(frame[head:], key)


def client_heartbeat(frame, key):
    plain = dt_plain(frame, key)
    if plain is None or len(plain) < 34:
        return None
    # Префикс BE32 транспорта присутствует в наблюдаемом направлении клиента.
    if frame[3] & 4 == 0:
        return None
    length, code = struct.unpack_from('>IH', plain, 4)
    tag = struct.unpack_from('>I', plain, 30)[0]
    if length != len(plain) - 4 or code != tag:
        raise ValueError('Не совпали длина/тег прикладного сообщения')
    if code != 0x1f74:
        return None
    if len(plain) != 38:
        raise ValueError('Heartbeat должен содержать один BE32')
    return struct.unpack_from('>I', plain, 34)[0]


def server_stamp(frame, key):
    # Формат наблюдавшегося сервера: Flag=0, компактный заголовок BE32+BE16.
    if frame[3] != 0:
        return None
    plain = dt_plain(frame, key)
    if plain is None or len(plain) < 10:
        return None
    stamp, code, tag = struct.unpack_from('>IHI', plain)
    if code != tag:
        raise ValueError('Не совпали код и тег серверного сообщения')
    return stamp


def heartbeat_reply(counter, stamp, key):
    # Первый BE32 — поле компактного заголовка, а не дополнительный seq-prefix.
    plain = struct.pack('>IHII', stamp, 0x1f75, 0x1f75, counter)
    cipher = encrypt(plain, key)
    return MAGIC + b'\0\0' + struct.pack('>II', 12, len(cipher)) + cipher
