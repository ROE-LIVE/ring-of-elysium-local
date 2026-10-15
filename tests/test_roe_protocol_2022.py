"""Регрессии TCP-границ, AES-padding и формата heartbeat клиента 2022."""
from pathlib import Path
import struct
import sys
import unittest
import importlib.util

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
import roe_protocol_2022 as protocol

KEY = bytes(range(16))


def client_request(counter):
    plain = struct.pack('>IIHIIIQII', 7, 34, 0x1f74, 0, 0, 0, 0, 0x1f74, counter)
    body = protocol.encrypt(plain, KEY)
    return protocol.MAGIC+b'\0\x04'+struct.pack('>II', 12, len(body))+body


@unittest.skipUnless(importlib.util.find_spec('cryptography'), 'Нужны tools/requirements-protocol-2022.txt')
class ProtocolTests(unittest.TestCase):
    def test_aes_roundtrip_all_padding_boundaries(self):
        for size in range(48):
            with self.subTest(size=size):
                plain = bytes(range(size))
                self.assertEqual(protocol.decrypt(protocol.encrypt(plain, KEY), KEY), plain)

    def test_wrong_key_and_truncation_rejected(self):
        cipher = protocol.encrypt(b'heartbeat', KEY)
        for body, key in [(cipher[:-1], KEY), (cipher, b'x'*16), (cipher, b'x')]:
            with self.assertRaises(ValueError):
                protocol.decrypt(body, key)

    def test_fragmented_and_coalesced_frames(self):
        first, second = client_request(1), client_request(2)
        buffer = protocol.FrameBuffer()
        result = []
        for byte in first+second:
            result.extend(buffer.feed(bytes([byte])))
        self.assertEqual(result, [first, second])
        self.assertEqual(buffer.pending, b'')
        self.assertEqual(protocol.FrameBuffer().feed(first+second), [first, second])

    def test_oversized_frame_and_bad_magic_rejected(self):
        for header in [b'xx\0\0'+struct.pack('>II', 12, 0),
                       protocol.MAGIC+b'\0\0'+struct.pack('>II', 11, 0),
                       protocol.MAGIC+b'\0\0'+struct.pack('>II', 12, 0xffffffff)]:
            with self.assertRaises(ValueError):
                protocol.FrameBuffer().feed(header)

    def test_heartbeat_reply_has_compact_header_without_sequence_prefix(self):
        frame = protocol.heartbeat_reply(123, 18530396, KEY)
        self.assertEqual(frame[:4], b'\x55\x0e\0\0')
        self.assertEqual(len(frame), 44)
        self.assertEqual(protocol.dt_plain(frame, KEY), bytes.fromhex('011ac05c1f7500001f750000007b'))
        self.assertEqual(protocol.server_stamp(frame, KEY), 18530396)
        self.assertEqual(protocol.client_heartbeat(client_request(123), KEY), 123)

    def test_mismatched_body_tag_rejected(self):
        plain = struct.pack('>IIHIIIQII', 7, 34, 0x1f74, 0, 0, 0, 0, 0x1f75, 1)
        cipher = protocol.encrypt(plain, KEY)
        frame = protocol.MAGIC+b'\0\x04'+struct.pack('>II', 12, len(cipher))+cipher
        with self.assertRaises(ValueError):
            protocol.client_heartbeat(frame, KEY)


if __name__ == '__main__':
    unittest.main()
