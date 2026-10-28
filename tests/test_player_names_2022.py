"""Nomes da sala para o servidor da partida: o arquivo da sessão tem o host e até 60 convidados."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server/directory'))
from game_endpoint_probe_2022 import Endpoint


class PlayerNamesTests(unittest.TestCase):
    def endpoint(self, path):
        e = Endpoint.__new__(Endpoint)
        e.player_names_path, e.player_names = path, {}
        return e

    def test_full_room_file_is_read(self):
        # Antes o limite era 8 nomes: com a sala de 60 o arquivo inteiro era ignorado e o
        # aviso de abate mostrava «LOCAL» para todos.
        names = {'0x515bb1e1dd242c': 'Alex', '0x515bb18e59c77c': 'Charlie'}
        names.update({hex(0x515bb100000000 + i): 'Jogador2' for i in range(59)})
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'player-names.json'
            path.write_text(json.dumps(names), encoding='utf-8')
            loaded = self.endpoint(path).load_player_names()
        self.assertEqual(loaded['0x515bb1e1dd242c'], 'Alex')
        self.assertEqual(loaded['0x515bb18e59c77c'], 'Charlie')

    def test_invalid_names_keep_previous(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'player-names.json'
            path.write_text(json.dumps({'0x1': ''}), encoding='utf-8')
            e = self.endpoint(path)
            e.player_names = {'0x2': 'Antigo'}
            self.assertEqual(e.load_player_names(), {'0x2': 'Antigo'})


if __name__ == '__main__':
    unittest.main()
