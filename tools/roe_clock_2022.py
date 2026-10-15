"""Замена только архивного UNIX-времени lobby1f5f, с корректной сборкой TCP."""
import struct
import time

from roe_protocol_2022 import FrameBuffer, dt_plain, encrypt


class LobbyClockStream:
    def __init__(self,key,now=time.time):
        self.key=key
        self.now=now
        self.frames=FrameBuffer()

    def feed(self,data):
        output=[]
        updates=[]
        for frame in self.frames.feed(data):
            result=frame
            # Только компактные server DT, не handshake/клиентские запросы.
            if frame[2:4]==bytes(2):
                plain=dt_plain(frame,self.key)
                if plain is not None and len(plain)==34:
                    code,tag=struct.unpack_from('>HI',plain,4)
                    if code==tag==0x1f5f:
                        timestamp=int(self.now())
                        if not 0<=timestamp<=0xffffffff:
                            raise ValueError('Серверный UNIX timestamp вне U32')
                        old=struct.unpack_from('>I',plain,26)[0]
                        patched=bytearray(plain)
                        struct.pack_into('>I',patched,26,timestamp)
                        head=struct.unpack_from('>I',frame,4)[0]
                        cipher=encrypt(bytes(patched),self.key)
                        header=bytearray(frame[:head])
                        struct.pack_into('>I',header,8,len(cipher))
                        result=bytes(header)+cipher
                        updates.append(dict(previous_server_seconds=old,
                                            server_seconds=timestamp))
            output.append(result)
        return b''.join(output),updates

    def finish(self):
        """Не скрывать незавершённый кадр при закрытии TCP-потока."""
        if self.frames.pending:
            raise ValueError('TCP-поток завершился внутри lobby-кадра')
