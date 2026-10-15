"""Старые application-id не переключают руки и не расходуют новый магазин."""
from dataclasses import replace
import struct
import unittest
import test_game_endpoint_probe_2022 as gameplay_tests


class GameplaySequenceTests(unittest.TestCase):
    def setUp(self):
        self.game=gameplay_tests.GameplayActionReplayTests()
        self.game.setUp()
        self.addCleanup(self.game.doCleanups)

    @staticmethod
    def fire(counter, mode=0):
        return struct.pack('>6fIBIIfII',0,0,0,0,0,0,counter,mode,1,0,0,0,0)

    def test_old_hand_does_not_cancel_later_reload(self):
        weapon=self.game.weapon
        weapon.fixture=replace(weapon.fixture,timed_reload=True,reload_update='delta')
        weapon.clip=1
        self.game.request(100,0x49e,struct.pack('>I',0))
        self.game.request(101,0x49e,struct.pack('>I',1))
        self.game.request(102,0x49c,struct.pack('>I',1))
        pending=weapon.pending_reload
        self.assertIsNotNone(pending)
        self.game.request(100,0x49e,struct.pack('>I',0))
        self.assertEqual(weapon.hand_slot,1)
        self.assertIs(weapon.pending_reload,pending)
        # Новое действие с тем же payload остаётся допустимым.
        self.game.request(103,0x49e,struct.pack('>I',0))
        self.assertEqual(weapon.hand_slot,0)
        self.assertIsNone(weapon.pending_reload)

    def test_stale_fire_cannot_spend_new_ammunition_after_counter_cache_eviction(self):
        self.game.request(100,0x11da,self.fire(1))
        self.game.request(101,0x49c,struct.pack('>I',1))
        for counter in range(2,66):
            self.game.request(100+counter,0x11da,self.fire(counter))
        self.assertNotIn(1,self.game.weapon.shots)
        self.game.request(200,0x49c,struct.pack('>I',1))
        before=(self.game.weapon.clip,self.game.weapon.reserve)
        self.game.request(100,0x11da,self.fire(1))
        self.assertEqual((self.game.weapon.clip,self.game.weapon.reserve),before)
        self.game.request(201,0x11da,self.fire(66))
        self.assertEqual(self.game.weapon.clip,before[0]-1)

    def test_mixed_actions_accept_serial_wrap_and_reject_old_epoch_counter(self):
        self.game.request(0xfffffffe,0x11da,self.fire(1))
        self.game.request(0xffffffff,0x49e,struct.pack('>I',0))
        self.game.request(0,0x49e,struct.pack('>I',1))
        self.game.request(1,0x11da,self.fire(2))
        self.assertEqual((self.game.weapon.hand_slot,self.game.weapon.clip),(1,0))
        self.game.request(0xffffffff,0x49e,struct.pack('>I',0))
        self.assertEqual(self.game.weapon.hand_slot,1)
