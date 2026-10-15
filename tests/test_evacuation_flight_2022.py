"""Порядок траектории, переходов и сохранение UID диагностической эвакуации."""
import copy
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from evacuation_flight_2022 import native_evacuation_scene


class EvacuationFlightTests(unittest.TestCase):
    def scene(self):
        body=bytearray(104)
        struct.pack_into('>QIIIiii',body,0,123,6,9,100,365300,544000,260300)
        return [dict(trigger='0x1f49',after_selection=True,
            after_selection_delay_seconds=127.8,responses=[
                dict(command='0x654b',payload_hex=body.hex()),
                dict(command='0x657b',payload_hex=struct.pack('>QQ',456,123).hex())])]

    def test_flight_preserves_uid_and_target_before_hover_link(self):
        source=self.scene();before=copy.deepcopy(source)
        scene=native_evacuation_scene(source)
        self.assertEqual(source,before)
        packets=[(r['after_selection_delay_seconds'],int(p['command'],0),
                  bytes.fromhex(p['payload_hex'])) for r in scene for p in r['responses']]
        entry=[p for _,code,p in packets if code==0x654b]
        self.assertEqual(len(entry),1)
        self.assertEqual(struct.unpack_from('>Q',entry[0])[0],123)
        self.assertEqual(struct.unpack_from('>iii',entry[0],20),(253314,643795,269932))
        moves=[(at,p) for at,code,p in packets if code==0x6575]
        self.assertGreater(len(moves),300)
        self.assertTrue(all(len(p)==73 and struct.unpack_from('>Q',p)[0]==123 for _,p in moves))
        self.assertEqual(struct.unpack_from('>iii',moves[-1][1],13),(365300,544000,260300))
        phases=[(at,struct.unpack('>QI',p)) for at,code,p in packets if code==0x6588]
        self.assertEqual([p for _,p in phases],[(123,1),(123,2)])
        self.assertLess(moves[-1][0],phases[-1][0])
        self.assertEqual([p for _,code,p in packets if code==0x657b],
                         [struct.pack('>QQ',456,123)])
        self.assertTrue(all(p.get('clock_tick_offsets')==[8] for r in scene
                            for p in r['responses'] if p['command']=='0x6575'))

    def test_incompatible_or_too_early_scene_is_rejected(self):
        with self.assertRaises(ValueError):native_evacuation_scene([])
        with self.assertRaises(ValueError):native_evacuation_scene(self.scene()*2)
        for value in (True,120,-1,1801,float('nan')):
            scene=self.scene();scene[0]['after_selection_delay_seconds']=value
            with self.subTest(value=value),self.assertRaises(ValueError):
                native_evacuation_scene(scene)
        scene=self.scene();scene[0]['after_selection']=False
        with self.assertRaises(ValueError):native_evacuation_scene(scene)
