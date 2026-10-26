"""Имена игроков в полях фиксированной длины: модель у других, пакет смерти."""
from pathlib import Path
import struct
import sys
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server/directory'))
from death_parcel_2022 import fixed_name
from peer_avatar_2022 import PeerAvatarRooms


class PlayerNameTests(unittest.TestCase):
    def test_fixed_name_keeps_13_bytes_and_cuts_on_character_boundary(self):
        self.assertEqual(fixed_name('Alex'), b'Alex' + bytes(9))
        self.assertEqual(len(fixed_name('Nome muito comprido')), 13)
        self.assertEqual(fixed_name('Nome muito comprido')[:12], b'Nome muito c')
        cut = fixed_name('Joãozinho123')  # «ã» = 2 байта: не разрывать символ
        self.assertEqual(len(cut), 13)
        cut[:12].rstrip(b'\0').decode('utf-8')

    def test_remote_profile_shows_member_name(self):
        profile = bytearray(1516)
        struct.pack_into('>I', profile, 16, 13)
        profile[20:33] = b'elpapu190704\0'
        rooms = PeerAvatarRooms(SimpleNamespace(listing=bytes(23), profile=bytes(profile)))
        member = dict(avatar=0x2040000100002, position=(1, 2, 3), state=dict(actor_display_name='Bernard'))
        body = dict(rooms.packets(member, 5))[0xbe7]
        self.assertEqual(struct.unpack_from('>I', body, 16)[0], 13)
        self.assertEqual(body[20:33], b'Bernard' + bytes(6))


if __name__ == '__main__':
    unittest.main()
