"""Явная идентичность одного локального клиента2022; без общего мира/аккаунтов."""
import struct
from roe_protocol_2022 import FrameBuffer, dt_plain, encrypt


class LobbyActorUIDStream:
    def __init__(self,key,uid):
        if type(uid) is not int or not 0 < uid < 2**64:
            raise ValueError('Local actor UID требует ненулевой U64')
        self.key = key
        self.uid = uid
        self.frames = FrameBuffer()

    def feed(self,data):
        output, updates = [], []
        for frame in self.frames.feed(data):
            result = frame
            if frame[2:4] == bytes(2):
                plain = dt_plain(frame,self.key)
                # ENTER_GAME_RSP39: payload+12/decoded+22 — UID следующих
                # клиентских заголовков. Не искать UID в произвольных профилях.
                if plain is not None and len(plain) == 39:
                    code,tag = struct.unpack_from('>HI',plain,4)
                    if code == tag == 0x32b and struct.unpack_from('>I',plain,30)[0] == 0:
                        previous = struct.unpack_from('>Q',plain,22)[0]
                        patched = bytearray(plain)
                        struct.pack_into('>Q',patched,22,self.uid)
                        head = struct.unpack_from('>I',frame,4)[0]
                        cipher = encrypt(bytes(patched),self.key)
                        header = bytearray(frame[:head])
                        struct.pack_into('>I',header,8,len(cipher))
                        result = bytes(header)+cipher
                        updates.append(dict(previous_actor_uid=hex(previous),actor_uid=hex(self.uid)))
            output.append(result)
        return b''.join(output),updates

    def finish(self):
        if self.frames.pending:
            raise ValueError('TCP-поток завершился внутри lobby-кадра')
