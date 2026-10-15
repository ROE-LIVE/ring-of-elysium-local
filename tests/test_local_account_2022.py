"""Изоляция устойчивого выбора профилей2022 и новые сеансы без утраты выбора."""
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from local_account_2022 import DEFAULT_ACTOR_UID, local_account
from local_cosmetics_2022 import LocalCosmetics


class LocalAccountTests(unittest.TestCase):
    def test_default_keeps_existing_state_and_named_accounts_are_stable(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            default = local_account(root)
            self.assertEqual(default['actor_uid'], DEFAULT_ACTOR_UID)
            self.assertEqual(Path(default['state_file']), root / 'local-account/cosmetics.json')
            a, b = local_account(root, 'Alice'), local_account(root, 'bob')
            self.assertEqual(a, local_account(root, 'ALICE'))
            self.assertNotEqual(a['actor_uid'], b['actor_uid'])
            self.assertNotEqual(a['state_file'], b['state_file'])
            self.assertEqual(a['actor_uid'] & 3, 0)
            self.assertFalse(list(root.iterdir()))

    def test_path_traversal_aliases_and_windows_device_names_rejected(self):
        for name in ('', '../a', 'a/b', 'a\\b', '.a', 'a.', 'a ', 'con', 'COM1', 'lpt9',
                     'имя', 'a' * 33, None, True):
            with self.subTest(name=name), self.assertRaises(ValueError):
                local_account('/unused', name)

    def test_a_b_a_preserves_separate_character_skin_and_clothing(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            configs = {}
            for name in ('alice', 'bob'):
                account = local_account(root, name)
                config = root / (name + '.json')
                config.write_text(json.dumps(dict(owned_gun_skin_ids=[10402210],
                    weapon_skin_to_weapon={'10402210': 10402}, owned_character_ids=[407],
                    owned_clothing_ids=[1000023], clothing_inventory_container=6,
                    clothing_equipment_slots={'1000023': 22}, state_file=account['state_file'])))
                configs[name] = config
            a = LocalCosmetics(configs['alice'])
            a.handle(0x73a2, struct.pack('>5I', 407, 0, 0, 0, 0))
            a.handle(0x54e2, struct.pack('>II', 10402, 10402210))
            a.handle(0x3e80, struct.pack('>BBHBHHB', 1, 6, 0, 1, 22, 1, 0))
            state_a = Path(local_account(root, 'alice')['state_file'])
            before = state_a.read_bytes()
            b = LocalCosmetics(configs['bob'])
            self.assertEqual(b.wardrobe.equipped, {})
            self.assertEqual(b.selected, {})
            self.assertEqual(b.avatar, bytes(20))
            b.save()
            self.assertEqual(state_a.read_bytes(), before)
            restored = LocalCosmetics(configs['alice'])
            self.assertEqual(restored.wardrobe.equipped, {22: 1000023})
            self.assertEqual(restored.selected, {10402: 10402210})
            restored.handle(0x3e80, struct.pack('>BBHBHHB', 1, 1, 22, 6, 0, 1, 0))
            self.assertEqual(LocalCosmetics(configs['bob']).wardrobe.equipped, {})

    def test_corrupt_a_does_not_load_or_overwrite_b(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            b = local_account(root, 'bob')
            path = Path(b['state_file']); path.parent.mkdir(parents=True)
            path.write_text('{"gun_skins":{}}')
            before = path.read_bytes()
            a = Path(local_account(root, 'alice')['state_file']); a.parent.mkdir(parents=True)
            a.write_text('{invalid')
            config = root / 'a.json'
            config.write_text(json.dumps(dict(owned_gun_skin_ids=[], state_file=str(a))))
            with self.assertRaises(ValueError):
                LocalCosmetics(config)
            self.assertEqual(path.read_bytes(), before)
