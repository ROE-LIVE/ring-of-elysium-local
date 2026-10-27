"""Имя профиля лобби 0x2ef: строка BE64 длины, замена меняет длину (способ MLVP)."""
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from lobby_actor_uid_2022 import DEFAULT_PROFILE_NAME, LobbyActorUIDStream


class ProfileNameTests(unittest.TestCase):
    def test_replaces_length_prefixed_name_and_keeps_tail(self):
        old = DEFAULT_PROFILE_NAME + b'\0'
        plain = b'HEAD' * 4 + struct.pack('>Q', len(old)) + old + b'TAIL'
        patched = LobbyActorUIDStream.patch_profile_name(plain, 'Bernard')
        self.assertEqual(patched, b'HEAD' * 4 + struct.pack('>Q', 8) + b'Bernard\0' + b'TAIL')

    def test_unexpected_layout_is_left_alone(self):
        plain = b'HEAD' * 4 + struct.pack('>Q', 99) + DEFAULT_PROFILE_NAME + b'\0'
        self.assertIsNone(LobbyActorUIDStream.patch_profile_name(plain, 'Bernard'))


if __name__ == '__main__':
    unittest.main()
