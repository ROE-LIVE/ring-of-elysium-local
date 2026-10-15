"""Административные действия меняют модель; ID/отказы/ошибки не дублируют эффект."""
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
from copy import deepcopy

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server/directory'))
from live_scene_probe_2022 import LiveSceneCommands
from state_scene_actions_2022 import apply_state_action
from bot_controller_2022 import BotController
import test_bot_controller_2022 as bot_tests


class StateActionsTests(unittest.TestCase):
    def setUp(self):
        fixture=bot_tests.BotControllerTests();fixture.setUp()
        self.fixture=fixture
        self.world=SimpleNamespace(hp=1000,fixture=SimpleNamespace(hp=1000),dead=False)
        self.state=dict(actor_uid=1,world=self.world,weapon=fixture.player,target_actor=fixture.actor)

    def test_health_updates_authoritative_world_without_npc_or_inventory_effect(self):
        inventory=self.fixture.player.inventory();npc=self.fixture.actor.hp
        packets,event=apply_state_action(self.state,dict(action='set_own_health',hp=425))
        self.assertEqual((self.world.hp,event['hp']),(425,425));self.assertEqual(packets[0][0],0x1069)
        self.assertEqual(self.fixture.actor.hp,npc);self.assertEqual(self.fixture.player.inventory(),inventory)
        self.assertFalse(apply_state_action(self.state,dict(action='set_own_health',hp=1001))[1]['accepted'])
        self.world.dead=True
        self.assertEqual(apply_state_action(self.state,dict(action='set_own_health',hp=500))[0],[])
        self.assertEqual(self.world.hp,425)

    def test_ammo_inventory_is_current_and_hand_clip_unchanged_capacity_rejects(self):
        weapon=self.fixture.player;gun=weapon.guns[1];hand=weapon.hand_slot
        packets,event=apply_state_action(self.state,dict(action='give_ammo',definition=30004,quantity=3))
        self.assertEqual(weapon.reserve,6);self.assertIs(weapon.guns[1],gun)
        self.assertEqual((weapon.hand_slot,gun.clip),(hand,1));self.assertTrue(event['accepted'])
        self.assertEqual([x[0] for x in packets],[0x3e82,0x4a0,0x6f5])
        before=weapon.inventory()
        self.assertEqual(apply_state_action(self.state,dict(action='give_ammo',definition=30004,quantity=100))[0],[])
        self.assertEqual(weapon.inventory(),before)

    def test_npc_damage_death_cancels_motion_and_only_transfers_npc_items(self):
        bot=self.fixture.bot;bot.take(self.fixture.player,12)
        self.state['target_inventory']=bot.inventory
        packets,event=apply_state_action(self.state,dict(action='damage_npc',damage=1000))
        self.assertEqual(self.fixture.actor.hp,0);self.assertTrue(event['accepted'])
        self.assertEqual(event['corpse']['items'][0]['quantity'],6)
        self.assertEqual(self.fixture.player.reserve,3);self.assertEqual(bot.inventory.reserve,0)
        self.assertEqual(self.fixture.actor.poll(30,750),([],[]))
        self.assertEqual(apply_state_action(self.state,dict(action='damage_npc',damage=1000))[0],[])

    def test_bad_corpse_fixture_rolls_back_npc_hp_and_inventory(self):
        self.state['target_inventory']=self.fixture.bot.inventory
        self.state['target_inventory'].ground_template=None
        with self.assertRaises(ValueError):apply_state_action(self.state,dict(action='damage_npc',damage=1000))
        self.assertEqual(self.fixture.actor.hp,1000);self.assertNotIn('death_parcels',self.state)

    def test_action_idempotence_recipient_and_mixed_wire(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'commands.json'
            path.write_text(json.dumps([dict(id='give',action='give_ammo',definition=30004,quantity=3,recipient_actor_uid='0x1'),dict(id='wire',command='0x481',payload_hex='00')]))
            control=LiveSceneCommands(path)
            self.assertEqual([x[0] for x in control.poll(2,0,0)],['wire'])
            row=control.poll(1,0,0)[0];apply_state_action(self.state,row[2]);control.acknowledge(row[0])
            self.assertEqual(self.fixture.player.reserve,6)
            self.assertEqual([x[0] for x in control.poll(1,1,1)],['wire'])

    def test_queue_preserves_existing_actions_and_rejects_conflicting_id_atomically(self):
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
        from scene_action_2022 import enqueue
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'live-commands.json';path.write_text('[]')
            row=dict(id='heal',action='set_own_health',hp=425)
            self.assertTrue(enqueue(path,row));self.assertFalse(enqueue(path,row))
            before=path.read_bytes()
            with self.assertRaises(ValueError):enqueue(path,dict(row,hp=900))
            self.assertEqual(path.read_bytes(),before)
            self.assertTrue(enqueue(path,dict(id='ammo',action='give_ammo',quantity=3,definition=30004)))
            self.assertEqual([v['id'] for v in json.loads(path.read_text())],['heal','ammo'])
            before=path.read_bytes()
            with self.assertRaises(ValueError):enqueue(path,dict(id='bad id',action='damage_npc',damage=100))
            self.assertEqual(path.read_bytes(),before)

    def test_invalid_mixed_file_is_atomic_and_zero_death_payload_not_allowed(self):
        for bad in [dict(action='set_own_health',hp=0),dict(action='damage_npc',damage=True),dict(action='give_ammo',definition=999,quantity=3),dict(action='set_own_health',hp=500,payload_hex='00')]:
            with tempfile.TemporaryDirectory() as folder:
                path=Path(folder)/'commands.json';path.write_text(json.dumps([dict(id='good',action='set_own_health',hp=800),dict(id='bad',**bad)]))
                control=LiveSceneCommands(path)
                with self.assertRaises(ValueError):control.poll(1,0,0)
                self.assertEqual(control.commands,[]);self.assertEqual(control.sent,set())
