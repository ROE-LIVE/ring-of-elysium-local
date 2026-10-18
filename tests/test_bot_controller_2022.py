"""NPC controller: сохранение предметов, own isolation, безопасные цели/отказы."""
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import struct
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server/directory'))
from actor_probe_2022 import ActorFixture,ActorState
from bot_controller_2022 import BotController
from ground_route_2022 import GroundRoute
from weapon_probe_2022 import LootFixture,WeaponFixture,WeaponState


class BotControllerTests(unittest.TestCase):
    def test_controller_does_not_copy_player_starter_ammo_or_medical(self):
        fixture = replace(self.player.fixture, starter_items=((20002, 1), (30003, 15), (70001, 5)),
                          winter_starter_inventory=True)
        player = WeaponState(fixture, 1)
        bot = BotController(self.actor, player)
        self.assertEqual((bot.inventory.guns, bot.inventory.reserve,
                          bot.inventory.extra_ammunition, bot.inventory.medical), ({}, 0, {}, {}))
        self.assertEqual((player.extra_ammunition, player.medical), ({30003: 15}, {70001: 5}))

    def setUp(self):
        self.graph=GroundRoute((('a',(0,0,100)),('b',(0,300,120)),('c',(600,300,140))),
                               (('a','b'),('b','c')),('a','c'),(), 'тест walk')
        self.actor=ActorState(ActorFixture(99,b'',b'',bytes(40),(0,0,100),
                            self.graph.patrol_waypoints(),200,1000,50,
                            ground_route=self.graph,movement_animation=True,
                            behavior=dict(loot_indexes=[12],after_seconds=2,speed_cm_seconds=200)))
        self.actor.started=True
        entity=bytearray(100);entity[62]=2
        struct.pack_into('>I',entity,0,30201002);struct.pack_into('>Q',entity,4,111)
        struct.pack_into('>3i',entity,29,0,0,100);struct.pack_into('>III',entity,63,30004,6,12)
        ground=LootFixture(111,12,6,(0,0,100),bytes(45),30004,bytes(entity))
        self.player=WeaponState(WeaponFixture(bytes(82),bytes(60),loot=ground,inventory_update='delta',weapon_slots=2),1)
        self.player.reserve=3;self.player.clip=1;self.player.hand_slot=1
        self.player.available_loot={111};self.player.loot_available=True
        self.bot=BotController(self.actor,self.player)
        self.world=SimpleNamespace(fixture=SimpleNamespace(hazard=(-50,-50,100,100),region_grid=None,
                                                         zero_region_is_frozen=False),closed=set())

    def test_pickup_consumes_ground_once_and_preserves_own_inventory(self):
        inventory=self.player.inventory();reserve=self.player.reserve
        packets,event=self.bot.take(self.player,12)
        self.assertEqual(event['quantity'],6);self.assertEqual(self.bot.inventory.reserve,6)
        self.assertEqual(self.player.reserve,reserve);self.assertEqual(self.player.inventory(),inventory)
        self.assertEqual([code for code,_ in packets],[0x82b,0x547])
        self.assertEqual(struct.unpack_from('>Q',packets[-1][1])[0],99)
        self.assertIn(12,self.player.picked_loot);self.assertFalse(self.player.loot_available)
        self.assertEqual(self.bot.take(self.player,12)[1]['reason'],'unavailable')
        self.assertEqual(self.bot.inventory.reserve,6)

    def test_player_wins_race_npc_cannot_duplicate_or_take_far_item(self):
        self.player.picked_loot.add(12)
        self.assertEqual(self.bot.take(self.player,12)[1]['reason'],'unavailable')
        self.player.picked_loot.clear();self.actor.position=(200,0,100)
        self.assertEqual(self.bot.take(self.player,12)[1]['reason'],'distance')
        self.assertEqual(self.bot.inventory.reserve,0);self.assertNotIn(12,self.player.picked_loot)

    def test_partial_pickup_conserves_remaining_stack(self):
        self.bot.inventory.reserve=79
        packets,event=self.bot.take(self.player,12)
        self.assertEqual((event['quantity'],event['remaining']), (1,5))
        self.assertEqual(self.player.loot_registry[12].quantity,5)
        self.assertNotIn(12,self.player.picked_loot);self.assertIn(111,self.player.available_loot)
        self.assertEqual([x[0] for x in packets],[0x82b,0x821,0x547])
        self.assertEqual(self.player.reserve,3)

    def test_own_sync_is_never_sent_and_remote_gun_has_separate_identity(self):
        item=self.player.loot_registry[12]
        self.player.loot_registry[12]=replace(item,definition=10402,quantity=1)
        packets,event=self.bot.take(self.player,12)
        self.assertEqual(event['npc_guns'],{1:10402});self.assertEqual(self.bot.inventory.hand_slot,1)
        self.assertNotEqual(self.bot.inventory.guns[1].uid,self.player.guns[1].uid)
        self.assertFalse(set(code for code,_ in packets)&{0x5fb,0x3e82,0x4a0,0x3b64})
        self.assertEqual(self.player.guns[1].clip,1)

    def test_finite_route_stops_at_endpoint_without_loop_or_shortcut(self):
        self.assertTrue(self.bot.route_to('c'));self.actor.patrol(0,0)
        for second in range(1,8):self.actor.patrol(second,second*25)
        self.assertEqual(self.actor.position,(600,300,140));self.assertEqual(self.actor.fixture.speed,0)
        before=self.actor.position;self.actor.patrol(10,250);self.assertEqual(self.actor.position,before)

    def test_controller_loot_safe_and_explicit_evac_block_then_no_duplicates(self):
        self.bot.poll(0,self.player,self.world)
        events=self.bot.poll(2,self.player,self.world)[1]
        self.assertIn('bot_loot_pickup',[e['action'] for e in events])
        events=self.bot.poll(3,self.player,self.world)[1]
        self.assertIn('bot_safe_route',[e['action'] for e in events])
        self.actor.patrol(3,75);self.actor.patrol(5,125)
        vehicles=SimpleNamespace(vehicles={88:dict(configuration=6,position=(200000,200000,500))})
        events=self.bot.poll(5,self.player,self.world,vehicles)[1]
        self.assertIn('bot_safe_reached',[e['action'] for e in events])
        self.assertEqual(events[-1]['reason'],'outside_verified_graph')
        self.assertEqual(self.actor.fixture.speed,0)
        self.assertEqual(self.bot.poll(11,self.player,self.world,vehicles)[1],[])
        self.assertEqual(self.player.reserve,3)

    def test_all_nodes_dangerous_and_dead_guard(self):
        self.bot.pending=[];self.bot.started=0;self.bot.phase='seeking_safe'
        self.world.fixture.hazard=(-100,-100,1000,1000)
        events=self.bot.poll(3,self.player,self.world)[1]
        self.assertEqual(events[0]['reason'],'no_safe_node')
        self.assertEqual(self.actor.fixture.speed,0)
        self.assertEqual(self.bot.poll(4,self.player,self.world)[1],[])
        self.actor.hp=0;self.assertEqual(self.bot.poll(5,self.player,self.world),([],[]))

    def test_closed_region_and_frozen_zero_are_not_safe_goals(self):
        self.world.fixture.hazard=(1000,1000,2000,2000)
        self.world.fixture.region_grid=SimpleNamespace(regions=lambda p:frozenset((2,)),region_id=lambda p:2)
        self.world.closed={2};self.assertFalse(self.bot.safe((0,0,100),self.world))
        self.world.closed=set();self.assertTrue(self.bot.safe((0,0,100),self.world))
        self.world.fixture.zero_region_is_frozen=True
        self.world.fixture.region_grid.region_id=lambda p:0
        self.assertFalse(self.bot.safe((0,0,100),self.world))
