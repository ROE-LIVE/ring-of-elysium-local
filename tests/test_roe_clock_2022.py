"""Фрагментация lobby clock: менять только epoch, сохранять соседние кадры."""
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from roe_clock_2022 import LobbyClockStream
from roe_protocol_2022 import FrameBuffer, dt_plain
from roe_team_2022 import server_message

KEY=bytes(range(16))


class LobbyClockTests(unittest.TestCase):
    def test_fragmented_and_coalesced_frames_preserve_every_non_clock_byte(self):
        before=server_message(0x1f75,struct.pack('>I',7),100,KEY)
        clock=server_message(0x1f5f,struct.pack('>6I',1,0,18577351,50,1698070099,4),101,KEY)
        after=server_message(0x47a,bytes(4),102,KEY)
        source=before+clock+after
        stream=LobbyClockStream(KEY,now=lambda:1791432000)
        out=[];updates=[]
        for start in range(0,len(source),3):
            data,changes=stream.feed(source[start:start+3]);out.append(data);updates+=changes
        frames=FrameBuffer().feed(b''.join(out))
        stream.finish()
        self.assertEqual(frames[0],before)
        self.assertEqual(frames[2],after)
        words=struct.unpack('>6I',dt_plain(frames[1],KEY)[10:])
        self.assertEqual(words,(1,0,18577351,50,1791432000,4))
        self.assertEqual(dt_plain(frames[1],KEY)[:10],dt_plain(clock,KEY)[:10])
        self.assertEqual(updates,[dict(previous_server_seconds=1698070099,server_seconds=1791432000)])

    def test_wrong_length_is_not_guessed(self):
        short=server_message(0x1f5f,bytes(20),101,KEY)
        stream=LobbyClockStream(KEY,now=lambda:1791432000)
        out,changes=stream.feed(short)
        self.assertEqual((out,changes),(short,[]))

    def test_invalid_epoch_fails_before_forwarding_clock(self):
        clock=server_message(0x1f5f,struct.pack('>6I',1,0,1,50,1698070099,4),101,KEY)
        with self.assertRaises(ValueError):LobbyClockStream(KEY,now=lambda:-1).feed(clock)

    def test_truncated_frame_is_reported_at_eof(self):
        frame=server_message(0x1f75,struct.pack('>I',7),100,KEY)
        stream=LobbyClockStream(KEY)
        self.assertEqual(stream.feed(frame[:-1]),(b'',[]))
        with self.assertRaises(ValueError):
            stream.finish()
