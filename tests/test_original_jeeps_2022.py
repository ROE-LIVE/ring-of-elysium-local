"""Контроль новых UID и исходных координат без запуска клиента."""
import copy
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from original_jeeps_2022 import add_original_jeeps, POINTS, UIDS


class OriginalJeepsTests(unittest.TestCase):
    def fixture(self):
        body = bytearray(164)
        struct.pack_into('>QI', body, 0, 123, 102)
        return [dict(trigger='0x1f49', after_selection=True,
                     responses=[dict(command='0x654b', payload_hex=body.hex())])]

    def test_distinct_uids_original_points_and_source_not_modified(self):
        scene = self.fixture()
        previous = copy.deepcopy(scene)
        result = add_original_jeeps(scene)
        self.assertEqual(scene, previous)
        for uid, (_, _, xyz), response in zip(UIDS, POINTS, result[-1]['responses']):
            body = bytes.fromhex(response['payload_hex'])
            self.assertEqual(len(body), 164)
            self.assertEqual(struct.unpack_from('>QI', body), (uid, 102))
            self.assertEqual(struct.unpack_from('>3i', body, 20), xyz)
            self.assertAlmostEqual(sum(x*x for x in struct.unpack_from('>4f', body, 33)), 1)
        self.assertTrue(result[-1]['after_selection'])
        with self.assertRaises(ValueError):
            add_original_jeeps(result)

    def test_missing_supported_prototype_is_rejected(self):
        with self.assertRaises(ValueError):
            add_original_jeeps([])
