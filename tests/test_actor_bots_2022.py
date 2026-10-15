"""Конечный боезапас и ручные преграды диагностического AI2022."""
import struct
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"server/directory"))
from actor_probe_2022 import ActorFixture, ActorState

class BotAmmunitionTests(unittest.TestCase):
    def make_bot(self, magazine=2, reserve=1, boxes=()):
        from dataclasses import replace
        fixture = replace(ActorFixture(0x2040000123460,b'\x01'+bytes(22),struct.pack('>II',3,1)+bytes(1508),bytes(40),(366000,544000,259060),((366000,544000,259060),),0,1000,50),
                          equipment=bytes(82), attack=(1500,50,3,2),
                          attack_ammunition=(magazine,reserve), collision_boxes=boxes)
        bot = ActorState(fixture)
        bot.begin(100)
        bot.poll(0,0,self.point)
        return bot

    point = (365100,544000,259100)

    def test_finite_ammunition_reload_deadline_and_exhaustion_conserve_total(self):
        bot = self.make_bot()
        self.assertEqual(bot.poll(2,50,self.point)[1][0]['action'], 'bot_attack')
        self.assertEqual(bot.poll(5,125,self.point)[1][0]['action'], 'bot_attack')
        self.assertEqual((bot.magazine,bot.reserve,bot.spent_ammunition), (0,1,2))
        self.assertEqual(bot.poll(8,200,self.point)[1][0]['action'], 'bot_reload_begin')
        self.assertEqual(bot.poll(10.129,253,self.point)[1], [])
        events = bot.poll(10.131,254,self.point)[1]
        self.assertEqual([e['action'] for e in events], ['bot_reload_complete','bot_attack'])
        self.assertEqual((bot.magazine,bot.reserve,bot.spent_ammunition), (0,0,3))
        self.assertEqual(bot.poll(40,1000,self.point)[1], [])
        self.assertEqual(bot.magazine+bot.reserve+bot.spent_ammunition, 3)

    def test_blocked_protected_range_and_nonfinite_do_not_spend_or_start_reload(self):
        wall = (((365500,543000,258000),(365600,545000,260000)),)
        for magazine in (0,2):
            with self.subTest(magazine=magazine):
                bot = self.make_bot(magazine,3,wall)
                for point, protected in ((self.point,False),(self.point,True),
                                         ((0,0,0),False),((float('nan'),0,0),False)):
                    bot.poll(20,500,point,protected)
                self.assertEqual((bot.magazine,bot.reserve,bot.spent_ammunition,bot.reload_at),
                                 (magazine,3,0,None))
        bot = self.make_bot(boxes=(((367000,543000,258000),(368000,545000,260000)),))
        event = bot.poll(2,50,self.point)[1][0]
        self.assertEqual((event['action'],event['validation'],bot.magazine),
                         ('bot_attack','diagnostic_ray_aabb',1))

    def test_reload_finishes_without_target_but_does_not_fire_and_death_cancels_it(self):
        bot = self.make_bot(0,2)
        bot.poll(2,50,self.point)
        events = bot.poll(5,125,None)[1]
        self.assertEqual([e['action'] for e in events], ['bot_reload_complete'])
        self.assertEqual((bot.magazine,bot.reserve,bot.spent_ammunition), (2,0,0))
        bot = self.make_bot(0,2)
        bot.poll(2,50,self.point)
        bot.diagnostic_area_damage(1000)
        self.assertIsNone(bot.reload_at)
        self.assertEqual(bot.poll(100,2500,self.point), ([],[]))
        self.assertEqual((bot.magazine,bot.reserve,bot.spent_ammunition), (0,2,0))
