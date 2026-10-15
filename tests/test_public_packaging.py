"""Регрессии удаления секретного CK-литерала и внешних зависимостей лобби."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PackagingTests(unittest.TestCase):
    def test_lobby_ck_is_external_and_size_checked(self):
        text = (ROOT/'search/Ring-of-Elysium-Lobby-Emulator/LobbyEmulator/Logic/LobbyPreData.cs').read_text()
        self.assertIsNone(re.search(r'a\.Data\s*=\s*"', text))
        self.assertIn('System.IO.File.ReadAllBytes(ckPath)', text)
        self.assertIn('a.Data.Length != 32', text)

    def test_only_fixed_local_pair_is_explicitly_allowed(self):
        text = (ROOT/'.gitignore').read_text()
        self.assertIn('!private/candidate-001.key', text)
        self.assertIn('!private/lobby-ck.bin', text)
        self.assertEqual((ROOT/'private/candidate-001.key').stat().st_size,16)
        self.assertEqual((ROOT/'private/lobby-ck.bin').stat().st_size,32)
        self.assertIn('private/*', text)
