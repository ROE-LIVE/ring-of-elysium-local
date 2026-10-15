"""Опасный участок: реальное время, выход и независимость игровых сеансов."""
import struct,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server/directory'))
from world_probe_2022 import WorldFixture, WorldState, RegionGrid, encode_shrink, encode_shrink_warning

class WorldTests(unittest.TestCase):
    def test_disabled_training_rectangle_never_damages_safe_final_area(self):
        from dataclasses import replace
        fixture = replace(self.fixture(), hazard_enabled=False)
        state = WorldState(fixture, 1, 0)
        state.poll(0)
        self.assertIsNone(state.update_position((15,25,0), 1))
        _, events = state.poll(100)
        self.assertEqual(state.hp, 1000)
        self.assertFalse(state.inside)
        self.assertFalse(any(e['action'] == 'hazard_damage' for e in events))

    def test_active_warning_uses_remaining_duration_on_late_join_and_resume(self):
        from dataclasses import replace
        fixture = replace(self.fixture(), warnings=((15, 60, encode_shrink_warning(60)),))
        late = WorldState(fixture, 2, 120)
        late.align_clock(100, 120)
        packets, events = late.poll(120)
        warnings = [body for command, body in packets if command == 0x481
                    and struct.unpack_from('>I', body)[0] == 1]
        self.assertEqual(len(warnings), 1)
        self.assertEqual(struct.unpack_from('>I', warnings[0], 8)[0], 55)
        self.assertEqual([event['action'] for event in events].count('zone_warning_late'), 1)
        self.assertIsNone(late.warning_snapshot(175))
        self.assertEqual(late.warning_snapshot(130)[1]['remaining_seconds'], 45)
        self.assertFalse(any(event['action'] == 'zone_warning_late'
                             for event in late.poll(121)[1]))
        # Более поздняя стадия перекрывает старое предупреждение.
        superseded = replace(fixture, stages=fixture.stages +
                             ((30, 40, encode_shrink(30, 40, [], [4])),))
        other = WorldState(superseded, 3, 140)
        other.align_clock(100, 140)
        _, events = other.poll(140)
        self.assertIsNone(other.warning_snapshot(140))
        self.assertNotIn('zone_warning_late', [event['action'] for event in events])
        crossing = replace(fixture, warnings=fixture.warnings +
                           ((20, 30, encode_shrink_warning(30)),))
        boundary = WorldState(crossing, 4, 119.99)
        boundary.align_clock(100, 119.99)
        packets, events = boundary.poll(120.01)
        self.assertEqual([event['action'] for event in events].count('zone_warning'), 1)
        self.assertNotIn('zone_warning_late', [event['action'] for event in events])
        self.assertEqual(sum(command == 0x481 and struct.unpack_from('>I', body)[0] == 1
                             for command, body in packets), 1)

    def test_late_join_uses_current_stage_without_expired_warning_or_hp_catchup(self):
        from dataclasses import replace
        fixture = replace(self.fixture(), region_grid=RegionGrid(bytes(1024*1024*4)),
                          stage_safe=(frozenset({4, 24}), frozenset({4})),
                          warnings=((5, 5, encode_shrink_warning(5)),
                                    (25, 5, encode_shrink_warning(5))))
        late = WorldState(fixture, 2, 116)
        late.align_clock(100, 116)
        self.assertIn(1, late.closed)
        self.assertNotIn(24, late.closed)
        late.update_position((15, 25, 0), 116)
        packets, events = late.poll(116)
        self.assertEqual([code for code, _ in packets], [0x1069, 0x481])
        stages = [event for event in events if event['action'] == 'zone_stage']
        self.assertEqual([event['stage'] for event in stages], [10])
        self.assertEqual(stages[0]['stage_elapsed_sent'], 6)
        self.assertIn(24, late.closed)
        self.assertEqual(late.hp, 1000)
        late.poll(117); self.assertEqual(late.hp, 950)
        _, events = late.poll(125)
        self.assertEqual([e['action'] for e in events].count('zone_warning'), 1)

    def test_clock_alignment_rejects_invalid_or_initialized_clock(self):
        state = WorldState(self.fixture(), 1, 100)
        for started, now in [(True,100),(-1,100),(101,100),(0,float('nan')),(float('inf'),100)]:
            with self.assertRaises(ValueError): state.align_clock(started, now)
        state.poll(100)
        with self.assertRaises(ValueError): state.align_clock(0, 100)

    def test_fully_absorbed_combat_damage_preserves_hp_without_death(self):
        from dataclasses import replace
        world = WorldState(replace(self.fixture(), hp=50, hp_floor=0, death_on_zero=True), 42, 0)
        packets, event = world.apply_damage(0, 43)
        self.assertEqual((world.hp, world.dead, event['damage']), (50, False, 0))
        self.assertEqual([code for code, _ in packets], [0x1069])
        for invalid in (True, -1, 101, .5):
            with self.assertRaises(ValueError): world.apply_damage(invalid, 43)
        self.assertEqual(world.hp, 50)

    def fixture(self):
        return WorldFixture(1000,100,(10,20,30,40),50,1,((0,1,encode_shrink(30,1,[4],[4])),(10,10,encode_shrink(30,10,[],[4]))))

    def test_exposure_stops_outside_and_catches_up_without_frame_dependence(self):
        s=WorldState(self.fixture(),1,100)
        self.assertEqual(len(s.poll(100)[0]),2)
        self.assertEqual(s.update_position((15,25,0),101)['action'],'hazard_enter')
        self.assertEqual(s.poll(101.9)[0],[])
        s.poll(104.2);self.assertEqual(s.hp,850)
        self.assertEqual(s.update_position((31,25,0),104.3)['action'],'hazard_leave')
        s.poll(109);self.assertEqual(s.hp,850)
        self.assertEqual(s.poll(110)[0][0][0],0x481)
        self.assertEqual(s.poll(110)[0],[])

    def test_floor_and_sessions_do_not_share_hp(self):
        a=WorldState(self.fixture(),1,0);b=WorldState(self.fixture(),2,0)
        a.update_position((10,20,0),0);responses,_=a.poll(100)
        self.assertEqual((a.hp,b.hp),(100,1000))
        hp=[data for code,data in responses if code==0x1069][-1]
        self.assertEqual(struct.unpack('>QBBBII',hp),(1,0,1,0,100,1000))
        a.update_position((30,40,0),101);a.poll(102);self.assertEqual(a.hp,100)

    def test_explicit_zero_death_is_once_and_after_health(self):
        from dataclasses import replace
        fixture=replace(self.fixture(),hp=50,hp_floor=0,death_on_zero=True)
        world=WorldState(fixture,42,0)
        world.update_position((15,25,0),0)
        first,_=world.poll(0)
        self.assertFalse(world.dead)
        responses,events=world.poll(1)
        self.assertEqual([c for c,p in responses],[0x1069,0x533])
        self.assertEqual(responses[-1],(0x533,struct.pack('>IQ',0,42)))
        self.assertEqual([e['action'] for e in events],['hazard_damage','own_death'])
        self.assertTrue(world.dead)
        self.assertEqual(world.poll(10)[0][0][0],0x481)
        self.assertFalse(any(c==0x533 for c,p in world.poll(100)[0]))
        # Сохранённое состояние остаётся мёртвым даже при ошибочной записи HP.
        world.hp=50
        self.assertTrue(world.dead)
        diagnostic=WorldState(replace(fixture,death_on_zero=False),43,0)
        diagnostic.update_position((15,25,0),0)
        self.assertFalse(any(c==0x533 for c,p in diagnostic.poll(1)[0]))
        self.assertEqual(diagnostic.hp,0)
        self.assertFalse(diagnostic.dead)

    def test_invalid_regions_rejected_before_wire(self):
        for ids in ([0],[4,4],list(range(1,102)),[True]):
            with self.assertRaises(ValueError):encode_shrink(30,10,ids,[4])

    def test_elapsed_stage_matches_primary_native_packet_and_rejects_invalid_time(self):
        # Первичные 481 из weather-threshold-test: 225 с, стадия длится 420 с.
        body=encode_shrink(420,10,[4],list(range(1,65)),225)
        self.assertEqual(body[:12].hex(),'0000000043610000000001a4')
        self.assertEqual(struct.unpack_from('>I',body,len(body)-4)[0],10)
        for elapsed in (True,-1,3601,float('nan'),float('inf')):
            with self.assertRaises(ValueError):encode_shrink(420,10,[4],[4],elapsed)

    def test_closed_region_damage_waits_for_closure_and_is_conservative_at_border(self):
        data=bytearray(1024*1024*4)
        at=(176*1024+400)*4;data[at:at+4]=bytes([24]*4)
        data[at+4:at+8]=bytes([24,4,24,4])
        grid=RegionGrid(bytes(data))
        self.assertEqual(grid.regions((365100,544000,0)),frozenset({24}))
        self.assertEqual(grid.regions((0,0,0)),frozenset())
        stages=((0,10,encode_shrink(10,10,[4],[4,24])),
                (10,20,encode_shrink(10,20,[4],[4])))
        fixture=WorldFixture(1000,100,(10,20,30,40),50,1,stages,grid,50,
                             (frozenset({4,24}),frozenset({4})))
        state=WorldState(fixture,1,0)
        state.update_position((365100,544000,0),0)
        state.poll(9);self.assertEqual(state.hp,1000)
        _,events=state.poll(10)
        self.assertIn('closed_zone_enter',[e['action'] for e in events])
        state.poll(13);self.assertEqual(state.hp,850)
        state.update_position((365300,544000,0),13)
        state.poll(20);self.assertEqual(state.hp,850)
        self.assertFalse(state.zone_inside)
        state.update_position((365100,544000,0),21);state.poll(21)
        state.poll(30,protected=True);self.assertEqual(state.hp,850)
        state.poll(31);self.assertEqual(state.hp,800)

    def test_warnings_preserve_closure_and_order_when_heartbeat_is_late(self):
        grid=RegionGrid(bytes([24])*(1024*1024*4))
        stages=((0,1,encode_shrink(10,1,[4],[4,24])),
                (10,10,encode_shrink(30,10,[4],[4])))
        warnings=((5,5,encode_shrink_warning(5)), (15,25,encode_shrink_warning(25)))
        fixture=WorldFixture(1000,100,(10,20,30,40),50,1,stages,grid,50,
                            (frozenset(range(1,65)),frozenset({4})),warnings)
        state=WorldState(fixture,1,0)
        state.poll(0)
        self.assertEqual(state.closed,set())
        response,events=state.poll(16)
        self.assertEqual([e['action'] for e in events],['zone_warning','zone_stage','zone_warning'])
        self.assertEqual([struct.unpack_from('>I',p)[0] for _,p in response],[1,0,1])
        self.assertIn(24,state.closed)
        self.assertEqual(state.poll(17),( [], [] ))

    def test_delayed_stages_keep_original_deadlines_and_fixture_bytes(self):
        from dataclasses import replace
        original=encode_shrink(60,10,[4],[4],7)
        fixture=replace(self.fixture(),stages=((90,10,original),))
        state=WorldState(fixture,1,100)
        responses,events=state.poll(201.5)
        sent=[body for opcode,body in responses if opcode==0x481][0]
        self.assertEqual(struct.unpack_from('>f',sent,4)[0],18.5)
        self.assertEqual(sent[:4]+sent[8:],original[:4]+original[8:])
        self.assertEqual(struct.unpack_from('>f',fixture.stages[0][2],4)[0],7)
        event=next(e for e in events if e['action']=='zone_stage')
        self.assertEqual(event['remaining_seconds'],41.5)
        self.assertEqual(event['scheduled_at'],90)
        self.assertEqual(state.poll(202),( [], [] ))
        # Отрицательный контроль отключается только явным параметром пресета.
        control=WorldState(replace(fixture,correct_delayed_stage_elapsed=False),1,100)
        old=[b for code,b in control.poll(201.5)[0] if code==0x481][0]
        self.assertEqual(old,original)

    def test_expired_stage_reports_zero_remaining_and_bounds_elapsed(self):
        state=WorldState(self.fixture(),1,0)
        responses,events=state.poll(10000)
        stages=[(body,event) for (_,body),event in zip(responses[1:],events[1:])]
        self.assertEqual(len(stages),2)
        for body,event in stages:
            self.assertEqual(struct.unpack_from('>f',body,4)[0],3600)
            self.assertEqual(event['remaining_seconds'],0)
        self.assertEqual(state.poll(10001),( [], [] ))

    def test_stage_snapshot_restores_lost_response_without_recreating_world(self):
        state=WorldState(self.fixture(),42,100)
        self.assertIsNone(state.stage_snapshot(101))
        state.poll(111)
        state.hp=750
        state.position=(15,25,0)
        before=(state.started,state.hp,state.position,state.stage_index,set(state.closed))
        body,timing=state.stage_snapshot(117)
        self.assertEqual(struct.unpack_from('>f',body,4)[0],7)
        self.assertEqual(timing['stage'],10)
        self.assertEqual(timing['remaining_seconds'],23)
        self.assertEqual((state.started,state.hp,state.position,state.stage_index,state.closed),before)
        self.assertEqual(state.poll(117),( [], [] ))

    def test_resume_catches_up_stage_without_replaying_superseded_warning(self):
        from dataclasses import replace
        fixture = replace(self.fixture(), warnings=((5, 30, encode_shrink_warning(30)),))
        state = WorldState(fixture, 42, 100)
        state.poll(100)
        state.poll(105)
        self.assertEqual(state.stage_snapshot(112)[1]['stage'], 1)
        self.assertEqual(state.catch_up_zone(112), (1, 0))
        body, timing = state.stage_snapshot(112)
        self.assertEqual(timing['stage'], 10)
        self.assertEqual(timing['stage_elapsed_sent'], 2)
        self.assertIsNone(state.warning_snapshot(112))
        self.assertEqual(state.poll(112), ([], []))

    def test_resource_buff915_has_independent_zone_cadence_and_terminal_death(self):
        from dataclasses import replace
        from region_index_2022 import FastRegionIndex
        rows=[struct.pack('<HH',0,8190)]*8192
        rows[6784]=struct.pack('<HH',24,8190)
        fixture=replace(self.fixture(),hp_floor=0,death_on_zero=True,interval=3,
            region_grid=FastRegionIndex(tuple(rows)),zone_damage=150,zone_interval=1,
            zone_damage_profile='buff915_resource',
            stages=((0,50,encode_shrink(30,50,[],[])),),stage_safe=(frozenset(),))
        state=WorldState(fixture,42,0);state.update_position((365100,544000,0),0)
        state.poll(0)
        self.assertEqual(state.poll(.99),( [], [] ))
        state.poll(1);self.assertEqual(state.hp,850)
        packets,events=state.poll(7)
        self.assertEqual(state.hp,0)
        self.assertEqual([c for c,p in packets],[0x1069,0x533])
        damage=next(e for e in events if e['action']=='closed_zone_damage')
        self.assertEqual((damage['damage_profile'],damage['interval_seconds']),
                         ('buff915_resource',1))
        self.assertEqual(state.poll(10),( [], [] ))

    def test_resource_buff915_rejects_wrong_rate_and_preserves_diagnostic_mode(self):
        import json,tempfile
        from unittest.mock import patch
        config={'hp':1000,'hp_floor':0,'hazard':{'bounds_xy':[0,0,1,1],
            'damage':50,'interval_seconds':3},'region_grid':{'file':'index.bin',
            'lookup':'native_fast','damage':150,'interval_seconds':1,
            'damage_profile':'buff915_resource'},'stages':[]}
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'world.json'
            with patch('world_probe_2022.FastRegionIndex.load',return_value=None):
                path.write_text(json.dumps(config));fixture=WorldFixture.load(path)
                self.assertEqual((fixture.zone_damage,fixture.zone_interval,fixture.interval),
                                 (150,1,3))
                for field,value in [('damage',50),('interval_seconds',2),
                                    ('interval_seconds',True),('damage_profile','original')]:
                    modified=json.loads(json.dumps(config));modified['region_grid'][field]=value
                    path.write_text(json.dumps(modified))
                    with self.assertRaises(ValueError):WorldFixture.load(path)
                config['region_grid']['damage_profile']='diagnostic'
                config['region_grid']['damage']=50
                path.write_text(json.dumps(config));self.assertEqual(WorldFixture.load(path).zone_damage,50)
