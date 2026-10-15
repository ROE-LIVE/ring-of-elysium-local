"""Native golden границы50см и отказ от повреждённого fast index2022."""
import struct,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server/directory'))
from region_index_2022 import FastRegionIndex

class RegionIndexTests(unittest.TestCase):
    def grid(self):
        # Выбранная строка6784 оригинального winter index; native1411BFAA0.
        pairs=((0,478),(16,1535),(41,2690),(24,3987),(14,4154),
               (59,5083),(60,5975),(11,6036),(51,7035),(61,7985),(0,8190))
        row=b''.join(struct.pack('<HH',*pair) for pair in pairs)
        rows=[struct.pack('<HH',0,8190)]*8192;rows[6784]=row
        return FastRegionIndex(tuple(rows))

    def test_native_measured_points_and_inclusive_boundary(self):
        grid=self.grid()
        # Golden: native emulation, exact inclusive end then next50cm cell.
        for x,expected in ((365100,24),(404149,24),(404150,24),(404199,24),
                           (404200,14),(339300,41),(339350,24),(614350,0)):
            self.assertEqual(grid.regions((x,544000,259107)),
                             frozenset((expected,)) if expected else frozenset())
        # Маска UI могла давать два региона; fast index возвращает один.
        self.assertEqual(len(grid.regions((404199,544000,0))),1)

    def test_world_exterior_and_native_row_zero_are_empty(self):
        grid=self.grid()
        for xyz in ((204800,204800,0),(204750,544000,0),(365100,614400,0),
                    (365100,0,0),(1000000,544000,0)):
            self.assertEqual(grid.regions(xyz),frozenset())
        for xyz in ((True,1,2),(1,float('nan'),2),(1,2),(1,2,2147483648)):
            with self.assertRaises(ValueError):grid.regions(xyz)

    def test_zero_region_retains_identity_separate_from_invalid_coordinates(self):
        grid=self.grid()
        self.assertEqual(grid.region_id((614300,544000,0)),0)
        self.assertIsNone(grid.region_id((365100,614400,0)))
        self.assertEqual(grid.region_id((365100,544000,0)),24)
        self.assertEqual(grid.regions((614300,544000,0)),frozenset())

    def test_frozen_zero_has_damage_and_leaving_stops_it_without_safe_escape(self):
        from dataclasses import replace
        from world_probe_2022 import WorldFixture,WorldState,encode_shrink
        base=WorldFixture(1000,0,(0,0,1,1),50,2,
            ((0,20,encode_shrink(30,20,[24],[24])),),self.grid(),150,
            (frozenset({24}),),zone_interval=1,zero_region_is_frozen=True)
        world=WorldState(base,42,0)
        world.update_position((614300,544000,0),0);world.poll(0)
        world.poll(1);self.assertEqual(world.hp,850)
        world.update_position((365100,544000,0),1);world.poll(1);world.poll(10)
        self.assertEqual(world.hp,850);self.assertFalse(world.zone_inside)
        # Внешняя координата не становится убежищем из-за lookup None.
        world.update_position((365100,614400,0),10);world.poll(10);world.poll(11)
        self.assertEqual(world.hp,700);self.assertTrue(world.zone_inside)
        legacy=WorldState(replace(base,zero_region_is_frozen=False),42,0)
        legacy.update_position((614300,544000,0),0);legacy.poll(0);legacy.poll(10)
        self.assertEqual(legacy.hp,1000)

    def test_corrupt_rows_rejected_before_use(self):
        valid=struct.pack('<HHH',1,24,8190)
        self.assertEqual(FastRegionIndex.from_bytes(valid,1).rows,(valid[2:],))
        for bad in (valid[:-1],valid+b'\0',struct.pack('<H',0),
                    struct.pack('<HHH',1,65,8190),struct.pack('<HHH',1,24,8192),
                    struct.pack('<H4H',2,24,100,14,100)):
            with self.assertRaises(ValueError):FastRegionIndex.from_bytes(bad,1)
        for count in (True,0,8193):
            with self.assertRaises(ValueError):FastRegionIndex.from_bytes(valid,count)

    def test_closed_zone_hurts_exact_region_at_boundary(self):
        from world_probe_2022 import WorldFixture,WorldState,encode_shrink
        grid=self.grid();fixture=WorldFixture(1000,0,(0,0,1,1),50,1,
            ((0,20,encode_shrink(30,20,[14],[14])),),grid,50,(frozenset({14}),))
        world=WorldState(fixture,42,0);world.update_position((404199,544000,0),0)
        world.poll(0);world.poll(1)
        self.assertEqual(world.hp,950)
        world.update_position((404200,544000,0),1);world.poll(1);world.poll(5)
        self.assertEqual(world.hp,950)
        self.assertFalse(world.zone_inside)

    def test_zero_frozen_loader_rejects_non_boolean_or_missing_native_index(self):
        import json,tempfile
        from unittest.mock import patch
        from world_probe_2022 import WorldFixture
        config={'hp':1000,'hp_floor':100,'hazard':{'bounds_xy':[0,0,1,1],
            'damage':50,'interval_seconds':1},'region_grid':{'file':'public-index.bin',
            'lookup':'native_fast','damage':150,'zero_region_is_frozen':True},'stages':[]}
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'world.json'
            with patch('world_probe_2022.FastRegionIndex.load',return_value=self.grid()):
                p.write_text(json.dumps(config));self.assertTrue(WorldFixture.load(p).zero_region_is_frozen)
                for bad in (1,'true',None):
                    config['region_grid']['zero_region_is_frozen']=bad
                    p.write_text(json.dumps(config))
                    with self.assertRaises(ValueError):WorldFixture.load(p)
                config['region_grid']['zero_region_is_frozen']=False
                p.write_text(json.dumps(config));self.assertFalse(WorldFixture.load(p).zero_region_is_frozen)

    def test_native_profile_rejects_reopening_and_future_outside_safe(self):
        import json,tempfile
        from unittest.mock import patch
        from world_probe_2022 import WorldFixture
        config={'hp':1000,'hp_floor':100,'hazard':{'bounds_xy':[0,0,1,1],
            'damage':50,'interval_seconds':1},'region_grid':{'file':'public-index.bin',
            'lookup':'native_fast','damage':50},'stages':[
            {'at_seconds':0,'stage':10,'duration':30,'future_regions':[24],
             'previous_regions':[24,14]},
            {'at_seconds':30,'stage':20,'duration':30,'future_regions':[24],
             'previous_regions':[24]}]}
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'world.json'
            with patch('world_probe_2022.FastRegionIndex.load',return_value=self.grid()):
                p.write_text(json.dumps(config));fixture=WorldFixture.load(p)
                self.assertIsInstance(fixture.region_grid,FastRegionIndex)
                config['stages'][1]['previous_regions']=[24,41]
                p.write_text(json.dumps(config))
                with self.assertRaises(ValueError):WorldFixture.load(p)
                config['stages'][1]['previous_regions']=[24]
                config['stages'][1]['future_regions']=[14]
                p.write_text(json.dumps(config))
                with self.assertRaises(ValueError):WorldFixture.load(p)
