"""Проверка по трём шагам genuine native Citori cold140,10.10.2026."""
import math
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server/directory'))
from ballistics_2022 import BallisticState, f32, step, trajectory


class BallisticsTests(unittest.TestCase):
    def test_native_citori_golden(self):
        # integrator-citori-retry.log: hardware140FC2430/140FC27F3,
        # вход и выход выбранного одного bullet; никаких memory writes.
        state=BallisticState((365188.781,543987.312,259253.953),
                            (35960.8086,-1419.3512,897.638062),-981,.0022,30000)
        golden=(
            ((365896.594,543959.375,259271.422),(35391.1914,-1396.86877,863.7995)),
            ((366593.375,543931.875,259288.234),(34839.4805,-1375.09314,830.713806)),
            ((367279.469,543904.812,259304.391),(34304.8438,-1353.99133,798.345947)),
        )
        for xyz,velocity in golden:
            state=step(state)
            self.assertEqual(state.position,tuple(f32(v) for v in xyz))
            self.assertEqual(state.velocity,tuple(f32(v) for v in velocity))

    def test_native_m4_golden(self):
        # integrator-m4.log cold141: штатный M4, pickup/reload, три шага.
        state=BallisticState((365185.125,543987.875,259245.578),
                            (87952.8203,-1088.15393,-2668.00122),-981,.00125,100000)
        golden=(
            ((366905.469,543966.562,259193.203),(86017.8594,-1064.21448,-2628.92529)),
            ((368588.812,543945.75,259141.562),(84167.0859,-1041.31665,-2591.98096)),
            ((370236.719,543925.375,259090.625),(82395.0859,-1019.39343,-2557.03125)),
        )
        for xyz,velocity in golden:
            state=step(state)
            self.assertEqual(state.position,tuple(f32(v) for v in xyz))
            self.assertEqual(state.velocity,tuple(f32(v) for v in velocity))

    def test_grace_water_remote_and_range(self):
        base=BallisticState((0,0,0),(1000,0,0),-981,.0022,15,grace_seconds=.1)
        end=step(base)
        self.assertEqual(end.position,(20.,0.,0.))
        self.assertEqual(end.velocity,(1000.,0.,0.))
        self.assertFalse(end.alive)
        self.assertIs(step(end),end)
        remote=step(BallisticState((0,0,0),(1000,0,0),-981,.0022,100,local=False))
        self.assertEqual(remote.velocity[0],1000.)
        self.assertLess(remote.position[2],0)
        water=step(BallisticState((0,0,0),(1000,0,0),-981,.0022,100,water=True))
        self.assertEqual(water.position[2],0.)
        self.assertAlmostEqual(water.velocity[0],894.,places=3)
        self.assertEqual(len(list(trajectory(base))),2)

    def test_invalid_parameters_and_bounded_iteration(self):
        for kwargs in ({'air_drag':-1},{'gravity':math.nan},{'range_cm':0},
                       {'local':1},{'position':(0,0,math.inf)}):
            values=dict(position=(0,0,0),velocity=(1000,0,0),gravity=-981,
                        air_drag=.0022,range_cm=30000);values.update(kwargs)
            with self.assertRaises(ValueError): BallisticState(**values)
        state=BallisticState((0,0,0),(1000,0,0),-981,.0022,30000)
        for value in (0,-.1,.021,math.nan):
            with self.assertRaises(ValueError): step(state,value)
        with self.assertRaises(ValueError): list(trajectory(state,10001))
        self.assertEqual(len(list(trajectory(state,2))),3)

if __name__=='__main__': unittest.main()
