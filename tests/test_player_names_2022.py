"""Имена игроков: строка с реальной длиной в BE7 (модель у других) и 821 (пакет смерти)."""
from pathlib import Path
import struct
import sys
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server/directory'))
from death_parcel_2022 import name_field, replace_name
from peer_avatar_2022 import PeerAvatarRooms


class PlayerNameTests(unittest.TestCase):
    def test_name_field_uses_real_length_and_cuts_on_character_boundary(self):
        self.assertEqual(name_field('Alex'), struct.pack('>I', 5) + b'Alex\0')
        self.assertEqual(name_field('Nome muito comprido')[4:], b'Nome muito c\0')
        cut = name_field('Joãozinho123')
        cut[4:-1].decode('utf-8')
        self.assertLessEqual(len(cut) - 5, 12)

    def test_replace_name_shifts_following_fields(self):
        body = bytearray(40)
        struct.pack_into('>I', body, 12, 13)
        body[16:29] = b'elpapu190704\0'
        struct.pack_into('>I', body, 29, 0xABCD)
        new, shift = replace_name(body, 12, 'Ana')
        self.assertEqual(shift, -9)
        self.assertEqual(struct.unpack_from('>I', new, 29 + shift)[0], 0xABCD)
        self.assertEqual(len(new), 40 + shift)

    def test_remote_profile_name_appearance_and_position_after_shift(self):
        profile = bytearray(1516)
        struct.pack_into('>I', profile, 16, 13)
        profile[20:33] = b'elpapu190704\0'
        struct.pack_into('>5I', profile, 1240, 2201, 0, 0, 0, 0)
        rooms = PeerAvatarRooms(SimpleNamespace(listing=bytes(23), profile=bytes(profile)))
        member = dict(avatar=0x2040000100002, position=(1, 2, 3),
                      state=dict(actor_display_name='Jogador2',
                                 appearance=(struct.pack('>5I', 3401, 0, 0, 0, 0), 1)))
        body = dict(rooms.packets(member, 5))[0xbe7]
        shift = len('Jogador2') + 1 - 13
        self.assertEqual(body[16:16 + 4 + 9], struct.pack('>I', 9) + b'Jogador2\0')
        self.assertEqual(struct.unpack_from('>3i', body, 1051 + shift), (1, 2, 3))
        self.assertEqual(struct.unpack_from('>I', body, 1064 + shift)[0], 5)
        self.assertEqual(struct.unpack_from('>5I', body, 1240 + shift), (3401, 0, 0, 0, 0))
        self.assertEqual(len(body), 1516 + shift)


if __name__ == '__main__':
    unittest.main()
