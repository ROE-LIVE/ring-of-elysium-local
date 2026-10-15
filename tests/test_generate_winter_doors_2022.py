"""Первичный XML: исходные XYZ/строка, фильтр двери и запрет смешения карт."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
spec=importlib.util.spec_from_file_location('generate_doors',Path(__file__).resolve().parents[1]/'tools/generate_winter_doors_2022.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


class GenerateDoorsTests(unittest.TestCase):
    def source(self, directory, obj='data.world.EU_IceLand_4096.ClientTable.EntityStatusInPxScene'):
        path=Path(directory)/'ENTITYSTATUSINPXSCENE.XML'
        path.write_text('<NewObj ObjName="'+obj+'">\n<mTable [XlsProp]="0">\n'
            '<mTable mID="7767" mEntityFullName="door" mPosX="415727.937500" mPosY="557603.562500" mPosZ="259024.234375">'
            '<mSwitcherStatus mType="EStatus_REVERSIBLE" mSwitcherType="ESwitcher_DOOR" mStatus="0"/></mTable>\n'
            '<mTable mID="9" mEntityFullName="wall" mPosX="0" mPosY="0" mPosZ="0">'
            '<mSwitcherStatus mType="EStatus_NONE" mSwitcherType="ESwitcher_DOOR" mStatus="0"/></mTable>\n'
            '</mTable></NewObj>')
        return path

    def test_preserves_primary_position_and_line(self):
        with tempfile.TemporaryDirectory() as directory:
            data=m.generate(self.source(directory))
            self.assertEqual(len(data['doors']),1)
            self.assertEqual(data['doors'][0]['position_cm'],[415727.9375,557603.5625,259024.234375])
            self.assertEqual(data['doors'][0]['source_line'],3)
            self.assertEqual(len(data['provenance']['sha256']),64)

    def test_bounds_do_not_move_points(self):
        with tempfile.TemporaryDirectory() as directory:
            path=self.source(directory)
            self.assertEqual(len(m.generate(path,(413000,554000,419000,560000))['doors']),1)
            self.assertFalse(m.generate(path,(0,0,1,1))['doors'])

    def test_other_map_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):m.generate(self.source(directory,'desert'))
