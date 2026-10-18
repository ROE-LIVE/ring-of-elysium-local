"""Независимые HP/броня/shot identity/пакеты смерти десяти пассивных мишеней."""
from dataclasses import replace
import json
from pathlib import Path
import struct
import sys
import tempfile
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'server/directory'))
from actor_probe_2022 import ActorFixture
from target_roster_2022 import TargetRoster, load_actor_fixtures
from death_parcel_2022 import target_inventory
from game_endpoint_probe_2022 import Endpoint
from weapon_probe_2022 import LootFixture, WeaponFixture, WeaponState
from state_scene_actions_2022 import apply_state_action, validate_state_action

WORK = ROOT / 'research/builds/2022/iceland-gameplay-20261006'


class TargetRosterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'targets.json'
        template = WORK / 'actor-static.json'
        if not template.exists():
            sys.path.insert(0, str(ROOT / 'tools'))
            from windows_launch import materialize
            assets = Path(self.temp.name) / 'assets'
            assets.mkdir()
            template = materialize(assets, 'glider')['target-plain']
            control = json.loads(template.read_text())
            control['pellet_damage'] = 50
            template = assets / 'target-control.json'
            template.write_text(json.dumps(control))
        self.config = dict(template_file=str(template), passive_targets=[
            dict(uid=hex(0x2040000800000 + i), position=[366000 + i * 100, 544000, 259060])
            for i in range(10)])
        self.fire = struct.pack('>6fIBIIfII', 365073, 543901, 259245,
                                366062, 544013, 259155, 4, 0, 14275, 7, 480, 64, 0)
        self.hit = bytearray(106)
        self.hit[62] = 3
        struct.pack_into('>I', self.hit, 88, 4)
        struct.pack_into('>I', self.hit, 96, 14275)
        ground = bytearray(100)
        struct.pack_into('>I', ground, 0, 30201002)
        ground[62] = 2
        self.weapon = WeaponFixture(bytes(82), bytes(60), gun_on_start=False,
            loot=LootFixture(99, 123, 1, (0, 0, 0), bytes(45), entity=bytes(ground)))

    def fixtures(self):
        self.path.write_text(json.dumps(self.config))
        return load_actor_fixtures(self.path)

    def payload(self, actor, counter=4):
        hit = bytearray(self.hit)
        struct.pack_into('>Q', hit, 4, actor.fixture.uid)
        struct.pack_into('>iii', hit, 37, *actor.position)
        struct.pack_into('>I', hit, 88, counter)
        return bytes(hit)

    def test_clone_wire_uid_and_positions_match_each_actor(self):
        fixtures = self.fixtures()
        self.assertEqual(len(fixtures), 10)
        for fixture in fixtures:
            self.assertEqual(struct.unpack_from('>Q', fixture.listing, 14)[0], fixture.uid)
            self.assertEqual(struct.unpack_from('>Q', fixture.profile, 8)[0], fixture.uid)
            self.assertEqual(struct.unpack_from('>Q', fixture.movement)[0], fixture.uid)
            self.assertEqual(struct.unpack_from('>iii', fixture.profile, 1051), fixture.position)

    def test_duplicate_unknown_and_excess_targets_rejected(self):
        self.config['passive_targets'][1]['uid'] = self.config['passive_targets'][0]['uid']
        with self.assertRaises(ValueError):
            self.fixtures()
        self.config['passive_targets'] *= 2
        with self.assertRaises(ValueError):
            self.fixtures()

    def test_nonfinite_and_extra_fields_rejected(self):
        for value in (float('nan'), float('inf'), True, 10000001):
            self.config['passive_targets'][0]['position'][0] = value
            with self.assertRaises(ValueError):
                self.fixtures()

    def test_low_uid_collision_rejected_even_with_distinct_full_uid(self):
        self.config['passive_targets'][1]['uid'] = hex(int(self.config['passive_targets'][0]['uid'], 0) + 2**32)
        with self.assertRaises(ValueError):
            self.fixtures()

    def test_own_uid_cannot_be_used_as_target(self):
        fixtures = self.fixtures()
        with self.assertRaises(ValueError):
            TargetRoster(fixtures, self.weapon, fixtures[0].uid)

    def test_accepted_hit_changes_only_addressed_actor_and_replay_is_safe(self):
        roster = TargetRoster(self.fixtures(), self.weapon, 42)
        actors = list(roster.actors.values())
        for actor in actors:
            actor.begin(100)
        roster.note_fire(self.fire, {'action': 'fire', 'gun_definition': 10201})
        packets, event, actor = roster.hit(self.payload(actors[0]), 42)
        self.assertEqual((actor.hp, event['damage']), (950, 50))
        self.assertTrue(all(a.hp == 1000 for a in actors[1:]))
        self.assertEqual(roster.hit(self.payload(actors[0]), 42)[1]['reason'], 'duplicate_hit')
        self.assertEqual(roster.hit(self.payload(actors[1]), 42)[1]['reason'], 'pellet_reused_target')
        self.assertTrue(all(a.hp == 1000 for a in actors[1:]))

    def test_no_accepted_shot_or_unknown_uid_cannot_damage(self):
        roster = TargetRoster(self.fixtures(), self.weapon, 42)
        actor = next(iter(roster.actors.values()))
        actor.begin(100)
        self.assertEqual(roster.hit(self.payload(actor), 42)[1]['reason'], 'unaccepted_shot_or_pellet')
        hit = bytearray(self.payload(actor)); struct.pack_into('>Q', hit, 4, 998)
        self.assertEqual(roster.hit(hit, 42)[1]['reason'], 'unknown_target')
        self.assertEqual(actor.hp, 1000)

    def test_target_inventory_does_not_inherit_player_starter_kit_ammo_or_medical(self):
        actor = next(iter(TargetRoster(self.fixtures(), self.weapon, 42).actors.values()))
        actor.fixture = replace(actor.fixture, death_loot_reserve=6)
        source = replace(self.weapon, starter_items=((20002, 1), (30003, 15), (70001, 5), (200907, 1)),
                         winter_starter_inventory=True, starting_equipment=(200907,))
        inventory = target_inventory(actor, source)
        self.assertEqual((inventory.reserve, inventory.extra_ammunition, inventory.medical), (6, {}, {}))
        self.assertEqual((inventory.guns, inventory.equipment), ({}, {}))

    def test_ten_deaths_make_ten_independent_parcels_and_replay_does_not_duplicate(self):
        fixtures = tuple(replace(f, hp=50, death_loot_reserve=6) for f in self.fixtures())
        events, packets = [], []
        endpoint = Endpoint(SimpleNamespace(record=lambda kind, **event: events.append(dict(kind=kind, **event))),
                            actor_fixture=fixtures)
        endpoint.send_application_batch = lambda d, remote, state, messages: packets.extend(messages)
        state = dict(actor_uid=42, weapon=WeaponState(self.weapon, 42))
        endpoint.handle_targets(None, None, state, SimpleNamespace(command=0x1f49, payload=b''))
        roster = state['target_roster']
        for number, actor in enumerate(roster.actors.values(), 10):
            fire = bytearray(self.fire); struct.pack_into('>I', fire, 24, number)
            roster.note_fire(fire, {'action': 'fire'})
            message = SimpleNamespace(command=0x11dd, payload=self.payload(actor, number))
            endpoint.handle_targets(None, None, state, message)
            endpoint.handle_targets(None, None, state, message)
        self.assertEqual(len(state['death_parcels'].containers), 10)
        self.assertEqual(len({c.fixture.uid for c in state['death_parcels'].containers}), 10)
        self.assertEqual(sum(code == 0x533 for code, _ in packets), 10)
        self.assertEqual(sum(e.get('action') == 'hit_damage' for e in events), 10)
        self.assertTrue(all(a.hp == 0 for a in roster.actors.values()))

    def test_handoff_moves_complete_registry_without_resetting_hp_or_inventory(self):
        fixtures = tuple(replace(f, death_loot_reserve=6) for f in self.fixtures())
        roster = TargetRoster(fixtures, self.weapon, 42)
        first = next(iter(roster.actors.values()))
        first.hp = 700
        roster.inventories[first.fixture.uid].reserve = 3
        endpoint = Endpoint(SimpleNamespace(record=lambda *args, **kw: None), actor_fixture=fixtures)
        old_key = (('127.0.0.1', 1111), 5000, 18001)
        new_key = (('127.0.0.1', 2222), 5001, 18001)
        old = dict(identity=b'local\0', auth_sent=True, room_sent=True, handoff_at=100,
                   weapon=WeaponState(self.weapon, 42), actor_uid=42, room_uid=456,
                   frame_seq=1023, seq=999, target_roster=roster,
                   target_actor=first, target_inventory=roster.inventories[first.fixture.uid])
        new = dict(identity=b'local\0', auth_sent=True, room_sent=False, frame_seq=3, seq=20)
        endpoint.sessions = {old_key: old, new_key: new}
        self.assertTrue(endpoint.resume_gameplay(new_key, new, 101))
        self.assertIs(new['target_roster'], roster)
        self.assertEqual(len(roster.actors), 10)
        self.assertEqual((first.hp, roster.inventories[first.fixture.uid].reserve), (700, 3))
        self.assertNotIn('target_roster', old)
        self.assertFalse(endpoint.resume_gameplay(new_key, new, 102))

    def test_grenade_routes_only_to_reported_targets_within_diagnostic_radius(self):
        fixtures = self.fixtures()
        weapon_fixture = replace(self.weapon, diagnostic_frag_damage=100)
        endpoint = Endpoint(SimpleNamespace(record=lambda *args, **kw: None), actor_fixture=fixtures)
        endpoint.send_application_batch = lambda *args: None
        state = dict(actor_uid=42, weapon=WeaponState(weapon_fixture, 42))
        endpoint.handle_targets(None, None, state, SimpleNamespace(command=0x1f49, payload=b''))
        actors = list(state['target_roster'].actors.values())
        finished = SimpleNamespace(definition=50001, point=actors[0].position,
                                   actors=(actors[0].fixture.uid, actors[1].fixture.uid),
                                   actor_fields=(), identifier=99)
        endpoint.apply_diagnostic_grenade(None, None, state, finished)
        self.assertEqual([a.hp for a in actors], [900, 900] + [1000] * 8)

    def test_administrative_damage_addresses_one_npc_and_its_inventory(self):
        fixtures = tuple(replace(f, death_loot_reserve=6) for f in self.fixtures())
        roster = TargetRoster(fixtures, self.weapon, 42)
        for actor in roster.actors.values():
            actor.begin(1)
        first, target = list(roster.actors.values())[0], list(roster.actors.values())[7]
        state = dict(actor_uid=42, weapon=WeaponState(self.weapon, 42), target_roster=roster,
                     target_actor=first, target_inventory=roster.inventories[first.fixture.uid],
                     world=SimpleNamespace(dead=False))
        request = validate_state_action(dict(action='damage_npc', damage=400, npc_uid=hex(target.fixture.uid)))
        _, event = apply_state_action(state, request)
        self.assertEqual((target.hp, first.hp), (600, 1000))
        self.assertTrue(event['administrative'])
        request['damage'] = 600
        _, event = apply_state_action(state, request)
        self.assertEqual((target.hp, first.hp), (0, 1000))
        self.assertEqual(state['death_parcels'].owners, {target.fixture.uid})
        self.assertEqual(roster.inventories[first.fixture.uid].reserve, 6)
        self.assertEqual(roster.inventories[target.fixture.uid].reserve, 0)
        self.assertFalse(apply_state_action(state, request)[1]['accepted'])
        self.assertEqual(len(state['death_parcels'].containers), 1)
        request['npc_uid'] = 998
        self.assertEqual(apply_state_action(state, request)[1]['reason'], 'npc_uid_not_found')

    def test_bad_npc_uid_cannot_be_used_in_typed_actions(self):
        for uid in (0, -1, 2**64, True, 'not-a-uid'):
            with self.assertRaises(ValueError):
                validate_state_action(dict(action='damage_npc', damage=100, npc_uid=uid))
        with self.assertRaises(ValueError):
            validate_state_action(dict(action='give_ammo', definition=30004, quantity=1, npc_uid=5))

    def test_bot_controller_identity_and_spent_inventory_survive_handoff_then_finish_releases_them(self):
        import test_bot_controller_2022 as bot_tests
        fixture = bot_tests.BotControllerTests()
        fixture.setUp()
        bot = fixture.bot
        bot.phase = 'safe'
        bot.inventory.reserve = 1
        endpoint = Endpoint(SimpleNamespace(record=lambda *args, **kw: None))
        old_key = (('127.0.0.1', 1111), 5000, 18001)
        new_key = (('127.0.0.1', 2222), 5001, 18001)
        old = dict(identity=b'local\0', auth_sent=True, room_sent=True, handoff_at=100,
                   weapon=fixture.player, actor_uid=1, room_uid=456, frame_seq=1023, seq=999,
                   target_actor=bot.actor, target_inventory=bot.inventory, bot_controller=bot)
        new = dict(identity=b'local\0', auth_sent=True, room_sent=False, frame_seq=3, seq=20)
        endpoint.sessions = {old_key: old, new_key: new}
        self.assertTrue(endpoint.resume_gameplay(new_key, new, 101))
        self.assertIs(new['bot_controller'], bot)
        self.assertIs(new['target_inventory'], bot.inventory)
        self.assertIs(new['target_actor'], bot.actor)
        self.assertEqual((bot.phase, bot.inventory.reserve), ('safe', 1))
        endpoint.finish_gameplay(new, None, 'test_timeout')
        self.assertNotIn('bot_controller', new)
        self.assertNotIn('target_actor', new)
        self.assertNotIn('target_inventory', new)


if __name__ == '__main__':
    unittest.main()
