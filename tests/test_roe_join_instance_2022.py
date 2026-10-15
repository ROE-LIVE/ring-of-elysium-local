"""Независимый wire fixture и отказ на нарушениях native decoder."""

from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from roe_join_instance_2022 import (
    JoinInstanceResponse, decode_join_instance_response, encode_join_instance_response,
    decode_join_instance_request, encode_join_instance_request,
    JoinInstanceNotification, decode_join_instance_notification,
    encode_join_instance_notification,
)


class JoinInstanceTests(unittest.TestCase):
    def fixture(self, route=b"0:127.0.0.1:18001", result=0):
        # Порядок и длины заданы вручную по ASM, независимо от encoder.
        return (struct.pack(">II", result, len(route) + 1) + route + b"\0"
                + bytes(range(16)) + bytes(range(16, 32))
                + bytes.fromhex("01020304 a0b0c0d0 fe"))

    def test_known_layout_and_full_coverage(self):
        raw = self.fixture()
        message = decode_join_instance_response(raw)
        self.assertEqual(message.route, b"0:127.0.0.1:18001")
        self.assertEqual(message.block_88, bytes(range(16)))
        self.assertEqual(message.block_98, bytes(range(16, 32)))
        self.assertEqual(message.connection_id_a8, 0x01020304)
        self.assertEqual(message.unknown_ac, 0xa0b0c0d0)
        self.assertEqual(message.flag_b0, 254)  # U8, не предполагаемый bool.
        self.assertEqual(encode_join_instance_response(message), raw)
        self.assertNotIn("block_88", repr(message))
        self.assertNotIn("block_98", repr(message))

    def test_all_truncated_prefixes_and_extra_tail(self):
        raw = self.fixture()
        for end in range(len(raw)):
            with self.subTest(end=end), self.assertRaises(ValueError):
                decode_join_instance_response(raw[:end])
        with self.assertRaises(ValueError):
            decode_join_instance_response(raw + b"\0")
        # Ошибка result не отменяет чтение остальных полей в native decoder.
        self.assertEqual(decode_join_instance_response(self.fixture(result=0xffffffff)).result,
                         0xffffffff)
        with self.assertRaises(ValueError):
            decode_join_instance_response(struct.pack(">I", 1))

    def test_string_constraints(self):
        for route in (b"", b"x" * 127, b"\xff"):
            raw = self.fixture(route)
            self.assertEqual(decode_join_instance_response(raw).route, route)
        for length in (0, 129, 0xffffffff):
            raw = bytearray(self.fixture())
            struct.pack_into(">I", raw, 4, length)
            with self.assertRaises(ValueError):
                decode_join_instance_response(raw)
        raw = bytearray(self.fixture())
        raw[9] = 0
        with self.assertRaises(ValueError):
            decode_join_instance_response(raw)
        raw = bytearray(self.fixture())
        raw[8 + struct.unpack_from(">I", raw, 4)[0] - 1] = 65
        with self.assertRaises(ValueError):
            decode_join_instance_response(raw)

    def test_builder_rejects_invalid_values(self):
        good = dict(result=0, route=b"", block_88=b"a" * 16, block_98=b"b" * 16,
                    connection_id_a8=1, unknown_ac=0, flag_b0=1)
        for name, value in (("route", b"x" * 128), ("route", b"a\0b"),
                            ("block_88", b"a" * 15), ("block_98", b"b" * 17),
                            ("result", -1), ("connection_id_a8", 1 << 32),
                            ("unknown_ac", True), ("flag_b0", 256)):
            with self.subTest(name=name), self.assertRaises(ValueError):
                encode_join_instance_response(JoinInstanceResponse(**(good | {name: value})))

    def test_request_be64_and_boundaries(self):
        raw = bytes.fromhex("0123456789abcdef")
        self.assertEqual(decode_join_instance_request(raw), 0x0123456789abcdef)
        self.assertEqual(encode_join_instance_request(0x0123456789abcdef), raw)
        for raw in (b"", b"x" * 7, b"x" * 9):
            with self.assertRaises(ValueError):
                decode_join_instance_request(raw)
        for value in (-1, 1 << 64, True):
            with self.assertRaises(ValueError):
                encode_join_instance_request(value)

    def test_notification_nested_u32_u64_and_boundaries(self):
        # Вложенный helper 0x140bddf50 читает U32+U64, без выравнивания wire.
        raw = bytes.fromhex(
            "01020304 1122334455667788 2132435465768798 31425364 "
            "415263748596a7b8 5162738495a6b7c8 61728394 718293a4")
        message = decode_join_instance_notification(raw)
        self.assertEqual(message.instance_id, 0x1122334455667788)
        self.assertEqual(message.unknown_14, 0x31425364)
        self.assertEqual(message.unknown_18, 0x415263748596a7b8)
        self.assertEqual(message.unknown_2c, 0x718293a4)
        self.assertEqual(encode_join_instance_notification(message), raw)
        for end in range(48):
            with self.subTest(end=end), self.assertRaises(ValueError):
                decode_join_instance_notification(raw[:end])
        with self.assertRaises(ValueError):
            decode_join_instance_notification(raw + b"\0")
        with self.assertRaises(ValueError):
            encode_join_instance_notification(
                JoinInstanceNotification(0, 1 << 64, 0, 0, 0, 0, 0, 0))
