"""Регрессии переносимости, изоляции копии и отсутствия активных port probes."""
import hashlib
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'));sys.path.insert(0,str(ROOT/'server/directory'))
import windows_launch as launcher
from weapon_probe_2022 import WeaponFixture
from game_endpoint_probe_2022 import load_scene_rules
from roe_room_2023 import decode_enter_room_response
from local_cosmetics_2022 import LocalCosmetics
from environment_probe_2022 import EnvironmentFixture


class WindowsKitTests(unittest.TestCase):
    def test_passive_target_roster_has_ten_unique_native_uids_and_ground_points(self):
        from target_roster_2022 import load_actor_fixtures
        with tempfile.TemporaryDirectory() as folder:
            configs = launcher.materialize(Path(folder), 'glider', practice_targets=10)
            for kind in ('plain', 'armored'):
                fixtures = load_actor_fixtures(configs['target-' + kind])
                self.assertEqual(len(fixtures), 10)
                self.assertEqual(len({f.uid for f in fixtures}), 10)
                self.assertTrue(all(not f.attack and f.speed == 0 for f in fixtures))
                self.assertTrue(all(366300 <= f.position[0] <= 366700 for f in fixtures))
                self.assertTrue(all(258900 <= f.position[2] <= 259200 for f in fixtures))

    def test_target_roster_default_preserves_single_target_and_rejects_bad_counts(self):
        from target_roster_2022 import load_actor_fixtures
        with tempfile.TemporaryDirectory() as folder:
            configs = launcher.materialize(Path(folder), 'glider')
            fixtures = load_actor_fixtures(configs['target-armored'])
            self.assertEqual((len(fixtures), fixtures[0].position), (1, (366650, 544149, 259077)))
        for count in (True, 0, 11, 1.5):
            with tempfile.TemporaryDirectory() as folder, self.assertRaises(ValueError):
                launcher.materialize(Path(folder), 'glider', practice_targets=count)

    def test_cycle_pacing_materializes_one_calendar_and_disables_training_hazard(self):
        with tempfile.TemporaryDirectory() as folder:
            configs = launcher.materialize(Path(folder), 'glider', cycle_scale=3)
            world = json.loads(configs['world'].read_text())
            scene = json.loads(configs['scene-cycle'].read_text())
            self.assertFalse(world['hazard']['enabled'])
            self.assertEqual(world['stages'][-1]['duration'],162)
            self.assertAlmostEqual(world['stages'][-1]['at_seconds'],405.9)
            delays = [r.get('after_selection_delay_seconds') for r in scene]
            self.assertIn(3,delays)
            self.assertIn(180,delays)
            self.assertIn(383.4,delays)
        with tempfile.TemporaryDirectory() as folder:
            configs = launcher.materialize(Path(folder), 'glider', diagnostic_hazard=True)
            self.assertTrue(json.loads(configs['world'].read_text())['hazard']['enabled'])
        for arguments in (dict(cycle_scale=True),dict(cycle_scale=11),
                          dict(diagnostic_hazard=1),dict(native_evacuation=True,cycle_scale=3)):
            with tempfile.TemporaryDirectory() as folder,self.assertRaises(ValueError):
                launcher.materialize(Path(folder),'glider',**arguments)

    def test_winter_windows_materialize_preserves_resource_catalog(self):
        from breakable_state_2022 import BreakableFixture
        with tempfile.TemporaryDirectory() as folder:
            configs=launcher.materialize(Path(folder),'snowboard',winter_windows=True)
            fixture=BreakableFixture.load(configs['winter-breakables'])
            self.assertEqual(len(fixture.entities),7118)
            self.assertEqual(fixture.entities[7690],((417391.53125,557270.25,259595.203125),(1,)))
            self.assertEqual(configs['winter-breakables'].read_bytes(),(ROOT/'config/winter-breakables.json').read_bytes())
            self.assertNotEqual(configs['winter-breakables'],ROOT/'config/winter-breakables.json')
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):launcher.materialize(Path(folder),'snowboard',winter_windows=1)

    def test_winter_doors_materialize_copies_valid_catalog(self):
        from door_state_2022 import DoorFixture
        with tempfile.TemporaryDirectory() as folder:
            configs=launcher.materialize(Path(folder),'snowboard',winter_doors=True)
            self.assertEqual(configs['winter-doors'].read_bytes(),(ROOT/'config/winter-doors.json').read_bytes())
            fixture=DoorFixture.load(configs['winter-doors'])
            self.assertIn(7767,fixture.doors)
            self.assertEqual(fixture.doors[7767][0],(415727.9375,557603.5625,259024.234375))

    def test_winter_doors_requires_explicit_boolean(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):launcher.materialize(Path(folder),'snowboard',winter_doors='yes')


    def test_profiles_resolve_durable_state_without_sharing_or_modifying_catalog(self):
        from local_account_2022 import local_account
        original=(ROOT/'config/cosmetics.json').read_bytes()
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder)
            for name in ('default','Alice','bob'):
                run=base/name;run.mkdir()
                configs=launcher.materialize(run,'snowboard',account_profile=name)
                catalog=json.loads(configs['cosmetics'].read_text())
                self.assertEqual(catalog['state_file'],local_account(ROOT/'runtime',name)['state_file'])
                self.assertEqual(json.loads(configs['weapon-snowboard'].read_text())['cosmetics_config_file'],str(configs['cosmetics']))
            with self.assertRaises(ValueError):
                launcher.materialize(base/'invalid','snowboard',account_profile='../bad')
            self.assertFalse((base/'invalid').exists())
        self.assertEqual((ROOT/'config/cosmetics.json').read_bytes(),original)

    def test_bot_behavior_has_private_empty_inventory_and_actual_consumable_ground(self):
        from actor_probe_2022 import ActorFixture
        with tempfile.TemporaryDirectory() as folder:
            configs=launcher.materialize(Path(folder),'snowboard',bot_ground_route=True,bot_behavior=True)
            actor=ActorFixture.load(configs['actor'])
            self.assertEqual(actor.behavior['loot_indexes'],[92001,92002])
            self.assertIsNone(actor.attack);self.assertFalse(actor.equipment)
            weapon=WeaponFixture.load(configs['weapon-snowboard'])
            items={x.index:x for x in weapon.all_loot}
            self.assertEqual((items[92001].definition,items[92002].quantity),(10402,6))
            self.assertEqual(items[92001].position,actor.position)
            world=json.loads(configs['world'].read_text())
            self.assertEqual(world['hazard']['bounds_xy'],[370600,543200,370750,544350])
        with tempfile.TemporaryDirectory() as folder,self.assertRaises(ValueError):
            launcher.materialize(Path(folder),'snowboard',bot_behavior=True)

    def test_ground_bot_profile_binds_measured_graph_without_moving_own_spawn(self):
        import struct
        from actor_probe_2022 import ActorFixture
        for enabled in (False,True):
            with tempfile.TemporaryDirectory() as folder:
                configs=launcher.materialize(Path(folder),'snowboard',bot_ground_route=enabled)
                fixture=ActorFixture.load(configs['actor'])
                self.assertEqual(fixture.movement_animation,enabled)
                self.assertEqual(fixture.attack_ammunition,(2,6))
                if enabled:
                    self.assertEqual(fixture.position,(370653,544252,258844))
                    self.assertEqual(len(fixture.ground_route.nodes),56)
                    self.assertEqual(fixture.speed,200)
                    self.assertEqual(fixture.attack_pause_seconds,1)
                    self.assertTrue(fixture.collision_boxes)
                own=[r[1] for q in load_scene_rules(configs['scene-walk']) for r in q[1] if r[0]==0x27]
                self.assertTrue(own)
                for body in own:self.assertLess(struct.unpack_from('>i',body,8)[0],370000)

    def test_bot_profile_has_finite_citori_inventory_and_explicit_los_control(self):
        from actor_probe_2022 import ActorFixture,ActorState
        for mode in ('off','open','blocked'):
            with tempfile.TemporaryDirectory() as folder:
                configs=launcher.materialize(Path(folder),'snowboard',target_los=mode)
                fixture=ActorFixture.load(configs['actor'])
                self.assertEqual(fixture.attack_ammunition,(2,6))
                actor=ActorState(fixture);actor.begin(0)
                point=(365100,544000,259100)
                actor.poll(0,0,point)
                attacks=actor.poll(31,775,point)[1]
                self.assertEqual(sum(e['action']=='bot_attack' for e in attacks),int(mode!='blocked'))
                self.assertEqual(actor.magazine,2 if mode=='blocked' else 1)

    def test_boat_practice_has_empty_part_vectors_source_point_and_fixed_actor_spawn(self):
        import struct
        from boat_practice_2022 import BOAT_UID,BOAT_POSITION,PLAYER_POSITION
        with tempfile.TemporaryDirectory() as folder:
            configs=launcher.materialize(Path(folder),'snowboard',boat_practice=True)
            rules=load_scene_rules(configs['scene-walk'])
            boats=[r[1] for rule in rules for r in rule[1] if r[0]==0x654b and struct.unpack_from('>Q',r[1])[0]==BOAT_UID]
            self.assertEqual(len(boats),1)
            body=boats[0]
            self.assertEqual(len(body),79)
            self.assertEqual(struct.unpack_from('>I',body,8)[0],203)
            self.assertEqual(struct.unpack_from('>3i',body,20),BOAT_POSITION)
            self.assertEqual(struct.unpack_from('>2I',body,66),(0,0))
            own=[r for rule in rules if len(rule)>=3 and rule[2] for r in rule[1] if r[0]==0x27]
            self.assertTrue(own)
            for r in own:
                self.assertEqual(struct.unpack_from('>3i',r[1],8),PLAYER_POSITION)
                self.assertTrue(r[4])
        for cycle,climb in [(True,False),(False,True)]:
            with tempfile.TemporaryDirectory() as folder:
                with self.assertRaises(ValueError):
                    launcher.materialize(Path(folder),'climb',cycle=cycle,climb_practice=climb,boat_practice=True)

    def test_snowmotor_profile_preserves_vehicle_uid_position_and_other_types(self):
        import struct
        with tempfile.TemporaryDirectory() as a,tempfile.TemporaryDirectory() as b:
            normal=launcher.materialize(Path(a),'snowboard',original_jeeps=True)
            snow=launcher.materialize(Path(b),'snowboard',original_jeeps=True,vehicle_profile='snowmotor')
            for name in ('scene-walk','scene-cycle'):
                def vehicles(path):
                    return [r[1] for rule in load_scene_rules(path) for r in rule[1] if r[0]==0x654b]
                n,s=vehicles(normal[name]),vehicles(snow[name])
                self.assertEqual(len(n),len(s))
                count=0
                for old,new in zip(n,s):
                    if len(old)==164 and struct.unpack_from('>I',old,8)[0]==102:
                        self.assertEqual(new[:8],old[:8])
                        self.assertEqual(new[12:],old[12:])
                        self.assertEqual(struct.unpack_from('>I',new,8)[0],109)
                        count+=1
                    else:self.assertEqual(new,old)
                self.assertGreaterEqual(count,2)

    def test_climb_practice_is_explicit_and_keeps_the_current_actor_and_tick(self):
        import struct
        for enabled in (False,True):
            with tempfile.TemporaryDirectory() as folder:
                configs=launcher.materialize(Path(folder),'climb',climb_practice=enabled)
                responses=[r for rule in load_scene_rules(configs['scene-walk'])
                           if len(rule)>=3 and rule[2] for r in rule[1] if r[0]==0x27]
                self.assertTrue(responses)
                for response in responses:
                    if enabled:
                        self.assertEqual(struct.unpack_from('>3i',response[1],8),(548255,483380,255000))
                        self.assertEqual(response[4],True)
                    else:
                        self.assertLess(len(response),5)
                    self.assertIn(0,response[2])
                    self.assertIn(31,response[3])
        for kit,cycle in [('snowboard',False),('climb',True)]:
            with tempfile.TemporaryDirectory() as folder:
                with self.assertRaises(ValueError):
                    launcher.materialize(Path(folder),kit,cycle=cycle,climb_practice=True)

    def test_original_jeeps_materialize_without_moving_player(self):
        import struct
        from original_jeeps_2022 import POINTS, UIDS
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            default = launcher.materialize(Path(a), 'snowboard')
            enabled = launcher.materialize(Path(b), 'snowboard', original_jeeps=True)
            for name in ('scene-walk', 'scene-cycle'):
                scene = json.loads(enabled[name].read_text())
                rules = load_scene_rules(enabled[name])
                self.assertTrue(rules)
                extra = scene[-1]['responses']
                self.assertEqual(len(extra), 2)
                for response, uid, (_, _, xyz) in zip(extra, UIDS, POINTS):
                    body = bytes.fromhex(response['payload_hex'])
                    self.assertEqual(struct.unpack_from('>Q', body)[0], uid)
                    self.assertEqual(struct.unpack_from('>3i', body, 20), xyz)
                original = json.loads(default[name].read_text())
                self.assertEqual(len(scene), len(original)+1)
                # Все исходные сообщения сохраняются, меняются лишь пути run/wire.
                self.assertEqual([r.get('command') for q in original for r in q['responses']],
                                 [r.get('command') for q in scene[:-1] for r in q['responses']])

    def test_departure_requires_explicit_flight_and_preserves_default(self):
        from vehicle_probe_2022 import EvacuationUIFixture
        for enabled in (False,True):
            with tempfile.TemporaryDirectory() as folder:
                configs=launcher.materialize(Path(folder),'snowboard',native_evacuation=enabled,
                                             diagnostic_departure=enabled)
                fixture=EvacuationUIFixture.load(configs['evacuation'])
                self.assertEqual(fixture.diagnostic_departure_seconds,20 if enabled else 0)
                row=json.loads(configs['evacuation'].read_text())
                for bad in (True,-1,1,31):
                    row['diagnostic_departure_seconds']=bad
                    configs['evacuation'].write_text(json.dumps(row))
                    with self.assertRaises(ValueError):EvacuationUIFixture.load(configs['evacuation'])
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                launcher.materialize(Path(folder),'snowboard',diagnostic_departure=True)

    def test_native_evacuation_materializes_matching_parent_and_motion(self):
        import struct
        from vehicle_probe_2022 import VehicleState
        with tempfile.TemporaryDirectory() as folder:
            configs=launcher.materialize(Path(folder),'snowboard',native_evacuation=True)
            scene=json.loads(configs['scene-cycle'].read_text())
            state=VehicleState(42)
            codes=[]
            for rule in scene:
                for response in rule['responses']:
                    code=int(response['command'],0);codes.append(code)
                    body=(Path(response['payload_file']).read_bytes() if 'payload_file' in response
                          else bytes.fromhex(response['payload_hex']))
                    state.register(code,body)
            plane=[(uid,v) for uid,v in state.vehicles.items() if v['configuration']==6]
            self.assertEqual(len(plane),1)
            uid,vehicle=plane[0]
            self.assertEqual(vehicle['position'],(365300,544000,260300))
            self.assertEqual(vehicle['flight_phase'],2)
            self.assertIn(uid,state.ropes.values())
            self.assertGreater(codes.count(0x6575),300)
            self.assertTrue(state.handle(0x6541,struct.pack('>QI',uid,1))[0])

    def test_evacuation_region_remains_safe_after_helicopter_arrival(self):
        import struct
        from world_probe_2022 import WorldFixture, WorldState
        from region_index_2022 import FastRegionIndex
        world_config=json.loads((ROOT/'config/world.json').read_text())
        refuge=world_config['evacuation_refuge']
        # Ресурс lookup проверяется отдельно; здесь регрессия согласования расписаний.
        grid=FastRegionIndex(tuple(struct.pack('<HH',24,8191) for _ in range(8192)))
        with tempfile.TemporaryDirectory() as folder:
            configs=launcher.materialize(Path(folder),'snowboard')
            scene=json.loads(configs['scene-cycle'].read_text())
            arrivals=[]
            for rule in scene:
                for response in rule['responses']:
                    if response['command']!='0x654b':continue
                    body=Path(response['payload_file']).read_bytes()
                    if len(body)==104 and struct.unpack_from('>I',body,8)[0]==6:
                        self.assertEqual(list(struct.unpack_from('>iii',body,20))[:2],refuge['position'][:2])
                        arrivals.append(rule['after_selection_delay_seconds'])
            self.assertEqual(len(arrivals),1)
            with patch('world_probe_2022.FastRegionIndex.load',return_value=grid):
                fixture=WorldFixture.load(configs['world'])
            state=WorldState(fixture,42,0)
            state.position=tuple(refuge['position'])
            for now in (0,60.3,90.3,114.3,arrivals[0],135.3,189.3,220,2400):
                state.poll(now)
                self.assertNotIn(refuge['region_id'],state.closed)
                self.assertFalse(state.zone_inside)
                self.assertEqual(state.hp,fixture.hp)
            self.assertIn(4,state.closed)
            self.assertEqual(state.closed,set(range(1,65))-{24})

    def test_native_airdrop_materializes_catalog_and_notice_without_launch(self):
        from parcel_catalog_2022 import load_parcel_fixture
        import struct
        with tempfile.TemporaryDirectory() as temp:
            configs=launcher.materialize(Path(temp),'snowboard',native_airdrop=True)
            weapon=WeaponFixture.load(configs['weapon-snowboard'])
            fixture=load_parcel_fixture(configs['parcel'],weapon)
            self.assertTrue(fixture.containers[0].native_motion)
            self.assertEqual(fixture.containers[0].position[2],301000)
            scene=json.loads(configs['scene-walk'].read_text())
            drop=[r for r in scene if any(x['command']=='0x6571' for x in r['responses'])]
            self.assertEqual(len(drop),1)
            self.assertEqual(sum(x['command']=='0x4a6' for x in drop[0]['responses']),1)
            notice=next(x for x in drop[0]['responses'] if x['command']=='0x4a6')
            self.assertEqual(struct.unpack_from('>3i',bytes.fromhex(notice['payload_hex'])),fixture.containers[0].position)

    def test_temperature_profile_changes_signed_attribute_without_changing_epoch(self):
        import struct
        for raw in (-5000, -2000, 0, 500):
            with self.subTest(raw=raw), tempfile.TemporaryDirectory() as folder:
                config = launcher.materialize(Path(folder), 'snowboard', temperature_raw=raw)
                env = EnvironmentFixture.load(config['environment'])
                packets = dict(env.messages(1791672000))
                self.assertEqual(struct.unpack('>II', packets[0x4816]), (8, 1791672000))
                self.assertEqual(struct.unpack('>Ii', packets[0x10d0]), (5, raw))
        for invalid in (True, -5001, 501, 0.0, '0'):
            with self.subTest(invalid=invalid), tempfile.TemporaryDirectory() as folder:
                with self.assertRaises(ValueError):
                    launcher.materialize(Path(folder), 'snowboard', temperature_raw=invalid)
                self.assertEqual(list(Path(folder).iterdir()), [])

    def test_start_hour_preserves_unix_clock_and_signed_temperature(self):
        import struct
        before = (ROOT / 'config/environment.json').read_bytes()
        for hour in (7, 8, 15, 16):
            with self.subTest(hour=hour), tempfile.TemporaryDirectory() as folder:
                config = launcher.materialize(Path(folder), 'snowboard', start_hour=hour)
                env = EnvironmentFixture.load(config['environment'])
                packets = dict(env.messages(1791672000))
                self.assertEqual(struct.unpack('>II', packets[0x4816]), (hour, 1791672000))
                self.assertEqual(struct.unpack('>Ii', packets[0x10d0]), (5, 500))
                self.assertEqual(len(WeaponFixture.load(config['weapon-snowboard']).all_loot), 19)
        self.assertEqual((ROOT / 'config/environment.json').read_bytes(), before)

    def test_invalid_map_start_hour_fails_before_materialization(self):
        for hour in (True, 0, 6, 17, 23, 24, 7.0, '8'):
            with self.subTest(hour=hour), tempfile.TemporaryDirectory() as folder:
                with self.assertRaises(ValueError):
                    launcher.materialize(Path(folder), 'snowboard', start_hour=hour)
                self.assertEqual(list(Path(folder).iterdir()), [])

    def test_grenade_actions_materialize_with_explicit_diagnostic_damage(self):
        for damage in (0,100,1000):
            with self.subTest(damage=damage), tempfile.TemporaryDirectory() as folder:
                configs=launcher.materialize(Path(folder),'snowboard',frag_damage=damage)
                fixture=WeaponFixture.load(configs['weapon-snowboard'])
                self.assertTrue(fixture.throwable_actions)
                self.assertEqual(fixture.diagnostic_frag_damage,damage)
                grenades={loot.definition:loot.quantity for loot in fixture.all_loot
                          if loot.definition in (50001,50002,50003)}
                self.assertEqual(grenades,{50001:2,50002:2,50003:2})
        for damage in (-1,1001,True,1.5):
            with tempfile.TemporaryDirectory() as folder:
                with self.assertRaises(ValueError):
                    launcher.materialize(Path(folder),'snowboard',frag_damage=damage)

    def test_movement_validation_materializes_only_as_explicit_profile(self):
        from world_probe_2022 import WorldFixture
        for enabled in (False, True):
            with self.subTest(enabled=enabled), tempfile.TemporaryDirectory() as folder:
                configs = launcher.materialize(Path(folder), 'snowboard', validate_movement=enabled)
                from region_index_2022 import FastRegionIndex
                with patch('world_probe_2022.FastRegionIndex.load',
                           return_value=FastRegionIndex((b'\x00\x00\xfe\x1f',))):
                    fixture = WorldFixture.load(configs['world'])
                self.assertEqual(fixture.movement_limits is not None, enabled)
                self.assertTrue(fixture.zero_region_is_frozen)
                if enabled:
                    self.assertEqual((fixture.movement_limits.horizontal_speed,
                                      fixture.movement_limits.vertical_speed,
                                      fixture.movement_limits.burst_seconds), (5000,20000,2))

    def test_own_combat_armor_profile_is_explicit_and_does_not_change_primary_maximum(self):
        for percent in (0, 50, 100):
            with self.subTest(percent=percent), tempfile.TemporaryDirectory() as folder:
                configs = launcher.materialize(Path(folder), 'snowboard', own_armor_absorb_percent=percent)
                fixture = WeaponFixture.load(configs['weapon-snowboard'])
                self.assertEqual(fixture.combat_armor_absorb_percent, percent)
                self.assertIn(201001, fixture.starting_equipment)
                from weapon_probe_2022 import WeaponState
                state = WeaponState(fixture, 42)
                self.assertEqual(state.equipment_durability[12], 2000)
        for invalid in (True, -1, 101, 50.5):
            with self.subTest(invalid=invalid), tempfile.TemporaryDirectory() as folder:
                with self.assertRaises(ValueError):
                    launcher.materialize(Path(folder), 'snowboard', own_armor_absorb_percent=invalid)
                self.assertEqual(list(Path(folder).iterdir()), [])

    def test_death_profile_is_opt_in_and_has_no_hp_floor(self):
        from world_probe_2022 import WorldFixture, WorldState
        for enabled in (False, True):
            with self.subTest(enabled=enabled), tempfile.TemporaryDirectory() as folder:
                configs = launcher.materialize(Path(folder), 'snowboard', death_on_zero=enabled)
                # Ресурс карты извлекается только при игровом запуске.
                from region_index_2022 import FastRegionIndex
                with patch('world_probe_2022.FastRegionIndex.load',
                           return_value=FastRegionIndex((b'\x00\x00\xfe\x1f',))):
                    fixture = WorldFixture.load(configs['world'])
                world = WorldState(fixture, 42, 0)
                world.hp = 0
                self.assertEqual(world.dead, enabled)
                self.assertEqual(fixture.hp_floor, 0 if enabled else 100)
                self.assertEqual(world.poll_death()[0], [world.death_message()] if enabled else [])

    def test_custom_catalog_snapshot_validates_and_remains_independent(self):
        from loot_catalog_2022 import LootCatalog
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            run = base/'run'; run.mkdir()
            source = base/'loot.json'
            row = dict(index=180000, entity_uid=1800000, item_id=30003,
                       quantity=30, position=[365100,544000,259109])
            source.write_text(json.dumps(dict(entities=[row])),encoding='utf-8-sig')
            config = launcher.materialize(run,'snowboard',loot_catalog=source)
            snapshot = config['custom-loot-catalog']
            self.assertEqual(snapshot.read_bytes(), source.read_bytes())
            source.write_text('{}')
            fixture = WeaponFixture.load(config['weapon-snowboard'])
            catalog = LootCatalog.load(snapshot, fixture.all_loot[0].entity)
            self.assertEqual((catalog.items[0].definition,catalog.items[0].quantity),(30003,30))
            catalog.validate_fixture(fixture)
        for invalid in (dict(row,item_id=999999), dict(row,index=fixture.all_loot[0].index)):
            with self.subTest(invalid=invalid), tempfile.TemporaryDirectory() as folder:
                base = Path(folder); run = base/'run'; run.mkdir()
                source = base/'loot.json'; source.write_text(json.dumps(dict(entities=[invalid])))
                with self.assertRaises(ValueError):
                    launcher.materialize(run,'snowboard',loot_catalog=source)

    def test_diagnostic_pool61_resolves_all_supported_definitions(self):
        from loot_catalog_2022 import LootCatalog
        with tempfile.TemporaryDirectory() as folder:
            config=launcher.materialize(Path(folder),'climb',loot_catalog=ROOT/'config/loot-pool61.json')
            fixture=WeaponFixture.load(config['weapon-climb'])
            catalog=LootCatalog.load(config['custom-loot-catalog'],fixture.all_loot[0].entity)
            self.assertEqual(len(catalog.items),61)
            self.assertEqual(len({item.definition for item in catalog.items}),61)
            catalog.validate_fixture(fixture)

    def test_target_los_profiles_validate_geometry_and_preserve_training_balance(self):
        import struct
        from actor_probe_2022 import ActorFixture, ActorState
        for mode in ('off','open','blocked'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as folder:
                configs = launcher.materialize(Path(folder),'snowboard',weapon_profile='m4',target_los=mode)
                actor = ActorState(ActorFixture.load(configs['target-armored']))
                actor.begin(1)
                impact = (*actor.position[:2], actor.position[2]+100)
                origin = (365140,543930,259250)
                actor.note_fire(struct.pack('>6fIBIIfII',*origin,*impact,1,0,100,0,0,0,0),{'action':'fire'})
                hit = bytearray(106)
                struct.pack_into('>Q',hit,4,actor.fixture.uid)
                struct.pack_into('>3f',hit,25,*origin)
                struct.pack_into('>3i',hit,37,*actor.position)
                struct.pack_into('>3f',hit,50,*impact)
                struct.pack_into('>I',hit,88,1);struct.pack_into('>I',hit,96,100)
                _, event = actor.hit(hit)
                if mode == 'blocked':
                    self.assertEqual((event['reason'],actor.hp,actor.armor_durability),('line_of_sight',1000,300))
                else:
                    self.assertEqual((event['action'],actor.hp,actor.armor_durability),('hit_damage',950,250))
                self.assertEqual(actor.fixture.collision_boxes is None,mode=='off')

    def test_additional_families_materialize_matching_ammunition_and_pistol_slot(self):
        from weapon_probe_2022 import WeaponState, GUN_PROFILES
        import struct
        for profile, definition in [('ak47',10202),('r700',10101),('mosin',10102),('usp45',20001)]:
            with self.subTest(profile=profile), tempfile.TemporaryDirectory() as folder:
                configs = launcher.materialize(Path(folder), 'snowboard', weapon_profile=profile)
                fixture = WeaponFixture.load(configs['weapon-snowboard'])
                self.assertTrue(fixture.handgun_slot)
                self.assertFalse(fixture.gun_on_start)
                gun = next(item for item in fixture.all_loot if item.definition == definition)
                ammo_definition, capacity = GUN_PROFILES[definition]
                ammo = next(item for item in fixture.all_loot if item.definition == ammo_definition)
                state = WeaponState(fixture, 42)
                for item in (ammo, gun):
                    state.available_loot.add(item.entity_uid)
                    request = struct.pack('>IIQBHB3iB', item.index, 0, 0, 0, 0, 1, *item.position, 0)
                    state.handle(0x3b63, request)
                slot = 3 if profile == 'usp45' else 1
                state.handle(0x49e, struct.pack('>I',slot))
                state.handle(0x49c, struct.pack('>I',slot), now=10)
                state.poll(20)
                self.assertEqual((state.guns[slot].definition,state.clip,
                                  state.ammunition_quantity(ammo_definition)),
                                 (definition,capacity,ammo.quantity-capacity))

    def test_targets_and_two_slots_materialize_with_explicit_training_balance(self):
        from actor_probe_2022 import ActorFixture, ActorState
        import struct
        with tempfile.TemporaryDirectory() as folder:
            configs = launcher.materialize(Path(folder), 'snowboard', weapon_profile='m4')
            weapon = WeaponFixture.load(configs['weapon-snowboard'])
            self.assertEqual((weapon.weapon_slots, weapon.reload_update, weapon.timed_reload), (3,'delta',True))
            self.assertEqual(weapon.inventory_update, 'delta')
            from winter_selection_2022 import selected_fixture
            from weapon_probe_2022 import WeaponState
            starter = WeaponState(selected_fixture(weapon, 2), 42)
            self.assertEqual((starter.guns[1].definition, starter.clip,
                              starter.ammunition_quantity(30006)), (20003, 7, 10))
            self.assertEqual(starter.reserve, 0)
            self.assertEqual(starter.medical, {70001: 5})
            plain = ActorFixture.load(configs['target-plain'])
            armored = ActorFixture.load(configs['target-armored'])
            self.assertEqual((plain.speed, plain.attack, plain.equipment, plain.armor_definition), (0,None,b'',0))
            actor = ActorState(armored)
            actor.begin(1)
            body = actor.armor_sync()[1]
            self.assertEqual((len(body), struct.unpack_from('>I',body,24)[0],
                             struct.unpack_from('>I',body,65)[0]), (82,12,300))
            fire = struct.pack('>6fIBIIfII',365140,543930,259250,*armored.position,1,0,100,0,0,0,0)
            actor.note_fire(fire, {'action':'fire'})
            hit = bytearray(106)
            struct.pack_into('>Q',hit,4,armored.uid)
            struct.pack_into('>3i',hit,37,*armored.position)
            struct.pack_into('>I',hit,88,1);struct.pack_into('>I',hit,96,100)
            packets, event = actor.hit(hit)
            self.assertEqual((event['hp'],event['absorbed'],event['armor_durability']), (950,50,250))
            self.assertEqual(struct.unpack_from('>I',dict(packets)[0x547],65)[0],250)
            actor.hit(hit)
            self.assertEqual((actor.hp,actor.armor_durability), (950,250))

    def test_m4_profile_preserves_verified_positions_and_indexes(self):
        with tempfile.TemporaryDirectory(prefix='roe m4 ') as folder:
            root = Path(folder);a=root/'default';b=root/'m4';a.mkdir();b.mkdir()
            default = launcher.materialize(a, 'snowboard')
            optional = launcher.materialize(b, 'snowboard', weapon_profile='m4')
            old = WeaponFixture.load(default['weapon-snowboard'])
            new = WeaponFixture.load(optional['weapon-snowboard'])
            self.assertFalse(new.gun_on_start)
            self.assertEqual([(x.index,x.entity_uid,x.position) for x in old.all_loot],
                             [(x.index,x.entity_uid,x.position) for x in new.all_loot])
            self.assertEqual(sorted((x.definition,x.quantity) for x in new.all_loot
                                     if x.definition in (10201,30001)), [(10201,1),(30001,50)])
            self.assertEqual((new.reserve,new.starting_equipment), (6,old.starting_equipment))
            self.assertTrue(old.gun_on_start)
            definitions = {item.index: item.definition for item in new.all_loot}
            for name in ('scene-walk','scene-cycle'):
                found = {}
                for rule in json.loads(optional[name].read_text()):
                    for reply in rule.get('responses', []):
                        if reply.get('command') != '0x821' or 'payload_file' not in reply:
                            continue
                        body = Path(reply['payload_file']).read_bytes()
                        if len(body) == 100:
                            import struct
                            found[struct.unpack_from('>I',body,71)[0]] = struct.unpack_from('>I',body,63)[0]
                self.assertEqual(found, definitions)

    def test_all_three_presets_and_scene_relocate_outside_workspace(self):
        for kit,pack in [('snowboard',200906),('glider',200907),('climb',200904)]:
            with tempfile.TemporaryDirectory(prefix='roe kit ') as folder:
                config=launcher.materialize(Path(folder),kit)
                fixture=WeaponFixture.load(config['weapon-'+kit])
                self.assertEqual(fixture.starting_equipment,(pack,201001,200101))
                self.assertTrue(fixture.gun_on_start)
                self.assertEqual(len(fixture.all_loot),19)
                self.assertEqual(sorted((item.definition,item.quantity) for item in fixture.all_loot
                                        if item.definition in (70001,70002,70003)),
                                 [(70001,5),(70002,1),(70003,1)])
                self.assertEqual(sorted(item.definition for item in fixture.all_loot
                                        if item.definition in (40305,40103,40101,40403)), [40101,40103,40305,40403])
                self.assertEqual(fixture.reserve,6)
                for mode in ('walk','cycle'):self.assertGreater(len(load_scene_rules(config['scene-'+mode])),3)
                room=Path(json.loads(config['room'].read_text())['room_file'])
                self.assertTrue(decode_enter_room_response(room.read_bytes())['fields'])
                catalog=LocalCosmetics(config['cosmetics'])
                self.assertEqual(tuple(map(len,[catalog.ids,catalog.characters,catalog.accessories,catalog.clothes])),(450,361,197,189))
                self.assertNotIn('/home/jovyan',config['scene-walk'].read_text())

    def test_tampered_fixture_rejected_before_use(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'config').mkdir();(root/'run').mkdir()
            (root/'config/wire.json').write_text(json.dumps({'0'*64:{'hex':'01','size':1}}))
            with patch.object(launcher,'ROOT',root),self.assertRaisesRegex(ValueError,'Повреждён'):
                launcher.materialize(root/'run','snowboard')

    def test_in_place_client_uses_same_files_without_copy_or_backup(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'game';run=root/'run';source.mkdir();run.mkdir()
            for name in launcher.REQUIRED:
                p=source/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'test resource')
            (source/'UserData').mkdir();(source/'UserData/player.txt').write_bytes(b'user settings')
            before={str(p.relative_to(source)):(p.read_bytes(),p.stat().st_mtime_ns)
                    for p in source.rglob('*') if p.is_file()}
            expected=hashlib.sha256(b'test resource').hexdigest()
            with patch.object(launcher,'EXPECTED_SHA',expected), patch.object(launcher.shutil,'copy2',side_effect=AssertionError('copy forbidden')), patch.object(launcher.shutil,'disk_usage',side_effect=AssertionError('no space for client copy')):
                selected=launcher.prepare_client_in_place(source,run)
            self.assertEqual(selected,source.resolve())
            after={str(p.relative_to(source)):(p.read_bytes(),p.stat().st_mtime_ns)
                   for p in source.rglob('*') if p.is_file()}
            self.assertEqual(before,after)
            manifest=json.loads((run/'client-files-before.json').read_text())
            self.assertEqual(manifest['mode'],'in_place')
            self.assertEqual(len(manifest['critical']),3)
            self.assertFalse((root/'runtime/client').exists())

    def test_in_place_rejects_wrong_build_without_touching_client(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'game';run=root/'run';source.mkdir();run.mkdir()
            for name in launcher.REQUIRED:
                p=source/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'wrong build')
            with self.assertRaisesRegex(ValueError,'другого билда'):
                launcher.prepare_client_in_place(source,run)
            self.assertFalse(list(run.iterdir()))
            self.assertEqual((source/'Europa_Client.exe').read_bytes(),b'wrong build')

    def test_occupied_port_is_not_consumed(self):
        with socket.socket() as owner:
            owner.bind(('127.0.0.1',0));owner.listen();owner.settimeout(.1)
            with self.assertRaisesRegex(ValueError,'занят'):
                launcher.check_ports([(owner.getsockname()[1],socket.SOCK_STREAM)])
            with self.assertRaises(socket.timeout):owner.accept()

    def test_account_catalog_never_contains_key_or_linux_path(self):
        config=json.loads((ROOT/'config/cosmetics.json').read_text())
        self.assertEqual(config['state_file'],'@account')
        self.assertFalse(any('key' in name.lower() or 'token' in name.lower() for name in config))


if __name__=='__main__':unittest.main()
