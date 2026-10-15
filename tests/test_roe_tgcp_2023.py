"""Регрессии границ, хеша, повторов и сжатия исторического игрового UDP."""
import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from roe_tgcp_2023 import (contiguous_streams, decompress_lz4_block,
                           direct_session_key, packet_hash, parse_application, parse_applications,
                           parse_datagram, parse_frame)


class TgcpTests(unittest.TestCase):
    def frame(self, command=0x4013, extra=b'\x01\x00\x00\x00', body=b'abc'):
        return struct.pack('>HHHHBIII', 0x3366, 10, 10, command, 1, 123,
                           21 + len(extra), len(body)) + extra + body

    def test_datagram_mixed_endianness_and_hash(self):
        header = struct.pack('>HHIIBBH', 50001, 10003, 0x12345678,
                             0x87654321, 0x50, 0x18, 65535)
        packet = header + struct.pack('<HH', 0x1234, 0x5678) + b'abc'
        packet += struct.pack('<I', packet_hash(packet))
        parsed = parse_datagram(packet)
        self.assertEqual((parsed.source_port, parsed.destination_port), (50001, 10003))
        self.assertEqual((parsed.clock, parsed.echoed_clock), (0x5678, 0x1234))
        self.assertEqual(parsed.data, b'abc')
        damaged = bytearray(packet)
        damaged[20] ^= 1
        with self.assertRaises(ValueError):
            parse_datagram(damaged)

    def test_native_extended_ack_headers_and_declared_payload_offset(self):
        # Два собственных ACK2022 из netem; payload/AUTH отсутствуют.
        samples = [('a4be465137b7dd8f100050e16010ffff41c0a6e41a51001048012e14', '1a510010', 934796687, 268456161), ('a4be465137b7e2e6100054f47010ffffeacd57f2765500103d550010c237980e', '765500103d550010', 934798054, 268457204)]
        for raw,extension,sequence,ack in samples:
            parsed = parse_datagram(bytes.fromhex(raw))
            self.assertEqual(parsed.extra_header,bytes.fromhex(extension))
            self.assertEqual((parsed.sequence,parsed.acknowledgement),(sequence,ack))
            self.assertEqual(parsed.data,b'')
        # Расширение не должно попасть в TGCP body; длина проверяется до slicing.
        header=struct.pack('>HHIIBBH',50001,10003,100,200,0x70,0x18,65535)
        body=header+struct.pack('<HH',1,2)+b'opaque!!'+b'body'
        parsed=parse_datagram(body+struct.pack('<I',packet_hash(body)))
        self.assertEqual(parsed.extra_header,b'opaque!!')
        self.assertEqual(parsed.data,b'body')
        for declared in (0x40,0xf0):
            bad=bytearray(header+struct.pack('<HH',1,2));bad[12]=declared
            with self.assertRaises(ValueError):
                parse_datagram(bytes(bad)+struct.pack('<I',packet_hash(bad)))

    def test_frame_boundaries_and_coalesced_frames(self):
        first, second = self.frame(), self.frame(body=b'defgh')
        self.assertEqual(parse_frame(first + second).body, b'abc')
        self.assertEqual(parse_frame(first + second, len(first)).body, b'defgh')
        for bad in (first[:-1], first[:20], self.frame(extra=b'')[:13] +
                    struct.pack('>II', 20, 3) + b'abc'):
            with self.assertRaises(ValueError):
                parse_frame(bad)

    def test_only_observed_key_exchange_variant(self):
        key = bytes(range(16))
        frame = parse_frame(self.frame(0x1002, b'\x02\x10' + key + bytes(9)))
        self.assertEqual(direct_session_key(frame), key)
        with self.assertRaises(ValueError):
            direct_session_key(parse_frame(self.frame(0x1002, b'\x03\x10' + key + bytes(9))))

    def test_reordering_duplicates_gaps_and_sequence_wrap(self):
        parts = [(0xfffffffc, b'abcd'), (2, b'gh'), (0, b'ef'),
                 (0xfffffffe, b'cdef'), (0xfffffffc, b'abcd'), (10, b'xy')]
        self.assertEqual(contiguous_streams(parts), [(0xfffffffc, b'abcdefgh'), (10, b'xy')])
        with self.assertRaises(ValueError):
            contiguous_streams([(100, b'abc'), (101, b'X')])

    def test_lz4_literal_extensions_overlapping_match_and_bounds(self):
        self.assertEqual(decompress_lz4_block(b'\x30abc'), b'abc')
        self.assertEqual(decompress_lz4_block(b'\x12a\x01\x00\x10z'), b'aaaaaaaz')
        self.assertEqual(decompress_lz4_block(b'\xf0\x03' + b'a' * 18), b'a' * 18)
        for bad in (b'\xf0', b'\x20a', b'\x10a\x00\x00', b'\x10a\x02\x00'):
            with self.assertRaises(ValueError):
                decompress_lz4_block(bad)
        with self.assertRaises(ValueError):
            decompress_lz4_block(b'\x12a\x01\x00\x10z', maximum=6)

    def test_application_compression_direction_and_tag(self):
        server = struct.pack('>IHI', 100, 0x25, 0x25) + b'xyz'
        compressed = bytes([len(server) << 4]) + server
        message = parse_application(parse_frame(self.frame(extra=b'\x01\0\0\0')),
                                    compressed, 'server')
        self.assertEqual((message.command, message.stamp, message.payload), (0x25, 100, b'xyz'))
        header = struct.pack('>IHI', 30, 0x2a, 1) + struct.pack('>IIQ', 100, 0, 123)
        client = struct.pack('>I', 7) + b'\xf0\x0f' + header + struct.pack('>I', 0x2a)
        message = parse_application(parse_frame(self.frame(extra=b'\x01\0\0\0')),
                                    client, 'client')
        self.assertEqual((message.command, message.sequence, message.payload), (0x2a, 7, b''))
        with self.assertRaises(ValueError):
            parse_application(parse_frame(self.frame(extra=b'\0\0\0\0')),
                              server[:6] + struct.pack('>I', 0x26) + server[10:], 'server')

    def test_merged_applications_have_independent_headers(self):
        one = struct.pack('>IHI', 100, 0x25, 0x25) + b'xyz'
        two = struct.pack('>IHI', 101, 0x30, 0x30) + b'a'
        frame = parse_frame(self.frame(extra=b'\0\0\0\x01' + struct.pack('>H', len(one))))
        messages = parse_applications(frame, one + two, 'server')
        self.assertEqual([message.payload for message in messages], [b'xyz', b'a'])
        with self.assertRaises(ValueError):
            parse_application(frame, one + two, 'server')
        with self.assertRaises(ValueError):
            parse_applications(frame, one + two[:-3], 'server')


if __name__ == '__main__':
    unittest.main()
