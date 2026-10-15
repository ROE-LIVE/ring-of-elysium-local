"""Внешность комнаты: переменные профили и порядок item/index брелков."""
from pathlib import Path
import json
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
for part in ('tools','server/directory'):sys.path.insert(0,str(ROOT/part))
from room_cosmetics_2022 import apply_room_cosmetics
from roe_room_2023 import decode_enter_room_response
import test_roe_room_2023 as fixtures


class RoomCosmeticsTests(unittest.TestCase):
    def catalog(self,root,state):
        saved=root/'selection.json';saved.write_text(json.dumps(state))
        path=root/'catalog.json';path.write_text(json.dumps(dict(owned_gun_skin_ids=[],
            owned_character_ids=[407],owned_accessory_ids=[200000],state_file=str(saved))))
        return path,saved

    def test_room_replaces_tail_keeps_other_data_with_variable_prefix_and_old_accessories(self):
        with tempfile.TemporaryDirectory() as directory:
            catalog,_=self.catalog(Path(directory),dict(avatar=[407,0,0,0,0],avatar_applied=True,
                accessory_selection=[[100608,0,200000,0]]))
            for original in (fixtures.room_fixture(),fixtures.room_fixture(3,2,2,(2,3,4,5,1),2,3)):
                fields={f['name']:f for f in decode_enter_room_response(original)['fields']}
                result,event=apply_room_cosmetics(original,catalog)
                parsed={f['name']:f['value'] for f in decode_enter_room_response(result)['fields']}
                offset=fields['mce6.values[0]']['offset']
                self.assertEqual(result[:offset],original[:offset])
                self.assertEqual([parsed[f'mce6.values[{i}]'] for i in range(5)],[407,0,0,0,0])
                self.assertEqual((parsed['mcfa'],parsed['mcfb.count']),(1,1))
                self.assertEqual([parsed[f'mcfb.entries[0].m008[0].m000[{i}]'] for i in range(2)],[200000,0])
                self.assertEqual(event['accessory_groups'],1)

    def test_next_room_reads_latest_apply_and_removal_state(self):
        with tempfile.TemporaryDirectory() as directory:
            catalog,saved=self.catalog(Path(directory),dict(avatar=[407,0,0,0,0],avatar_applied=True,
                accessory_selection=[[100608,0,200000,0]]))
            _,first=apply_room_cosmetics(fixtures.room_fixture(),catalog)
            saved.write_text(json.dumps(dict(avatar=[0]*5,avatar_applied=False,accessory_selection=[])))
            result,second=apply_room_cosmetics(fixtures.room_fixture(),catalog)
            self.assertTrue(first['avatar_applied']);self.assertFalse(second['avatar_applied'])
            self.assertEqual((len(result),second['accessory_groups']),(1034,0))

    def test_unowned_character_or_accessory_is_rejected_before_packet(self):
        with tempfile.TemporaryDirectory() as directory:
            for state in (dict(avatar=[999,0,0,0,0]),dict(accessory_selection=[[100608,0,999,0]])):
                catalog,_=self.catalog(Path(directory),state)
                with self.assertRaises(ValueError):apply_room_cosmetics(fixtures.room_fixture(),catalog)

    def test_truncated_or_trailing_room_is_not_guessed(self):
        with tempfile.TemporaryDirectory() as directory:
            catalog,_=self.catalog(Path(directory),{})
            for payload in (fixtures.room_fixture()[:-1],fixtures.room_fixture()+b'\0'):
                with self.assertRaises(ValueError):apply_room_cosmetics(payload,catalog)

if __name__=='__main__':unittest.main()
