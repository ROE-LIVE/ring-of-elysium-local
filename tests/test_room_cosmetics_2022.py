"""Комната: внешность второго участника хранится отдельно от профиля хоста."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from local_cosmetics_2022 import LocalCosmetics
sys.path.insert(0, str(ROOT / 'server' / 'directory'))
from room_cosmetics_2022 import account_cosmetics
from peer_avatar_2022 import PeerAvatarRooms
from types import SimpleNamespace
import struct


class RoomCosmeticsTests(unittest.TestCase):
    def test_second_account_uses_separate_state_file(self):
        catalog = json.loads((ROOT / 'config' / 'cosmetics.json').read_text())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'cosmetics.json'
            catalog['state_file'] = 'state/cosmetics.json'
            path.write_text(json.dumps(catalog))
            host = LocalCosmetics(path)
            guest = LocalCosmetics(path, state_file='cosmetics-515bb18e59c77c.json')
            self.assertEqual(host.state_path, Path(directory) / 'state' / 'cosmetics.json')
            self.assertEqual(guest.state_path, Path(directory) / 'state' / 'cosmetics-515bb18e59c77c.json')
            guest.save()
            self.assertFalse(host.state_path.exists())
            self.assertTrue(guest.state_path.exists())

    def test_scene_server_picks_guest_file_only_when_it_exists(self):
        catalog = json.loads((ROOT / 'config' / 'cosmetics.json').read_text())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'cosmetics.json'
            catalog['state_file'] = 'state/cosmetics.json'
            path.write_text(json.dumps(catalog))
            self.assertEqual(account_cosmetics(path, 0x515bb18e59c77c).state_path.name, 'cosmetics.json')
            LocalCosmetics(path, state_file='cosmetics-515bb18e59c77c.json').save()
            self.assertEqual(account_cosmetics(path, 0x515bb18e59c77c).state_path.name, 'cosmetics-515bb18e59c77c.json')
            self.assertEqual(account_cosmetics(path, 0x515bb1e1dd242c).state_path.name, 'cosmetics.json')

    def test_remote_profile_carries_member_appearance(self):
        profile = bytearray(1516)
        struct.pack_into('>5I', profile, 1240, 2201, 0, 0, 0, 0)
        profile[1260] = 1
        rooms = PeerAvatarRooms(SimpleNamespace(listing=bytes(23), profile=bytes(profile)))
        member = dict(avatar=0x2040000100002, position=(1, 2, 3),
                      state=dict(appearance=(struct.pack('>5I', 3401, 0, 0, 0, 0), 1)))
        body = dict(rooms.packets(member, 5))[0xbe7]
        self.assertEqual(struct.unpack_from('>5I', body, 1240), (3401, 0, 0, 0, 0))
        member['state']['appearance'] = (bytes(20), 0)
        body = dict(rooms.packets(member, 5))[0xbe7]
        self.assertEqual(struct.unpack_from('>I', body, 1240)[0], 2201)


if __name__ == '__main__':
    unittest.main()
