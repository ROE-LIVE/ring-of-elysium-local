"""UID влияет только на проверенный успешный32B; TCP соседние кадры неизменны."""
from pathlib import Path
import struct,sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from lobby_actor_uid_2022 import LobbyActorUIDStream
from roe_protocol_2022 import FrameBuffer,dt_plain
from roe_team_2022 import server_message
KEY=bytes(range(16))

class ActorUIDTests(unittest.TestCase):
    def test_fragmented_enter_rewrites_only_public_uid_and_preserves_other_frames(self):
        body=bytes(12)+struct.pack('>QI',123,0)+bytes(5)
        before=server_message(0x1f75,bytes(4),7,KEY)
        enter=server_message(0x32b,body,8,KEY)
        after=server_message(0x47a,bytes(4),9,KEY)
        stream=LobbyActorUIDStream(KEY,456);out=[];events=[]
        data=before+enter+after
        for at in range(0,len(data),3):
            chunk,event=stream.feed(data[at:at+3]);out.append(chunk);events+=event
        stream.finish();frames=FrameBuffer().feed(b''.join(out))
        self.assertEqual(frames[0],before);self.assertEqual(frames[2],after)
        plain=dt_plain(frames[1],KEY);old=dt_plain(enter,KEY)
        self.assertEqual(plain[:22]+plain[30:],old[:22]+old[30:])
        self.assertEqual(struct.unpack_from('>Q',plain,22)[0],456)
        self.assertEqual(events,[dict(previous_actor_uid='0x7b',actor_uid='0x1c8')])
    def test_unsuccessful_and_wrong_size_enter_are_not_rewritten(self):
        for body in [bytes(28),bytes(12)+struct.pack('>QI',123,1)+bytes(5)]:
            source=server_message(0x32b,body,8,KEY)
            self.assertEqual(LobbyActorUIDStream(KEY,456).feed(source),(source,[]))
    def test_uid_and_truncated_stream_validation(self):
        for uid in [0,-1,2**64,True]:
            with self.assertRaises(ValueError):LobbyActorUIDStream(KEY,uid)
        stream=LobbyActorUIDStream(KEY,123)
        source=server_message(0x32b,bytes(29),8,KEY)
        self.assertEqual(stream.feed(source[:-1]),(b'',[]))
        with self.assertRaises(ValueError):stream.finish()

if __name__=='__main__':unittest.main()
