"""Пересылка поворота/прицела/выстрела/анимации: размеры SYNC по декодерам клиента."""
from pathlib import Path
import struct
import sys
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server/directory'))
from peer_actions_2022 import relay_body
from game_endpoint_probe_2022 import Endpoint


class PeerActionTests(unittest.TestCase):
    def test_sync_sizes_follow_client_decoders(self):
        uid = 0x2040000100002
        code, body = relay_body(0x2f, bytes(range(12)), uid)
        self.assertEqual((code, len(body), body[:8]), (0x30, 20, struct.pack('>Q', uid)))
        code, body = relay_body(0x11d5, bytes(12), uid)
        self.assertEqual((code, len(body)), (0x11d6, 28))
        fire = struct.pack('>6fIBIIfII', 1, 2, 3, 4, 5, 6, 7, 0, 9, 10, 11.0, 12, 13)
        code, body = relay_body(0x11da, fire, uid)
        self.assertEqual((code, len(body)), (0x11d4, 33))
        self.assertEqual(struct.unpack_from('>3fIBII', body, 8), (1.0, 2.0, 3.0, 7, 0, 9, 10))
        code, body = relay_body(0x11d7, b'\x05', uid)
        self.assertEqual((code, len(body), body[0], struct.unpack_from('>Q', body, 1)[0]), (0x11d8, 17, 5, uid))
        self.assertIsNone(relay_body(0x11d5, bytes(11), uid))

    def test_endpoint_relays_only_to_other_room_members(self):
        sent = []
        a, b, c = dict(room_uid=1, actor_uid=10), dict(room_uid=1, actor_uid=11), dict(room_uid=2, actor_uid=12)
        fake = SimpleNamespace(
            peer_avatars=SimpleNamespace(members={(1, 10): dict(avatar=0xA, state=a), (1, 11): dict(avatar=0xB, state=b),
                                                  (2, 12): dict(avatar=0xC, state=c)}),
            emit_peer_avatars=lambda outputs, events: sent.extend(outputs),
            capture=SimpleNamespace(record=lambda *x, **y: None))
        Endpoint.relay_peer_action(fake, a, 0x2f, bytes(12))
        self.assertEqual(len(sent), 1)
        self.assertIs(sent[0][0], b)
        self.assertEqual(sent[0][1][0][0], 0x30)
        self.assertEqual(struct.unpack_from('>Q', sent[0][1][0][1])[0], 0xA)


if __name__ == '__main__':
    unittest.main()
