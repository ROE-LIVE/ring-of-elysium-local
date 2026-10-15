"""Скин экземпляра: выбор до матча, обвесы, drop/repick и пакет смерти."""
from pathlib import Path
from dataclasses import replace
import json
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'server/directory'))
from cosmetic_selection_2022 import load_weapon_skins
from inventory_codec_2022 import decode_snapshot, decode_delta, decode_item
from attachment_probe_2022 import AttachmentInstance
from death_parcel_2022 import DeathParcelState
import test_weapon_probe_2022 as fixtures
from weapon_probe_2022 import WeaponState


class WeaponCosmeticsTests(unittest.TestCase):
    def state(self):
        return fixtures.WeaponStateTests().recycling_state(10402, 1)

    def test_new_match_merges_latest_clothes_without_replacing_gun_or_kit(self):
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
        from local_cosmetics_2022 import LocalCosmetics
        with tempfile.TemporaryDirectory() as directory:
            catalog,saved=self.catalog(Path(directory),{})
            value=json.loads(catalog.read_text())
            value.update(owned_clothing_ids=[1000023],clothing_inventory_container=6,
                         clothing_equipment_slots={'1000023':22})
            catalog.write_text(json.dumps(value))
            fixture=replace(self.state().fixture,cosmetics_config_file=catalog)
            first=WeaponState(fixture,42)
            account=LocalCosmetics(catalog)
            account.handle(0x3e80,struct.pack('>BBHBHHB',1,6,0,1,22,1,0),42)
            second=WeaponState(fixture,42)
            self.assertEqual(first.cosmetic_clothes,{})
            equipment={(x.container,x.slot):x.item.definition for x in decode_snapshot(second.inventory()).entries}
            self.assertEqual((equipment[(1,1)],equipment[(1,22)]),(10402,1000023))
            account.handle(0x3e80,struct.pack('>BBHBHHB',1,1,22,6,0,1,0),42)
            self.assertEqual(WeaponState(fixture,42).cosmetic_clothes,{})

    def test_wire_skin_survives_parts_snapshot_delta_and_optional_name(self):
        state = self.state(); state.guns[1].skin_id = 10402210
        state.guns[1].parts = {3: AttachmentInstance(40403, 55)}
        record = state.inventory_records()[0]
        parsed = decode_snapshot(state.inventory()).entries[0].item
        self.assertEqual((parsed.skin_id, parsed.part_count), (10402210, 1))
        self.assertEqual(decode_delta(state.slot_sync(1,1)[1]).entries[0].item.skin_id,10402210)
        raw = bytearray(record[2:]); raw[22] = 1
        named = raw[:23]+struct.pack('>I',4)+b'gun\0'+raw[23:]
        self.assertEqual(decode_item(named).skin_id,10402210)

    def test_move_drop_repick_retains_same_skin_and_instance(self):
        state = self.state(); state.fixture = replace(state.fixture, weapon_slots=2)
        gun=state.guns[1]; gun.skin_id=10402210
        state.handle(0x3e80,struct.pack('>BBHBHHB',1,1,1,1,2,1,1))
        self.assertIs(state.guns[2],gun)
        _,event=state.handle(0x3e80,struct.pack('>BBHHQB',2,1,2,1,0,1))
        dropped=state.loot_registry[event['index']]
        self.assertEqual((dropped.skin_id,dropped.instance_uid),(10402210,gun.uid))
        state.skin_selection[10402]=0
        state.handle(0x3b63,fixtures.WeaponStateTests().pickup_request(dropped.index))
        self.assertEqual((state.guns[1].skin_id,state.guns[1].uid),(10402210,gun.uid))

    def test_original_ground_pickup_uses_account_selection_and_zero_is_default(self):
        for skin in (0,10402210):
            state=self.state(); state.guns.clear(); state.skin_selection[10402]=skin
            state.handle(0x3b63,fixtures.WeaponStateTests().pickup_request(15510))
            self.assertEqual(state.guns[1].skin_id,skin)

    def test_death_parcel_retains_current_weapon_skin(self):
        state=self.state(); state.guns[1].skin_id=10402210
        death=DeathParcelState(); death.transfer(state,state.position)
        loot=next(x for x in death.containers[0].fixture.items if x.definition==10402)
        self.assertEqual(loot.skin_id,10402210)
        self.assertFalse(state.guns)

    def catalog(self, root, selected):
        state=root/'selection.json';state.write_text(json.dumps(dict(gun_skins=selected)))
        catalog=root/'catalog.json';catalog.write_text(json.dumps(dict(
            owned_gun_skin_ids=[10402210],weapon_skin_to_weapon={'10402210':10402},state_file=str(state))))
        return catalog,state

    def test_new_match_reads_latest_saved_choice_not_preflight_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            catalog,saved=self.catalog(Path(directory),{'10402':10402210})
            self.assertEqual(load_weapon_skins(catalog),{10402:10402210})
            fixture=replace(self.state().fixture,cosmetics_config_file=catalog)
            first=WeaponState(fixture,42);self.assertEqual(first.guns[1].skin_id,10402210)
            saved.write_text(json.dumps(dict(gun_skins={'10402':0})))
            second=WeaponState(fixture,42)
            self.assertEqual((first.guns[1].skin_id,second.guns[1].skin_id),(10402210,0))

    def test_wrong_weapon_unowned_id_or_malformed_selection_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            for selected in ({'10201':10402210},{'10402':999},{'10402':True},
                             {'010402':10402210},{'0':0},{'10402':'10402210'},[]):
                catalog,_=self.catalog(Path(directory),selected)
                with self.subTest(selected=selected),self.assertRaises(ValueError):load_weapon_skins(catalog)
            catalog,_=self.catalog(Path(directory),{})
            value=json.loads(catalog.read_text());value.pop('weapon_skin_to_weapon');catalog.write_text(json.dumps(value))
            with self.assertRaises(ValueError):load_weapon_skins(catalog)

if __name__=='__main__': unittest.main()
