"""Отбор временных/одинаковых записей и обнаружение конфликтов публичных таблиц."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from audit_cosmetics_catalog_2022 import build_catalog, compare_catalog, table_rows
from local_cosmetics_2022 import accessory_container, character_container, clothing_inventory


class CatalogAuditTests(unittest.TestCase):
    def tables(self, path):
        texts = {
            '000002cf.xml': '<mWeaponSkins mSkinId="7" mWeaponId="10201"/><mWeaponSkins mSkinId="7" mWeaponId="10201"/>',
            '00000989.xml': '<m_Items ID="407" group_id="7"/>',
            '000005fb.xml': '<m_Items ID="200000"/>',
            '00000a89.xml': '<mItems dwStringID="11" szPosition="HAT" szAvatar3D_b="male" szAvatar3D_d="female" nExpireDuration="0"/>'
                           '<mItems dwStringID="10" szPosition="HAT" szAvatar3D_b="male" szAvatar3D_d="female"/>'
                           '<mItems dwStringID="9" szPosition="HAT" szAvatar3D_b="male" szAvatar3D_d="female" nExpireDuration="86400"/>'
                           '<mItems dwStringID="8" szPosition="BACKPACK"/>',
        }
        for name, text in texts.items():
            (path / name).write_text('<root [XlsProp]="1">' + text + '<!--<m_Items ID="999"/>--></root>')

    def test_identical_duplicate_and_permanent_visual_aliases(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp); self.tables(path)
            config, evidence = build_catalog(path)
            self.assertEqual(config['owned_gun_skin_ids'], [7])
            self.assertEqual(config['owned_clothing_ids'], [10])
            self.assertEqual(evidence['owned_gun_skin_ids']['identical_duplicate_ids'], [7])
            self.assertEqual(evidence['owned_clothing_ids']['temporary_ids'], [9])
            self.assertEqual(evidence['owned_clothing_ids']['permanent_aliases'], {'10': [10, 11]})
            self.assertTrue(compare_catalog(config, copy.deepcopy(config))['matches'])
            changed = copy.deepcopy(config); changed['owned_clothing_ids'] = [9, 9, 10]
            result = compare_catalog(config, changed)
            self.assertFalse(result['matches'])
            self.assertEqual(result['owned_clothing_ids']['extra'], [9])
            self.assertEqual(result['owned_clothing_ids']['duplicate_ids'], [9])

    def test_conflicting_id_comment_and_entity_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'table.xml'
            path.write_text('<root><row ID="1" group="2"/><row ID="1" group="3"/></root>')
            with self.assertRaisesRegex(ValueError, 'Конфликт'):
                table_rows(path, 'row', 'ID')
            path.write_text('<root><!--<row ID="2"/>--><row ID="1"/></root>')
            self.assertEqual(list(table_rows(path, 'row', 'ID')[0]), [1])
            path.write_text('<!DOCTYPE root><root><row ID="1"/></root>')
            with self.assertRaises(ValueError): table_rows(path, 'row', 'ID')

    def test_missing_models_negative_expiry_and_stale_groups(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp); self.tables(path)
            config, _ = build_catalog(path)
            changed = copy.deepcopy(config); changed['character_groups'] = {'407': 8}
            self.assertFalse(compare_catalog(config, changed)['matches'])
            for attrs in ('nExpireDuration="-1"', 'nExpireDuration="0"'):
                (path / '00000a89.xml').write_text('<root><mItems dwStringID="1" szPosition="HAT" ' + attrs + '/></root>')
                with self.assertRaises(ValueError): build_catalog(path)

    def test_iterables_and_bad_id_types_do_not_silently_change_catalog(self):
        for function in (accessory_container, character_container):
            self.assertEqual(function(iter([1, 2])), function([1, 2]))
            for value in ([True], [[1]], [1, 1], [0], [-1]):
                with self.assertRaises(ValueError): function(value)
        self.assertEqual(clothing_inventory(iter([1, 2]), 42), clothing_inventory([1, 2], 42))


if __name__ == '__main__': unittest.main()
