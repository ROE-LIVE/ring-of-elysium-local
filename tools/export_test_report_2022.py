"""Компактный отчёт Windows2022 без ключей, AUTH и сырых пакетов."""
import argparse
import json
import math
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
KINDS = frozenset(('weapon_probe', 'actor_probe', 'world_probe', 'medical_probe',
                   'parcel_probe', 'vehicle_probe', 'door_probe', 'breakable_probe', 'throwable_probe',
                   'match_statistics', 'winter_kit_initialized', 'winter_selection',
                   'winter_selection_rejected', 'selection_started', 'live_state_action',
                   'gameplay_handoff_complete', 'gameplay_handoff_pending', 'gameplay_resume_reload_reconcile'))
SUMMARY = frozenset(('build', 'map', 'mode', 'kit', 'weapon_profile', 'target',
                     'bots', 'reliable_udp', 'idle_handoff', 'duration', 'verify_only',
                     'world_cycle_enabled', 'cycle_scale', 'diagnostic_hazard_enabled',
                     'death_on_zero', 'winter_doors_enabled', 'winter_windows_enabled',
                     'custom_loot_catalog_enabled', 'launcher_revision', 'weapon_slots',
                     'starter_item_source', 'starter_magazine_policy', 'debug_console',
                     'start_hour', 'temperature_raw', 'native_airdrop', 'native_evacuation',
                     'diagnostic_departure', 'original_account_authentication',
                     'original_starter_inventory', 'local_session_id', 'launcher_platform'))
EVENT = frozenset(('sequence', 'timestamp', 'kind', 'action', 'reason', 'synthetic',
                   'experimental', 'failed_checks', 'slot', 'source', 'destination',
                   'source_slot', 'target_slot', 'requested_slot', 'gun_definition',
                   'definition', 'index', 'quantity', 'amount', 'clip', 'reserve',
                   'ammunition_definition', 'ammunition_quantity', 'counter', 'tick',
                   'instance_uid', 'uid', 'target', 'hp', 'damage', 'absorbed',
                   'armor_durability', 'armor_definition', 'position', 'regions',
                   'stage', 'elapsed', 'scheduled_at', 'lateness_seconds', 'duration',
                   'remaining_seconds', 'stage_elapsed_sent', 'periods', 'damage_profile',
                   'interval_seconds', 'choice', 'kit', 'capacity', 'weapon_slots',
                   'cell_x', 'cell_y', 'selected_cell', 'spawn_position', 'seconds',
                   'update', 'seat', 'configuration', 'rope', 'match_statistics',
                   'survival_seconds', 'distance_cm', 'damage_raw', 'damage_hp',
                   'kills', 'loot_actions', 'loot_quantity', 'rescued',
                   'original_reward_formula', 'distance_policy', 'damage_policy',
                   'cause', 'part_id', 'target_path_id', 'target_path_sequence',
                   'target_path_use_c', 'on_vehicle', 'shooter_path_id',
                   'shooter_path_sequence', 'shooter_path_use_c', 'shoot_id',
                   'bullet_id', 'ratio', 'pellet_index', 'gun_origin', 'target_stand',
                   'hit_impact', 'hit_tag62', 'hit_field71', 'hit_field78',
                   'hit_flag83', 'hit_field100', 'state', 'entity_id',
                   'diagnostic_protection_seconds', 'reload_cancelled', 'amount_healed',
                   'starter_items', 'starter_item_source', 'starter_magazine_policy',
                   'request_kind', 'actor_matches', 'requested_cell', 'request_flag',
                   'inventory_started', 'handoff_mode', 'previous_idle_seconds',
                   'world_position', 'world_hp', 'world_stage_index'))
NUMERIC = frozenset(('snapshot', 'qs_current_map_id_unclassified', 'magazine_slot1',
                     'magazine_slot2', 'magazine_slot3', 'reserve_citori', 'reserve_m4',
                     'reserve_ak47', 'reserve_glock', 'reserve_de', 'bandages',
                     'first_aid', 'medkit', 'glider_kit', 'snowboard_kit', 'climb_kit',
                     'weather_id', 'game_day_fraction', 'body_temperature_raw',
                     'init_equip_type1', 'init_equip_type2', 'init_equip_type3'))


def public_value(value, allowed):
    if value is None or type(value) in (bool, int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, str):
        return value if len(value) <= 256 and not any(ord(c) < 32 for c in value) else None
    if isinstance(value, list):
        return [public_value(v, allowed) for v in value[:128]]
    if isinstance(value, dict):
        return {k: public_value(v, allowed) for k, v in value.items() if k in allowed}
    return None


def export_report(run, destination):
    run, destination = Path(run).resolve(), Path(destination)
    if destination.exists():
        raise ValueError('Каталог отчёта уже существует; выберите новый')
    summary_path, events_path = run/'launch-summary.json', run/'scene/events.jsonl'
    for path in (summary_path, events_path):
        if path.is_symlink() or not path.is_file():
            raise ValueError('Нужны обычные launch-summary.json и scene/events.jsonl')
    if summary_path.stat().st_size > 1024 * 1024:
        raise ValueError('Сводка запуска превышает1МиБ')
    source = json.loads(summary_path.read_text(encoding='utf-8-sig'))
    if not isinstance(source, dict) or not str(source.get('build', '')).startswith('2022'):
        raise ValueError('Нужна сводка запуска клиента2022')
    summary = public_value(source, SUMMARY)
    hashes = source.get('source_hashes', {})
    if not isinstance(hashes,dict):
        raise ValueError('source_hashes должен быть объектом')
    summary['source_hashes'] = {k: v for k, v in hashes.items()
                                if k in ('tools/windows_launch.py', 'server/directory/weapon_probe_2022.py',
                                         'server/directory/winter_selection_2022.py', 'server/directory/world_probe_2022.py',
                                         'server/directory/actor_probe_2022.py', 'tools/match_pacing_2022.py', 'SOURCE-MANIFEST.json')
                                and isinstance(v, str) and re.fullmatch('[0-9a-fA-F]{64}', v)}
    destination.mkdir(parents=True)
    (destination/'scene').mkdir()
    (destination/'launch-summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    count = 0
    with events_path.open(encoding='utf-8-sig') as stream, (destination/'scene/events.jsonl').open('w',encoding='utf-8') as target:
        for line in stream:
            # Незавершённую последнюю строку работающего процесса пропускаем.
            if len(line)>65536:
                continue
            try:
                row=json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row,dict) and row.get('kind') in KINDS:
                target.write(json.dumps(public_value(row,EVENT),ensure_ascii=False)+'\n')
                count+=1
    numeric = run/'client-state.tsv'
    if numeric.is_file() and not numeric.is_symlink() and numeric.stat().st_size <= 8*1024*1024:
        lines=[]
        for line in numeric.read_text(encoding='utf-8-sig').splitlines():
            fields=line.split('\t')
            if len(fields)!=2 or fields[0] not in NUMERIC:
                continue
            try:
                valid=fields[1]=='unavailable' or math.isfinite(float(fields[1]))
            except ValueError:
                valid=False
            if valid:lines.append(line)
        if lines:(destination/'client-state.tsv').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    receipt = dict(run=run.name, gameplay_events=count, raw_network_included=False,
                   keys_included=False, native_platform_verified_by_exporter=False)
    (destination/'export-summary.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return receipt


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',type=Path,help='Каталог runs/ID; по умолчанию последний со scene/events.jsonl')
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    try:
        candidates=sorted((ROOT/'runs').glob('*/launch-summary.json'))
        run=args.run or next((p.parent for p in reversed(candidates) if (p.parent/'scene/events.jsonl').is_file()),None)
        if run is None:raise ValueError('Ещё нет запуска с игровыми событиями')
        output=args.output or ROOT/'reports'/run.name
        if args.output is None:
            suffix=2
            while output.exists():
                output=ROOT/'reports'/(run.name+'-'+str(suffix));suffix+=1
        receipt=export_report(run,output)
    except (ValueError,OSError,TypeError) as error:
        parser.error(str(error))
    print('Отчёт: '+str(output))
    print('Игровых событий: '+str(receipt['gameplay_events'])+'. Передайте эту папку и заметки с ID тестов.')


if __name__=='__main__':main()
