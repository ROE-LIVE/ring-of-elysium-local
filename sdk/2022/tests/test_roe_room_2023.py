"""Проверки вложенных списков, NUL-строк и границ ответа входа в комнату."""
import struct
import sys
import json
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from roe_room_2023 import decode_enter_room_response, decode_jump_routing, Reader
from analyze_room_messages_2023 import analyze


def room_fixture(points=0, extras=0, names=0, lists=(0, 0, 0, 0, 0), entries=0, subentries=0):
    # Независимая сборка по таблице decoder EXE: 1034 байта при пустых списках.
    word = lambda n: struct.pack('>I', n)
    text = word(1) + b'\0'
    profile = (bytes(20) + text + bytes(48 + 88) + word(points) + bytes(40 * points)
               + bytes(108 + 8 + 4 + 8) + word(extras) + bytes(4 * extras)
               + bytes(16 + 8 + 8 + 4 + 1) + text + bytes(88 + 4 + 4)
               + word(names) + text * names + text + bytes(25 + 420))
    inventory = bytes(44) + b''.join(word(n) + bytes(n * 4) for n in lists) + bytes(8)
    tail = word(entries) + (bytes(4) + word(subentries) + bytes(9 * subentries)) * entries
    return bytes(36) + profile + bytes(12) + inventory + bytes(20 + 1) + tail


class RoomTests(unittest.TestCase):
    def test_minimum_response_and_exact_consumption(self):
        data = room_fixture()
        self.assertEqual(len(data), 1034)
        result = decode_enter_room_response(data)
        self.assertEqual(result['length'], 1034)
        with self.assertRaises(ValueError):
            decode_enter_room_response(data + b'x')
        for cut in range(len(data)):
            with self.assertRaises(ValueError):
                decode_enter_room_response(data[:cut])

    def test_all_nested_lists_at_native_maxima(self):
        data = room_fixture(30, 2, 2, (10, 5, 10, 80, 10), 400, 6)
        result = decode_enter_room_response(data)
        self.assertEqual(len(data), 1034 + 1200 + 8 + 10 + 460 + 400 * 62)
        self.assertEqual(result['length'], len(data))
        self.assertEqual(result['fields'][-1]['name'], 'mcfb.entries[399].m008[5].m008')
        for name, maximum in [('profile.base.m094.extended.m058.count', 30),
                              ('profile.base.m648.m008.count', 2),
                              ('profile.base.m75d.m004.count', 2),
                              ('mad2.m058.count', 5), ('mad2.m09c.count', 80),
                              ('mcfb.count', 400), ('mcfb.entries[0].m004.count', 6)]:
            field = next(f for f in result['fields'] if f['name'] == name)
            for count in (-1, maximum + 1):
                bad = bytearray(data)
                struct.pack_into('>i', bad, field['offset'], count)
                with self.assertRaises(ValueError):
                    decode_enter_room_response(bad)

    def test_string_requires_one_terminal_nul(self):
        for raw in (b'', b'ab', b'a\0b\0', b'x' * 129 + b'\0'):
            with self.assertRaises(ValueError):
                Reader(struct.pack('>I', len(raw)) + raw).string('name')
        self.assertEqual(Reader(b'\0\0\0\x02a\0').string('name'), b'a')

    def test_routing_variants_and_bounds(self):
        route = (struct.pack('>I', 10) + b'127.0.0.1\0' + struct.pack('>H', 10005)
                 + struct.pack('>I', 1) + b'\0' + struct.pack('>I', 7))
        for code, extra in [(0x360, b''), (0x368, bytes(9))]:
            data = bytes(52) + extra + struct.pack('>i', 1) + route
            decoded = decode_jump_routing(data, code)
            port = next(f for f in decoded['fields'] if f['name'] == 'routes[0].m010')
            self.assertEqual(port['value'], 10005)
            for bad in (data[:-1], data + b'x', bytes(52) + extra + struct.pack('>i', -1),
                        bytes(52) + extra + struct.pack('>i', 5)):
                with self.assertRaises(ValueError):
                    decode_jump_routing(bad, code)
        with self.assertRaises(ValueError):
            decode_jump_routing(b'', 0x341)

    def test_offline_report_excludes_private_values_and_validates_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plain = root / 'plaintext'
            plain.mkdir()
            data = bytearray(room_fixture())
            struct.pack_into('>Q', data, 12, 12345678901234567)
            (plain / 'frame.bin').write_bytes(bytes(10) + data)
            message = {'code': '0xdcf', 'direction': 'server', 'file': 'capture.pcap',
                       'record': 7, 'plaintext_file': 'frame.bin',
                       'plaintext_offset': 0, 'decoded_length': len(data) + 10}
            catalog = root / 'catalog.jsonl'
            output = root / 'report.json'
            catalog.write_text(json.dumps(message) + '\n')
            self.assertEqual(analyze(catalog, plain, output), 1)
            report = json.loads(output.read_text())
            self.assertNotIn('12345678901234567', output.read_text())
            fields = report['messages'][0]['fields']
            self.assertNotIn('value', next(f for f in fields if f['name'] == 'm00c'))
            self.assertTrue(report['messages'][0]['roundtrip'])
            for change in ({'plaintext_file': '../frame.bin'},
                           {'plaintext_offset': -1}, {'direction': 'client'}):
                catalog.write_text(json.dumps(dict(message, **change)) + '\n')
                with self.assertRaises(ValueError):
                    analyze(catalog, plain, output)


if __name__ == '__main__':
    unittest.main()
