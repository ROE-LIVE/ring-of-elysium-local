"""Безопасная отправка диагностических команд: атомарность, привязка и повторы."""
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server/directory'))
from live_scene_probe_2022 import LiveSceneCommands
from game_endpoint_probe_2022 import Endpoint
from types import SimpleNamespace


class LiveCommandsTests(unittest.TestCase):
    def test_acknowledged_ids_survive_new_match_for_same_actor_only(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'commands.json'
            first = {'id': 'first', 'action': 'damage_npc', 'damage': 100}
            path.write_text(json.dumps([first]))
            endpoint = Endpoint(SimpleNamespace(record=lambda *args, **kw: None),
                                live_commands=path)
            old = dict(actor_uid=123)
            control = endpoint.live_control_for(old)
            self.assertEqual([r[0] for r in control.poll(123, 1, 1)], ['first'])
            control.acknowledge('first')
            endpoint.finish_gameplay(old, ('127.0.0.1', 1), 'test')
            self.assertNotIn('live_control', old)
            new = dict(actor_uid=123)
            current = endpoint.live_control_for(new)
            self.assertIsNot(current, control)
            self.assertEqual(current.poll(123, 2, 2), [])
            path.write_text(json.dumps([first, dict(first, id='second')]))
            self.assertEqual([r[0] for r in current.poll(123, 3, 3)], ['second'])
            other = endpoint.live_control_for(dict(actor_uid=321))
            self.assertEqual([r[0] for r in other.poll(321, 4, 4)], ['first', 'second'])

    def test_targeted_camera_command_does_not_affect_other_connection(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'commands.json'
            target_uid, other_uid, camera_unit = 123, 321, 0x2040000100002
            path.write_text(json.dumps([
                {'id': 'camera', 'command': '0x6fbb',
                 'recipient_actor_uid': hex(target_uid),
                 'payload_hex': struct.pack('>Q', camera_unit).hex()},
                {'id': 'clock', 'command': '0x481', 'payload_hex': '00000000'},
            ]))
            target, other = LiveSceneCommands(path), LiveSceneCommands(path)
            self.assertEqual([r[0] for r in other.poll(other_uid, 1, 1)], ['clock'])
            delivered = target.poll(target_uid, 1, 1)
            self.assertEqual(delivered[0][2], struct.pack('>Q', camera_unit))
            self.assertEqual([r[0] for r in delivered], ['camera', 'clock'])
            target.acknowledge('camera')
            self.assertEqual([r[0] for r in target.poll(target_uid, 2, 2)], ['clock'])
            self.assertNotIn('camera', other.sent)

    def test_invalid_recipient_prevents_partial_command_delivery(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'commands.json'
            for recipient in (0, -1, 2**64, True, None, 'invalid', '0x0'):
                with self.subTest(recipient=recipient):
                    path.write_text(json.dumps([
                        {'id': 'all', 'command': '0x481', 'payload_hex': '00000000'},
                        {'id': 'bad', 'command': '0x6fbb', 'payload_hex': '00',
                         'recipient_actor_uid': recipient},
                    ]))
                    control = LiveSceneCommands(path)
                    with self.assertRaises(ValueError):
                        control.poll(123, 1, 1)
                    self.assertEqual(control.commands, [])
                    self.assertEqual(control.sent, set())

    def test_client_binding_and_acknowledged_command_is_not_repeated(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'commands.json'
            row = {'id': 'hp-75', 'command': '0x1069', 'payload_hex': bytes(12).hex(),
                   'actor_uid_offsets': [0], 'clock_tick_offsets': [8]}
            path.write_text(json.dumps([row]))
            control = LiveSceneCommands(path)
            first = control.poll(123, 456, 1)
            self.assertEqual(first[0][2], struct.pack('>QI', 123, 456))
            self.assertEqual(control.poll(123, 456, 1), first)
            control.acknowledge('hp-75')
            self.assertEqual(control.poll(123, 999, 2), [])
            self.assertEqual(LiveSceneCommands(path).poll(321, 111, 1)[0][2],
                             struct.pack('>QI', 321, 111))

    def test_invalid_later_entry_prevents_partial_delivery(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'commands.json'
            path.write_text(json.dumps([
                {'id': 'ok', 'command': '0x481', 'payload_hex': '00000000'},
                {'id': 'bad', 'command': '0x1069', 'payload_hex': '00',
                 'actor_uid_offsets': [0]},
            ]))
            control = LiveSceneCommands(path)
            with self.assertRaises(ValueError):
                control.poll(1, 1, 1)
            self.assertEqual(control.sent, set())
            self.assertEqual(control.commands, [])

    def test_payload_cannot_read_outside_experiment_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'other.bin').write_bytes(b'data')
            (root / 'run').mkdir()
            path = root / 'run/commands.json'
            path.write_text(json.dumps([{'id': 'bad', 'command': '0x481',
                                         'payload_file': '../other.bin'}]))
            with self.assertRaises(ValueError):
                LiveSceneCommands(path).poll(1, 1, 1)
