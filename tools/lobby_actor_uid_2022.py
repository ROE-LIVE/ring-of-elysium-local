"""Явная идентичность локального клиента2022: UID и публичное имя лобби.

UID подставляется в ENTER_GAME_RSP (0x32b). Имя (profile_nickname) — в lobby-профиль
0x2ef: строка с BE64 длиной (байты + NUL); смена длины пересобирает AES-кадр.
Способ замены имени взят из MLVP/roe_server_previw (tools/lobby_actor_uid_2022.py).
"""
import struct
from roe_protocol_2022 import FrameBuffer, dt_plain, encrypt

# Имя профиля в записанном приветствии локального эмулятора лобби.
DEFAULT_PROFILE_NAME = b'BRING_BACK_ROE!!'


class LobbyActorUIDStream:
    def __init__(self, key, uid, profile_nickname=None):
        if type(uid) is not int or not 0 < uid < 2**64:
            raise ValueError('Local actor UID требует ненулевой U64')
        if profile_nickname is not None and not isinstance(profile_nickname, str):
            raise ValueError('profile_nickname должен быть строкой')
        self.key = key
        self.uid = uid
        self.profile_nickname = profile_nickname or None
        self.frames = FrameBuffer()

    def _rebuild(self, frame, plain):
        head = struct.unpack_from('>I', frame, 4)[0]
        cipher = encrypt(bytes(plain), self.key)
        header = bytearray(frame[:head])
        struct.pack_into('>I', header, 8, len(cipher))
        return bytes(header) + cipher

    @staticmethod
    def patch_profile_name(plain, nickname):
        index = plain.find(DEFAULT_PROFILE_NAME)
        if index < 8:
            return None
        length_at = index - 8
        if struct.unpack_from('>Q', plain, length_at)[0] != len(DEFAULT_PROFILE_NAME) + 1:
            return None
        if plain[index + len(DEFAULT_PROFILE_NAME)] != 0:
            return None
        encoded = nickname.encode('utf-8')
        if not 1 <= len(encoded) <= 127:
            raise ValueError('profile nickname: 1..127 байт UTF-8')
        new = encoded + b'\x00'
        return (bytes(plain[:length_at]) + struct.pack('>Q', len(new)) + new
                + bytes(plain[index + len(DEFAULT_PROFILE_NAME) + 1:]))

    def feed(self, data):
        output, updates = [], []
        for frame in self.frames.feed(data):
            result = frame
            if frame[2:4] == bytes(2):
                plain = dt_plain(frame, self.key)
                if plain is not None and len(plain) >= 10:
                    code, tag = struct.unpack_from('>HI', plain, 4)
                    # ENTER_GAME_RSP39: payload+12/decoded+22 — UID следующих
                    # клиентских заголовков. Не искать UID в произвольных профилях.
                    if code == tag == 0x32b and len(plain) == 39 and struct.unpack_from('>I', plain, 30)[0] == 0:
                        previous = struct.unpack_from('>Q', plain, 22)[0]
                        patched = bytearray(plain)
                        struct.pack_into('>Q', patched, 22, self.uid)
                        result = self._rebuild(frame, patched)
                        updates.append(dict(previous_actor_uid=hex(previous), actor_uid=hex(self.uid)))
                    elif code == tag == 0x2ef and self.profile_nickname:
                        patched = self.patch_profile_name(plain, self.profile_nickname)
                        if patched is not None:
                            result = self._rebuild(frame, patched)
                            updates.append(dict(update='local_profile_name',
                                                profile_nickname=self.profile_nickname))
            output.append(result)
        return b''.join(output), updates

    def finish(self):
        if self.frames.pending:
            raise ValueError('TCP-поток завершился внутри lobby-кадра')
