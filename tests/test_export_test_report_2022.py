"""Выгрузка отчёта не должна забирать AUTH, ключи или произвольный TSV."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from export_test_report_2022 import export_report


class ExportReportTests(unittest.TestCase):
    def test_terrain_los_export_keeps_numeric_evidence_without_resource_or_auth(self):
        with tempfile.TemporaryDirectory() as folder:
            run=Path(folder)/'run';(run/'scene').mkdir(parents=True)
            (run/'launch-summary.json').write_text(json.dumps(dict(build='2022-test',source_hashes={
                'tools/probe_iceland_heightfield_2022.py':'a'*64})))
            row=dict(kind='actor_probe',action='hit_rejected',reason='line_of_sight',terrain_checked=True,
                     blocking_terrain=dict(fraction=.5,position=[1,2,3],normal=[0,0,1],
                     face_index=123,material_index=42,visited_cells=3,terrain_only=True,
                     source_file='must-not-copy',samples='must-not-copy',auth='must-not-copy'))
            (run/'scene/events.jsonl').write_text(json.dumps(row)+'\n')
            out=Path(folder)/'report';export_report(run,out)
            text=(out/'scene/events.jsonl').read_text();actual=json.loads(text)
            self.assertEqual(actual['blocking_terrain']['face_index'],123)
            self.assertEqual(actual['blocking_terrain']['position'],[1,2,3])
            self.assertTrue(actual['terrain_checked'])
            self.assertNotIn('must-not-copy',text)
            summary=json.loads((out/'launch-summary.json').read_text())
            self.assertEqual(summary['source_hashes'],{'tools/probe_iceland_heightfield_2022.py':'a'*64})

    def test_death_owners_and_typed_action_are_exported_without_nested_secrets(self):
        with tempfile.TemporaryDirectory() as folder:
            run = Path(folder) / 'run'
            (run / 'scene').mkdir(parents=True)
            (run / 'launch-summary.json').write_text('{"build":"2022-test"}')
            corpse = dict(action='death_inventory_transferred', owner='0x123',
                          parcel_id=450100, items=[dict(definition=30004, quantity=6,
                          durability=0, identity='must-not-copy')], auth='must-not-copy')
            rows = [dict(kind='death_parcel_probe', **corpse),
                    dict(kind='live_state_action', id='one', action='damage_npc',
                         accepted=True, administrative=True, corpse=corpse, key='must-not-copy')]
            (run / 'scene/events.jsonl').write_text('\n'.join(map(json.dumps, rows)) + '\n')
            out = Path(folder) / 'report'
            export_report(run, out)
            text = (out / 'scene/events.jsonl').read_text()
            actual = list(map(json.loads, text.splitlines()))
            self.assertEqual(actual[0]['owner'], '0x123')
            self.assertEqual(actual[1]['corpse']['items'], [dict(definition=30004, quantity=6, durability=0)])
            self.assertTrue(actual[1]['accepted'])
            self.assertNotIn('must-not-copy', text)

    def test_passive_targets_and_handoff_health_survive_filtered_export(self):
        with tempfile.TemporaryDirectory() as folder:
            run = Path(folder) / 'run'
            (run / 'scene').mkdir(parents=True)
            (run / 'launch-summary.json').write_text(json.dumps(dict(build='2022-test', practice_targets=10)))
            event = dict(kind='gameplay_handoff_complete', target_count=10,
                         target_states=[dict(uid='0x123', hp=400, armor_durability=0,
                                             auth='must-not-copy')], raw='must-not-copy')
            (run / 'scene/events.jsonl').write_text(json.dumps(event) + '\n')
            out = Path(folder) / 'report'
            export_report(run, out)
            summary = json.loads((out / 'launch-summary.json').read_text())
            actual = json.loads((out / 'scene/events.jsonl').read_text())
            self.assertEqual(summary['practice_targets'], 10)
            self.assertEqual(actual['target_count'], 10)
            self.assertEqual(actual['target_states'], [dict(uid='0x123', hp=400, armor_durability=0)])
            self.assertNotIn('must-not-copy', (out / 'scene/events.jsonl').read_text())

    def test_loot_visibility_export_preserves_spawn_remove_without_raw_or_paths(self):
        with tempfile.TemporaryDirectory() as folder:
            run = Path(folder) / 'run'
            (run / 'scene').mkdir(parents=True)
            (run / 'launch-summary.json').write_text(json.dumps(dict(build='2022-test',
                loot_catalog_sha256='b'*64, loot_catalog_items=8,
                loot_catalog_radius_cm=2000, loot_catalog_bounds_cm=[1, 2, 3, 4, 5, 6])))
            rows = [dict(kind='loot_catalog_ready', count=8, radius_cm=2000,
                         source_file='must-not-copy', raw='must-not-copy'),
                    dict(kind='loot_catalog_probe', action='catalog_visibility',
                         spawned=2, removed=0, visible=2, spawned_indexes=[190500, 190501],
                         removed_indexes=[], catalog_total=8, original_aoi_verified=False,
                         auth='must-not-copy'),
                    dict(kind='loot_catalog_probe', action='catalog_visibility',
                         spawned=0, removed=1, visible=1, spawned_indexes=[],
                         removed_indexes=[190500], catalog_total=8)]
            (run / 'scene/events.jsonl').write_text('\n'.join(map(json.dumps, rows)) + '\n')
            out = Path(folder) / 'report'
            receipt = export_report(run, out)
            text = (out / 'scene/events.jsonl').read_text()
            exported = list(map(json.loads, text.splitlines()))
            self.assertEqual(receipt['gameplay_events'], 3)
            self.assertEqual(exported[0]['count'], 8)
            self.assertEqual(exported[1]['spawned_indexes'], [190500, 190501])
            self.assertEqual(exported[2]['removed_indexes'], [190500])
            self.assertFalse(exported[1]['original_aoi_verified'])
            self.assertNotIn('must-not-copy', text)
            summary = json.loads((out / 'launch-summary.json').read_text())
            self.assertEqual(summary['loot_catalog_sha256'], 'b'*64)
            self.assertEqual(summary['loot_catalog_items'], 8)
            self.assertEqual(summary['loot_catalog_bounds_cm'], [1, 2, 3, 4, 5, 6])

    def test_extended_hit_records_remain_diagnostic_without_nested_raw_data(self):
        with tempfile.TemporaryDirectory() as folder:
            run=Path(folder)/'run';(run/'scene').mkdir(parents=True)
            (run/'launch-summary.json').write_text('{"build":"2022-test"}')
            hit=dict(kind='actor_probe',action='hit_damage',hp=800,
                     collision_record_count=2,hit_feedback_command='0x11eb',
                     penetration=dict(material_id=305,energy_after=27.2,
                                      source_faces=[2066,2065],original_server_policy=False,
                                      raw='must-not-copy'),
                     collision_records=[dict(kind=0,material_id=305,point=[1,2,3],
                                             opaque_u8_1=0,opaque_u8_2=1,raw='must-not-copy'),
                                        dict(kind=1,unit_uid='0x123',part_id=2,auth='must-not-copy')])
            (run/'scene/events.jsonl').write_text(json.dumps(hit)+'\n')
            out=Path(folder)/'report';export_report(run,out)
            text=(out/'scene/events.jsonl').read_text();row=json.loads(text)
            self.assertEqual((row['hp'],row['collision_record_count'],row['hit_feedback_command']),
                             (800,2,'0x11eb'))
            self.assertEqual(row['collision_records'][0]['material_id'],305)
            self.assertEqual(row['collision_records'][1],dict(kind=1,unit_uid='0x123',part_id=2))
            self.assertEqual(row['penetration'], dict(material_id=305,energy_after=27.2,
                source_faces=[2066,2065],original_server_policy=False))
            self.assertNotIn('must-not-copy',text)

    def test_export_includes_gameplay_and_numeric_state_without_network_or_identity(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder);run=base/'run';(run/'scene').mkdir(parents=True)
            (run/'launch-summary.json').write_text(json.dumps(dict(
                build='2022-0.2.989.0-x64',launcher_revision='test',weapon_slots=3,
                token='must-not-copy',remote_peer='must-not-copy',source_hashes={
                    'tools/windows_launch.py':'a'*64,'private/key':'must-not-copy'})))
            rows=[dict(kind='plaintext',command='0x2001',raw='session.key',identity='must-not-copy'),
                  dict(kind='world_probe',action='hazard_damage',hp=950,position=[1,2,3],raw='must-not-copy'),
                  dict(kind='vehicle_probe',action='singleplayer_evacuation_finish',
                       match_statistics=dict(rescued=1,kills=1,token='must-not-copy'))]
            (run/'scene/events.jsonl').write_text('\n'.join(json.dumps(r) for r in rows)+'\n{unfinished')
            (run/'client-state.tsv').write_text('snapshot\t1\nmagazine_slot1\t17\ntoken\tmust-not-copy\nreserve_glock\tNaN\nreserve_m4\tunavailable\n')
            destination=base/'report';receipt=export_report(run,destination)
            self.assertEqual(receipt['gameplay_events'],2)
            self.assertFalse(receipt['native_platform_verified_by_exporter'])
            text=''.join(p.read_text() for p in destination.rglob('*') if p.is_file())
            self.assertNotIn('must-not-copy',text)
            self.assertNotIn('session.key',text)
            self.assertEqual(json.loads((destination/'scene/events.jsonl').read_text().splitlines()[1])['match_statistics'],dict(rescued=1,kills=1))
            self.assertEqual((destination/'client-state.tsv').read_text(), 'snapshot\t1\nmagazine_slot1\t17\nreserve_m4\tunavailable\n')
            with self.assertRaises(ValueError):export_report(run,destination)

    def test_missing_or_non2022_summary_rejected_without_output(self):
        with tempfile.TemporaryDirectory() as folder:
            run=Path(folder);out=run/'out';(run/'scene').mkdir()
            (run/'scene/events.jsonl').write_text('')
            (run/'launch-summary.json').write_text('{"build":"v99"}')
            with self.assertRaises(ValueError):export_report(run,out)
            self.assertFalse(out.exists())
