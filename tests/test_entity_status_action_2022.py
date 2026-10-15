"""Проверка минимального wire-контракта и сохранности очереди двери2022."""
import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('door_action', Path(__file__).resolve().parents[1] / 'tools/entity_status_action_2022.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class EntityStatusActionTests(unittest.TestCase):
    def test_native_minimal_body(self):
        row = m.make_command(7767, 'open', 'door-open')
        body = bytes.fromhex(row['payload_hex'])
        self.assertEqual(len(body), 16)
        self.assertEqual(struct.unpack('>IBBBBQ', body), (7767, 1, 0, 0, 0, 0))
        self.assertEqual(bytes.fromhex(m.make_command(7767, 'closed', 'close')['payload_hex'])[4], 0)

    def test_invalid_entity_and_state(self):
        for entity in (True, 0, -1, 2**32, '7767'):
            with self.assertRaises(ValueError):
                m.make_command(entity, 'open', 'a')
        with self.assertRaises(ValueError):
            m.make_command(7767, 'toggle', 'a')

    def test_preserve_history_and_reject_duplicate(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'live-commands.json'
            old = m.make_command(7767, 'open', 'first')
            path.write_text(json.dumps([old]))
            m.enqueue(path, m.make_command(7767, 'closed', 'second'))
            self.assertEqual(json.loads(path.read_text())[0], old)
            before = path.read_bytes()
            with self.assertRaises(ValueError):
                m.enqueue(path, old)
            self.assertEqual(path.read_bytes(), before)

    def test_invalid_id_does_not_replace_queue(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'live-commands.json'
            path.write_text('[]')
            with self.assertRaises(ValueError):
                m.enqueue(path, m.make_command(7767, 'open', 'bad id'))
            self.assertEqual(path.read_text(), '[]')
            self.assertEqual(list(Path(tmp).glob('.commands-*')), [])

    def test_full_queue_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'live-commands.json'
            path.write_text(json.dumps([m.make_command(7767, 'open', 'd' + str(i)) for i in range(128)]))
            before = path.read_bytes()
            with self.assertRaises(ValueError):
                m.enqueue(path, m.make_command(7767, 'closed', 'extra'))
            self.assertEqual(path.read_bytes(), before)
