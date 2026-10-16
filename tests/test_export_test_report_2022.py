"""Выгрузка отчёта не должна забирать AUTH, ключи или произвольный TSV."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from export_test_report_2022 import export_report


class ExportReportTests(unittest.TestCase):
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
