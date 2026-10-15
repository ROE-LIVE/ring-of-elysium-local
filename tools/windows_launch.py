"""Локальная зимняя сессия2022 прямо из выбранной папки, без копии клиента."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import struct
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_SHA = '2dca9b1e122e21363e14eeeb2372598c773205a907ed8d2b2d54a7229ad6ba18'
REQUIRED = ('Europa_Client.exe', 'ProtocalHandler_x64.dll', 'Tenproxy64.dll',
            'SFC/World_EU_ICELAND_4096_RemainingFiles.sfc')


class WindowsJob:
    """Завершает только собственные процессы и их дочерние процессы при выходе."""
    def __init__(self):
        import ctypes as c
        class Basic(c.Structure):
            _fields_=[('process_time',c.c_int64),('job_time',c.c_int64),('flags',c.c_uint32),
                      ('min_ws',c.c_size_t),('max_ws',c.c_size_t),('active',c.c_uint32),
                      ('affinity',c.c_size_t),('priority',c.c_uint32),('scheduling',c.c_uint32)]
        class IO(c.Structure):
            _fields_=[(name,c.c_uint64) for name in ('read_ops','write_ops','other_ops','read_bytes','write_bytes','other_bytes')]
        class Limits(c.Structure):
            _fields_=[('basic',Basic),('io',IO),('process_memory',c.c_size_t),('job_memory',c.c_size_t),
                      ('peak_process',c.c_size_t),('peak_job',c.c_size_t)]
        self.api=c.WinDLL('kernel32',use_last_error=True)
        self.api.CreateJobObjectW.argtypes=[c.c_void_p,c.c_wchar_p];self.api.CreateJobObjectW.restype=c.c_void_p
        self.api.SetInformationJobObject.argtypes=[c.c_void_p,c.c_int,c.c_void_p,c.c_uint32];self.api.SetInformationJobObject.restype=c.c_int
        self.api.AssignProcessToJobObject.argtypes=[c.c_void_p,c.c_void_p];self.api.AssignProcessToJobObject.restype=c.c_int
        self.api.CloseHandle.argtypes=[c.c_void_p];self.api.CloseHandle.restype=c.c_int
        self.handle=self.api.CreateJobObjectW(None,None)
        if not self.handle:raise c.WinError(c.get_last_error())
        limits=Limits();limits.basic.flags=0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.api.SetInformationJobObject(self.handle,9,c.byref(limits),c.sizeof(limits)):
            error=c.get_last_error();self.close();raise c.WinError(error)

    def add(self,process):
        if not self.api.AssignProcessToJobObject(self.handle,int(process._handle)):
            import ctypes
            raise ctypes.WinError(ctypes.get_last_error())

    def close(self):
        if self.handle:self.api.CloseHandle(self.handle);self.handle=None


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def validate_client(source):
    for name in REQUIRED:
        if not (source/name).is_file() or not (source/name).stat().st_size:
            raise ValueError('Не хватает полного клиента2022: '+name)
    if digest(source/'Europa_Client.exe') != EXPECTED_SHA:
        raise ValueError('Нужен проверенный EXE2022 0.2.989.0; этот EXE другого билда')


def prepare_client_in_place(source, run):
    """Проверяет выбранный клиент; пишет только хеши в журнал, без копии/бэкапа."""
    source = Path(source).resolve()
    validate_client(source)
    critical = [dict(file=name, sha256=digest(source/name)) for name in REQUIRED[:3]]
    (Path(run)/'client-files-before.json').write_text(
        json.dumps(dict(client=str(source), mode='in_place', critical=critical),
                   ensure_ascii=False, indent=2), encoding='utf-8')
    print('Клиент используется на месте, без копирования: '+str(source), flush=True)
    return source


def extract_region(client, target):
    """Извлекает один проверенный публичный ресурс, не полный SFC."""
    from lz4.block import decompress
    spec = json.loads((ROOT/'config/region-source.json').read_text())
    if target.exists() and digest(target) == spec['sha256']:
        return
    with (client/spec['archive']).open('rb') as stream:
        magic,version,count = struct.unpack('<4sII',stream.read(12))
        if magic != b'SFC\x1a' or version != 3 or spec['ordinal'] >= count:
            raise ValueError('Не тот контейнер зимних регионов')
        stream.seek(12+12*spec['ordinal'])
        _,_,offset = struct.unpack('<III',stream.read(12));stream.seek(offset)
        packed_size = struct.unpack('<I',stream.read(4))[0]
        if not 0 < packed_size <= 8*1024*1024:
            raise ValueError('Размер выбранного ресурса вне границ')
        packed = stream.read(packed_size)
        raw_size = struct.unpack('<I',stream.read(4))[0]
        if raw_size != spec['size']:
            raise ValueError('Не совпал размер зимней сетки')
        data = decompress(packed,uncompressed_size=raw_size)
    if hashlib.sha256(data).hexdigest() != spec['sha256']:
        raise ValueError('Не совпала контрольная сумма зимней сетки')
    target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)


def materialize(run, kit, client=None, cycle=False, weapon_profile='citori', target_los='off',
                loot_catalog=None, death_on_zero=False, own_armor_absorb_percent=0, validate_movement=False,
                frag_damage=100, start_hour=8, temperature_raw=500, native_airdrop=False, native_evacuation=False, diagnostic_departure=False, original_jeeps=False, climb_practice=False, vehicle_profile='jeep', boat_practice=False, bot_ground_route=False, bot_behavior=False, account_profile='default', winter_doors=False, winter_windows=False, cycle_scale=1, diagnostic_hazard=False):
    if type(cycle_scale) is not int or not 1 <= cycle_scale <= 10:
        raise ValueError('CycleScale: целое1..10')
    if type(diagnostic_hazard) is not bool:
        raise ValueError('DiagnosticHazard требует bool')
    if native_evacuation and cycle_scale != 1:
        raise ValueError('NativeEvacuation пока требует CycleScale1: исходная скорость полёта не масштабируется')
    from local_account_2022 import local_account
    account = local_account(ROOT/'runtime', account_profile)
    if type(bot_behavior) is not bool or bot_behavior and not bot_ground_route:
        raise ValueError('BotBehavior требует BotGroundRoute')
    if type(bot_ground_route) is not bool:
        raise ValueError('bot_ground_route должен быть bool')
    if type(start_hour) is not int or start_hour not in (7, 8, 15, 16):
        raise ValueError('StartHour:7/8/15/16 из EnvrMapTimeTable для16010')
    if type(temperature_raw) is not int or not -5000 <= temperature_raw <= 500:
        raise ValueError('TemperatureRaw: целое−5000..500, единица0.01°C')
    if target_los not in ('off', 'open', 'blocked'):
        raise ValueError('TargetLOS: off/open/blocked')
    if type(own_armor_absorb_percent) is not int or not 0 <= own_armor_absorb_percent <= 100:
        raise ValueError('Учебная защита собственного жилета требует целое0..100')
    if type(frag_damage) is not int or not 0 <= frag_damage <= 1000:
        raise ValueError('Учебный урон осколочной гранаты требует целое0..1000')
    if type(validate_movement) is not bool:
        raise ValueError('validate_movement должен быть bool')
    if type(diagnostic_departure) is not bool or diagnostic_departure and not native_evacuation:
        raise ValueError('DiagnosticDeparture требует NativeEvacuation')
    if type(native_evacuation) is not bool:
        raise ValueError('native_evacuation должен быть bool')
    if type(boat_practice) is not bool or (boat_practice and (cycle or climb_practice)):
        raise ValueError('BoatPractice требует Mode walk безClimbPractice')
    if vehicle_profile not in ('jeep','snowmotor'):
        raise ValueError('VehicleProfile: jeep/snowmotor')
    if type(climb_practice) is not bool or (climb_practice and (kit != 'climb' or cycle)):
        raise ValueError('ClimbPractice требует Kit climb и Mode walk')
    if type(original_jeeps) is not bool:
        raise ValueError('original_jeeps должен быть bool')
    wires = json.loads((ROOT/'config/wire.json').read_text())
    wire_dir = run/'wire';wire_dir.mkdir()
    for token,record in wires.items():
        raw=bytes.fromhex(record['hex'])
        if len(raw) != record['size'] or hashlib.sha256(raw).hexdigest() != token:
            raise ValueError('Повреждён проверенный wire fixture')
        (wire_dir/(token+'.bin')).write_bytes(raw)
    region = ROOT/'runtime/regions-iceland-fast.dat'
    if cycle:
        if client is None:raise ValueError('Для cycle нужна runtime-копия клиента')
        extract_region(client,region)
    def resolve(value):
        if isinstance(value,dict):return {k:resolve(v) for k,v in value.items()}
        if isinstance(value,list):return [resolve(x) for x in value]
        if isinstance(value,str) and value.startswith('@wire/'):
            token=value.split('/')[1]
            if token not in wires:raise ValueError('Неизвестный fixture')
            return str(wire_dir/(token+'.bin'))
        if value == '@account':return account['state_file']
        if value == '@region':return str(region)
        return value
    configs = {}
    for path in (ROOT/'config').glob('*.json'):
        if path.stem in ('wire','region-source'):continue
        target = run/(path.stem+'.json')
        target.write_text(json.dumps(resolve(json.loads(path.read_text())),ensure_ascii=False,indent=2),encoding='utf-8')
        configs[path.stem]=target
    # Лобби сохраняет выбор; endpoint читает его заново при создании матча.
    for name, target in configs.items():
        if name.startswith('weapon-'):
            weapon = json.loads(target.read_text())
            weapon['cosmetics_config_file'] = str(configs['cosmetics'])
            target.write_text(json.dumps(weapon,ensure_ascii=False,indent=2),encoding='utf-8')
    from airdrop_fixture_2022 import add_airdrop_notices, native_airdrop_entity
    if type(native_airdrop) is not bool:
        raise ValueError('native_airdrop должен быть bool')
    if native_airdrop:
        # Только текущая одиночная parcel fixture; исходный RNG/серверная физика отсутствуют.
        parcel = json.loads(configs['parcel'].read_text())
        if 'parcels' in parcel:
            raise ValueError('NativeAirDrop ожидает стандартную одиночную fixture')
        old_entity = parcel['entity_file']
        body = native_airdrop_entity(Path(old_entity).read_bytes())
        target = run/'native-airdrop.bin'
        target.write_bytes(body)
        parcel = dict(parcels=[dict(entity_file=str(target), parcel_id=parcel['parcel_id'],
            native_motion=True, items=[dict(item_index=parcel['item_index'],
                                            definition=30004, quantity=parcel['quantity'])])])
        configs['parcel'].write_text(json.dumps(parcel, ensure_ascii=False, indent=2), encoding='utf-8')
        for name in ('scene-walk', 'scene-cycle'):
            scene = json.loads(configs[name].read_text())
            for rule in scene:
                for response in rule.get('responses', []):
                    if response.get('payload_file') == old_entity:
                        response['payload_file'] = str(target)
            configs[name].write_text(json.dumps(scene,ensure_ascii=False,indent=2), encoding='utf-8')
    for name in ('scene-walk', 'scene-cycle'):
        scene = add_airdrop_notices(json.loads(configs[name].read_text()))
        configs[name].write_text(json.dumps(scene,ensure_ascii=False,indent=2), encoding='utf-8')
    if climb_practice:
        from climb_practice_2022 import practice_scene
        name = 'scene-walk'
        scene = practice_scene(json.loads(configs[name].read_text()))
        configs[name].write_text(json.dumps(scene,ensure_ascii=False,indent=2),encoding='utf-8')
    if original_jeeps:
        from original_jeeps_2022 import add_original_jeeps
        for name in ('scene-walk', 'scene-cycle'):
            scene = add_original_jeeps(json.loads(configs[name].read_text()))
            configs[name].write_text(json.dumps(scene,ensure_ascii=False,indent=2),encoding='utf-8')
    if vehicle_profile == 'snowmotor':
        from snowmotor_fixture_2022 import snowmotor_scene
        for name in ('scene-walk','scene-cycle'):
            scene = snowmotor_scene(json.loads(configs[name].read_text()))
            configs[name].write_text(json.dumps(scene,ensure_ascii=False,indent=2),encoding='utf-8')
    if boat_practice:
        from boat_practice_2022 import practice_scene
        name='scene-walk'
        scene=practice_scene(json.loads(configs[name].read_text()))
        configs[name].write_text(json.dumps(scene,ensure_ascii=False,indent=2),encoding='utf-8')
    if native_evacuation:
        from evacuation_flight_2022 import native_evacuation_scene
        for name in ('scene-walk', 'scene-cycle'):
            scene = native_evacuation_scene(json.loads(configs[name].read_text()))
            configs[name].write_text(json.dumps(scene,ensure_ascii=False,indent=2),encoding='utf-8')
    if diagnostic_departure:
        departure = json.loads(configs['evacuation'].read_text())
        departure['diagnostic_departure_seconds'] = 20
        configs['evacuation'].write_text(json.dumps(departure,ensure_ascii=False,indent=2),encoding='utf-8')
    from environment_probe_2022 import EnvironmentFixture
    environment = configs['environment']
    preset = json.loads(environment.read_text())
    preset['hour'] = start_hour
    preset['temperature_raw'] = temperature_raw
    environment.write_text(json.dumps(preset, ensure_ascii=False, indent=2), encoding='utf-8')
    EnvironmentFixture.load(environment)
    from weapon_probe_2022 import WeaponFixture
    # Три общих слота; перезарядка не пересоздаёт полный inventory.
    selected_weapon_path = configs['weapon-'+kit]
    selected_weapon = json.loads(selected_weapon_path.read_text())
    selected_weapon.update(weapon_slots=3, reload_update='delta', timed_reload=True,
                           inventory_update='delta', handgun_slot=True,
                           winter_starter_inventory=True,
                           combat_armor_absorb_percent=own_armor_absorb_percent,
                           throwable_actions=True, diagnostic_frag_damage=frag_damage)
    selected_weapon_path.write_text(json.dumps(selected_weapon,ensure_ascii=False,indent=2),encoding='utf-8')
    families = {'m4': (10201, 30001, 50), 'ak47': (10202, 30002, 50),
                'r700': (10101, 30001, 40), 'mosin': (10102, 30002, 40),
                'usp45': (20001, 30005, 30)}
    if weapon_profile in families:
        path = configs['weapon-'+kit]
        weapon = json.loads(path.read_text())
        weapon['gun_on_start'] = False
        replaced = set()
        replacements = {}
        for row in [weapon['loot'], *weapon.get('additional_loot', [])]:
            entity = bytearray(Path(row['entity_file']).read_bytes())
            if len(entity) != 100:
                continue
            definition = struct.unpack_from('>I', entity, 63)[0]
            if definition not in (10402, 30004) or definition in replaced:
                continue
            gun_definition, ammunition_definition, ammunition_quantity = families[weapon_profile]
            new_definition, quantity = ((gun_definition, 1) if definition == 10402
                                        else (ammunition_definition, ammunition_quantity))
            struct.pack_into('>II', entity, 63, new_definition, quantity)
            target = run / (weapon_profile + ('-ground.bin' if definition == 10402 else '-ammunition.bin'))
            target.write_bytes(entity)
            replacements[row['entity_file']] = str(target)
            row['entity_file'] = str(target)
            replaced.add(definition)
        if replaced != {10402, 30004}:
            raise ValueError('В проверенном профиле не найдены Citori и12ga')
        path.write_text(json.dumps(weapon,ensure_ascii=False,indent=2),encoding='utf-8')
        def replace_scene_references(value):
            if isinstance(value, dict):
                return {key: replace_scene_references(item) for key, item in value.items()}
            if isinstance(value, list):
                return [replace_scene_references(item) for item in value]
            return replacements.get(value, value) if isinstance(value, str) else value
        for scene_name in ('scene-walk', 'scene-cycle'):
            scene_path = configs[scene_name]
            scene_path.write_text(json.dumps(replace_scene_references(
                json.loads(scene_path.read_text())),ensure_ascii=False,indent=2),encoding='utf-8')
    elif weapon_profile != 'citori':
        raise ValueError('Неизвестный профиль оружия')
    # Проверенный medical union70001/2/3; координаты — наш фиксированный стенд.
    weapon = json.loads(selected_weapon_path.read_text())
    template = Path(weapon['loot']['entity_file']).read_bytes()
    if len(template) != 100:
        raise ValueError('Нужен проверенный100-байтный шаблон предмета')
    medical_entities = []
    for offset, (definition, quantity) in enumerate(((70001, 5), (70002, 1), (70003, 1))):
        entity = bytearray(template)
        struct.pack_into('>Q', entity, 4, 0x31d0003000000 + offset)
        struct.pack_into('>I', entity, 46, 1)
        entity[62] = 2
        struct.pack_into('>III', entity, 63, definition, quantity, 88001 + offset)
        target = run / ('medical-' + str(definition) + '.bin')
        target.write_bytes(entity)
        medical_entities.append(str(target))
        weapon.setdefault('additional_loot', []).append(dict(
            entity_file=str(target), acknowledgement_file=weapon['loot']['acknowledgement_file']))
    # INV07: Red-dot/AR/SR и один проверенный AR extended-mag40403.
    for offset, definition in enumerate((40305, 40103, 40101, 40403)):
        entity = bytearray(template)
        struct.pack_into('>Q', entity, 4, 0x31d0005000000 + offset)
        struct.pack_into('>III', entity, 63, definition, 1, 90001 + offset)
        target = run / ('attachment-' + str(definition) + '.bin')
        target.write_bytes(entity)
        medical_entities.append(str(target))
        weapon.setdefault('additional_loot', []).append(dict(
            entity_file=str(target), acknowledgement_file=weapon['loot']['acknowledgement_file']))
    # GUN09: три проверенные winter grenade types, по две в фиксированном луте.
    for offset, definition in enumerate((50001,50002,50003)):
        entity=bytearray(template)
        struct.pack_into('>Q',entity,4,0x31d0006000000+offset)
        struct.pack_into('>III',entity,63,definition,2,91001+offset)
        target=run/('grenade-'+str(definition)+'.bin')
        target.write_bytes(entity)
        medical_entities.append(str(target))
        weapon.setdefault('additional_loot',[]).append(dict(
            entity_file=str(target),acknowledgement_file=weapon['loot']['acknowledgement_file']))
    selected_weapon_path.write_text(json.dumps(weapon,ensure_ascii=False,indent=2),encoding='utf-8')
    for scene_name in ('scene-walk', 'scene-cycle'):
        scene_path = configs[scene_name]
        scene = json.loads(scene_path.read_text())
        ground_rules = [rule for rule in scene if any(
            response.get('command') == '0x821' for response in rule.get('responses', []))]
        if len(ground_rules) != 1:
            raise ValueError('Не найдена единственная начальная выдача лута')
        ground_rules[0]['responses'].extend(dict(command='0x821', payload_file=path)
                                           for path in medical_entities)
        scene_path.write_text(json.dumps(scene,ensure_ascii=False,indent=2),encoding='utf-8')
    WeaponFixture.load(configs['weapon-'+kit])
    if target_los != 'off':
        # GUN06: диагностическая преграда без модели, не коллизия всей карты.
        boxes = [] if target_los == 'open' else [
            [[365500,543000,258000], [365600,545000,260000]]]
        for name in ('target-plain', 'target-armored', 'actor'):
            path = configs[name]
            target = json.loads(path.read_text())
            target['collision_boxes'] = boxes
            path.write_text(json.dumps(target,ensure_ascii=False,indent=2),encoding='utf-8')
    if bot_ground_route:
        # Маршрут измерен native309 на карте16010; это ограниченный граф,
        # не исходный navmesh. Позицию собственного игрока не переносим.
        route = run/'bot-ground-route.json'
        route.write_bytes((ROOT/'config/bot-ground-route.json').read_bytes())
        actor = json.loads(configs['actor'].read_text())
        actor.update(ground_route_file=str(route), movement_animation=True,
                     speed_cm_seconds=200, attack_pause_seconds=1)
        actor['collision_boxes'] = json.loads(route.read_text())['clearance_boxes']
        configs['actor'].write_text(json.dumps(actor,ensure_ascii=False,indent=2),encoding='utf-8')
        from actor_probe_2022 import ActorFixture
        ActorFixture.load(configs['actor'])
    if bot_behavior:
        # Фиксированный опыт BOT05: два собственных ground821 и hazard
        # у начала измеренного маршрута. Исходные RNG/AI здесь не заявляются.
        actor = json.loads(configs['actor'].read_text())
        for key in ('equipment_file','attack','attack_ammunition','armor','death_loot_reserve'):
            actor.pop(key,None)
        actor.update(speed_cm_seconds=0,attack_pause_seconds=0,
                     behavior=dict(loot_indexes=[92001,92002],after_seconds=15,speed_cm_seconds=200))
        configs['actor'].write_text(json.dumps(actor,ensure_ascii=False,indent=2),encoding='utf-8')
        weapon = json.loads(selected_weapon_path.read_text())
        base = Path(weapon['loot']['entity_file']).read_bytes()
        responses = []
        for offset,(definition,quantity) in enumerate(((10402,1),(30004,6))):
            body=bytearray(base)
            struct.pack_into('>Q',body,4,0x31d0009000000+offset)
            struct.pack_into('>3i',body,29,370653,544252,258844)
            struct.pack_into('>III',body,63,definition,quantity,92001+offset)
            path=run/('bot-loot-'+str(definition)+'.bin');path.write_bytes(body)
            weapon.setdefault('additional_loot',[]).append(dict(entity_file=str(path),
                                     acknowledgement_file=weapon['loot']['acknowledgement_file']))
            responses.append(dict(command='0x821',payload_file=str(path)))
        selected_weapon_path.write_text(json.dumps(weapon,ensure_ascii=False,indent=2),encoding='utf-8')
        for name in ('scene-walk','scene-cycle'):
            scene=json.loads(configs[name].read_text())
            ground=next(q for q in scene if any(x.get('command')=='0x821' for x in q['responses']))
            ground['responses'].extend(responses)
            configs[name].write_text(json.dumps(scene,ensure_ascii=False,indent=2),encoding='utf-8')
        world=json.loads(configs['world'].read_text())
        world['hazard']['bounds_xy']=[370600,543200,370750,544350]
        configs['world'].write_text(json.dumps(world,ensure_ascii=False,indent=2),encoding='utf-8')
        from actor_probe_2022 import ActorFixture
        ActorFixture.load(configs['actor'])
    if type(winter_windows) is not bool:
        raise ValueError('WinterWindows должен быть bool')
    if winter_windows:
        from breakable_state_2022 import BreakableFixture
        source = ROOT/'config/winter-breakables.json'
        BreakableFixture.load(source)
        target = run/'winter-breakables.json'
        shutil.copy2(source,target)
        configs['winter-breakables'] = target
    if type(winter_doors) is not bool:
        raise ValueError('WinterDoors должен быть bool')
    if winter_doors:
        from door_state_2022 import DoorFixture
        source = ROOT/'config/winter-doors.json'
        DoorFixture.load(source)
        target = run/'winter-doors.json'
        target.write_bytes(source.read_bytes())
        configs['winter-doors'] = target
    if loot_catalog is not None:
        source = Path(loot_catalog)
        if not source.is_file() or source.stat().st_size > 16 * 1024 * 1024:
            raise ValueError('LootCatalog: нужен существующий JSON до16МиБ')
        # Снимок пользовательского каталога фиксирует реально проверенный вход.
        target = run/'custom-loot-catalog.json'
        target.write_bytes(source.read_bytes())
        from loot_catalog_2022 import LootCatalog
        fixture = WeaponFixture.load(selected_weapon_path)
        catalog = LootCatalog.load(target, fixture.all_loot[0].entity)
        catalog.validate_fixture(fixture)
        configs['custom-loot-catalog'] = target
    if death_on_zero:
        # Явный локальный terminal-death; исходные downed/revive не восстановлены.
        path = configs['world']
        world = json.loads(path.read_text())
        world.update(death_on_zero=True, hp_floor=0)
        path.write_text(json.dumps(world, ensure_ascii=False, indent=2), encoding='utf-8')
    if validate_movement:
        path = configs['world']
        world = json.loads(path.read_text())
        world['movement_validation'] = dict(horizontal_speed_cm_s=5000,
                                           vertical_speed_cm_s=20000, burst_seconds=2)
        path.write_text(json.dumps(world, ensure_ascii=False, indent=2), encoding='utf-8')
    from match_pacing_2022 import paced_match
    world, scene = paced_match(json.loads(configs['world'].read_text()),
                              json.loads(configs['scene-cycle'].read_text()),
                              cycle_scale, diagnostic_hazard or bot_behavior)
    configs['world'].write_text(json.dumps(world,ensure_ascii=False,indent=2),encoding='utf-8')
    configs['scene-cycle'].write_text(json.dumps(scene,ensure_ascii=False,indent=2),encoding='utf-8')
    return configs


def check_ports(bindings=None):
    sockets = []
    try:
        for port,transport in (bindings if bindings is not None else [(8001,socket.SOCK_STREAM),(9001,socket.SOCK_STREAM),(18001,socket.SOCK_DGRAM)]):
            sock=socket.socket(socket.AF_INET,transport);sockets.append(sock)
            if os.name=='nt':sock.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)
            sock.bind(('127.0.0.1',port))
    except OSError as error:
        raise ValueError('Порт localhost занят другим процессом; закройте прежнюю сессию') from error
    finally:
        for sock in sockets:sock.close()


def wait_ready(process,path,marker,timeout=40):
    # Не соединяемся для проверки: лобби обслуживает одну сессию.
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        if process.poll() is not None:
            raise RuntimeError('Сервис завершился при запуске. Журнал: '+str(path))
        if path.exists() and marker in path.read_text(encoding='utf-8',errors='replace'):
            return
        time.sleep(.2)
    raise RuntimeError('Сервис не сообщил готовность. Журнал: '+str(path))


def write_launch_summary(run, args):
    """Записывает действующие параметры; ключи и авторизационные данные исключены."""
    summary = dict(build='2022-0.2.989.0-x64', map=16010, launcher_platform=sys.platform,
                   mode=args.mode, kit=args.kit, weapon_profile=args.weapon_profile,
                   target=args.target, target_los=args.target_los, bots=args.bots,
                   bot_ground_route=bool(getattr(args,'bot_ground_route',False)),
                   bot_behavior=bool(getattr(args,'bot_behavior',False)),
                   live_control=bool(getattr(args,'live_control',False)),
                   reliable_udp=args.reliable_udp, idle_handoff=args.idle_handoff,
                   duration=args.duration, verify_only=args.verify_only,
                   world_cycle_enabled=args.mode == 'cycle',
                   cycle_scale=getattr(args,'cycle_scale',1),
                   diagnostic_hazard_enabled=bool(getattr(args,'diagnostic_hazard',False) or getattr(args,'bot_behavior',False)),
                   death_on_zero=bool(getattr(args, 'death_on_zero', False)),
                   own_armor_absorb_percent=getattr(args, 'own_armor_absorb_percent', 0),
                   own_armor_model='diagnostic_body_percent_durability',
                   throwable_actions_enabled=True,
                   diagnostic_frag_damage=getattr(args, 'frag_damage', 100),
                   original_grenade_damage_formula=False,
                   movement_validation_enabled=bool(getattr(args, 'validate_movement', False)),
                   custom_loot_catalog_enabled=bool(getattr(args, 'loot_catalog', None)),
                   winter_doors_enabled=bool(getattr(args, 'winter_doors', False)),
                   winter_windows_enabled=bool(getattr(args, 'winter_windows', False)),
                   spawn_selection_supported=True, kit_selection_in_game_supported=True,
                   spawn_height_basis="team_l_estimates_native_selected_cells",
                   original_starter_inventory=False)
    summary.update(launcher_revision='20261015-inplace-v1', client_mode='in_place', weapon_slots=3,
                   starter_item_source='INITITEM.XML/map16010/stage1',
                   starter_magazine_policy='full_capacity_local',
                   source_hashes={name:digest(ROOT/name) for name in (
                       'tools/windows_launch.py', 'server/directory/weapon_probe_2022.py',
                       'server/directory/winter_selection_2022.py', 'server/directory/world_probe_2022.py',
                       'server/directory/actor_probe_2022.py', 'tools/match_pacing_2022.py', 'SOURCE-MANIFEST.json')})
    from local_account_2022 import local_account
    account = local_account(ROOT/'runtime', getattr(args, 'profile', 'default'))
    summary.update(local_profile=account['name'], local_profile_id='local-2022:'+account['name'], local_actor_uid=hex(account['actor_uid']),
                   local_session_id=run.name, original_account_authentication=False,
                   profile_isolation_scope='durable_cosmetics_only')
    summary['debug_console'] = bool(getattr(args, 'debug_console', False))
    summary['remote_peer'] = getattr(args, 'remote_peer', None)
    summary['server_only'] = bool(getattr(args, 'services_only', False))
    summary['lan_udp_tunnel'] = bool(getattr(args, 'lan_tunnel', False) or summary['remote_peer'])
    summary['original_network_transport'] = not summary['lan_udp_tunnel']
    summary['start_hour'] = getattr(args, 'start_hour', 8)
    summary['original_random_time_selection'] = False
    summary['temperature_raw'] = getattr(args, 'temperature_raw', 500)
    summary['native_airdrop'] = getattr(args, 'native_airdrop', False)
    summary['boat_practice'] = getattr(args, 'boat_practice', False)
    if summary['boat_practice']:
        summary['spawn_selection_supported'] = False
        summary['spawn_height_basis'] = 'fixed_boat135136_proton206'
    summary['vehicle_damage_practice'] = getattr(args, 'vehicle_damage_practice', False)
    summary['vehicle_profile'] = getattr(args, 'vehicle_profile', 'jeep')
    summary['original_vehicle_rng'] = False
    summary['climb_practice'] = getattr(args, 'climb_practice', False)
    if summary['climb_practice']:
        summary['spawn_selection_supported'] = False
        summary['spawn_height_basis'] = 'fixed_cliff27930_proton201'
    summary['original_jeeps'] = getattr(args, 'original_jeeps', False)
    summary['native_evacuation'] = getattr(args, 'native_evacuation', False)
    summary['diagnostic_departure'] = getattr(args, 'diagnostic_departure', False)
    summary['original_temperature_algorithm'] = False
    if summary['remote_peer']:
        summary['local_server_settings_effective'] = False
        for field in ('mode','kit','weapon_profile','target','bots','world_cycle_enabled'):
            summary[field] = 'remote_server'
    else:
        summary['local_server_settings_effective'] = True
    (run/'launch-summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    return summary


def main():
    sys.path.insert(0,str(ROOT/'server/directory'));sys.path.insert(0,str(ROOT/'tools'))
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--client',type=Path,required=True,help='Папка полного клиента2022; используется на месте без копирования')
    parser.add_argument('--profile', default='default', help='Отдельный локальный выбор внешности; не оригинальный login')
    parser.add_argument('--kit',choices=('snowboard','glider','climb'),default='snowboard')
    parser.add_argument('--start-hour', type=int, choices=(7, 8, 15, 16), default=8,
                        help='Начальный период суток из таблицы карты16010')
    parser.add_argument('--temperature-raw', type=int, default=500,
                        help='Фиксированная температура−5000..500 в0.01°C; исходная кривая не восстановлена')
    parser.add_argument('--debug-console',action='store_true',help='Собственный debug marker и ручной числовой HUD snapshot; не server host')
    parser.add_argument('--weapon-profile',choices=('citori','m4','ak47','r700','mosin','usp45'),default='citori')
    parser.add_argument('--winter-windows', action='store_true', help='Подтверждение разрушения стекла; одиночный учебный peer')
    parser.add_argument('--winter-doors', action='store_true', help='Обратимые двери зимы: F/состояние; одиночный peer')
    parser.add_argument('--loot-catalog', type=Path,
                        help='Явный JSON каталога предметов; проверяется и сохраняется в журнале запуска')
    parser.add_argument('--native-airdrop',action='store_true',
                        help='Одиночный native501 flight+client MOVE_REQ; исходная серверная физика не восстановлена')
    parser.add_argument('--vehicle-damage-practice', action='store_true', help='Учебные500HP за попадание по корпусу102/109; исходная формула не восстановлена')
    parser.add_argument('--boat-practice',action='store_true',
                        help='Лодка203 в исходной точке135136; диагностический выход; только walk')
    parser.add_argument('--vehicle-profile',choices=('jeep','snowmotor'),default='jeep',
                        help='Фиксированный водительский профиль102/109; без исходного RNG и повреждений')
    parser.add_argument('--climb-practice',action='store_true',
                        help='Фиксированная скала27930; требует kit climb и mode walk; Windows повтор отдельно')
    parser.add_argument('--original-jeeps',action='store_true',
                        help='Два фиксированных Jeep102 на исходных точках; без RNG')
    parser.add_argument('--native-evacuation',action='store_true',
                        help='Подтверждённый участок plane6/6575; требует cycle, departure ещё не восстановлен')
    parser.add_argument('--diagnostic-departure',action='store_true',
                        help='Собственный прямой20сек отлёт1328/1382; требует native-evacuation, исходная кривая неизвестна')
    parser.add_argument('--mode',choices=('walk','cycle'),default='walk')
    parser.add_argument('--cycle-scale',type=int,choices=range(1,11),default=1,metavar='1..10',
                        help='Множитель календаря зон/дропа/эвакуации; Duration ограничивает процесс отдельно')
    parser.add_argument('--diagnostic-hazard',action='store_true',
                        help='Включить невидимый учебный прямоугольник5HP/s; по умолчанию отключён')
    parser.add_argument('--death-on-zero',action='store_true',
                        help='Экспериментальная смерть при HP0; требует mode cycle; без downed/revive')
    parser.add_argument('--live-control',action='store_true',help='Локальный live-commands.json/state actions; без сетевой admin API')
    parser.add_argument('--bots',action='store_true')
    parser.add_argument('--bot-ground-route',action='store_true',
                        help='Измеренный обход камня/SC25; требует bots; свободная навигация отсутствует')
    parser.add_argument('--bot-behavior',action='store_true',
                        help='Одиночный BOT05 Citori/12ga→safe; требует Bots/BotGroundRoute/cycle')
    parser.add_argument('--frag-damage',type=int,default=100,
                        help='Учебный flat урон осколочной гранаты0..1000; 0 отключает HP-эффект')
    parser.add_argument('--own-armor-absorb-percent',type=int,default=0,
                        help='Учебная защита тела0..100%%; требует bots и cycle, исходная формула неизвестна')
    parser.add_argument('--validate-movement',action='store_true',
                        help='Учебный бюджет позиции XY5000/Z20000см/с; требует cycle, без физики/LOS карты')
    parser.add_argument('--target',choices=('none','plain','armored'),default='none',
                        help='Пассивная мишень с учебным HP/уроном; armored добавляет тестовый жилет')
    parser.add_argument('--target-los',choices=('off','open','blocked'),default='off',
                        help='Диагностический контроль луча; blocked задаёт невидимую серверную преграду')
    parser.add_argument('--reliable-udp',action='store_true',help='Экспериментальные ACK/retry и сборка игрового UDP')
    parser.add_argument('--idle-handoff',action='store_true',help='Перенос authenticated idle peer послеRELАY; требует reliable-udp')
    parser.add_argument('--duration',type=int,default=3600)
    parser.add_argument('--dotnet',default=str(ROOT/'.tools/dotnet/dotnet.exe'))
    parser.add_argument('--key-file',type=Path,default=ROOT/'private/candidate-001.key')
    parser.add_argument('--verify-only',action='store_true')
    parser.add_argument('--remote-peer', help='Windows клиент→SSH LinuxUser@LAN_IPv4; сервер должен иметь --lan-tunnel')
    parser.add_argument('--lan-tunnel', action='store_true', help='Loopback UDP↔TCP server дляSSH; требует --services-only')
    parser.add_argument('--services-only',action='store_true',help=argparse.SUPPRESS)
    args=parser.parse_args()
    from local_account_2022 import local_account
    try:
        account = local_account(ROOT/'runtime', args.profile)
    except ValueError as error:
        parser.error(str(error))
    args.profile = account['name']
    if args.remote_peer and args.winter_windows:
        parser.error('WinterWindows пока требует одиночный local peer')
    if args.remote_peer and args.winter_doors:
        parser.error('WinterDoors настраивается на удалённом сервере; этот флаг для одиночного local peer')
    if args.remote_peer:
        from remote_peer_2022 import ssh_command
        try:
            ssh_args = ssh_command(args.remote_peer)
        except ValueError as error:
            parser.error(str(error))
        if args.services_only or args.lan_tunnel:
            parser.error('RemotePeer несовместим с ServicesOnly/LanTunnel')
        if not args.verify_only and shutil.which('ssh') is None:
            parser.error('Нет OpenSSH client ssh.exe; установите компонент Windows OpenSSH Client')
    if args.debug_console and args.services_only:
        parser.error('DebugConsole относится к игровому клиенту, не ServicesOnly')
    if args.lan_tunnel and not args.services_only:
        parser.error('LanTunnel требует ServicesOnly')
    if not 0 <= args.own_armor_absorb_percent <= 100:
        parser.error('own-armor-absorb-percent:0..100')
    if args.own_armor_absorb_percent and (not args.bots or args.mode != 'cycle'):
        parser.error('Учебная защита собственного жилета требует --bots --mode cycle')
    if args.validate_movement and args.mode != 'cycle':
        parser.error('Учебная валидация движения требует --mode cycle')
    if args.vehicle_damage_practice and args.boat_practice:
        parser.error('VehicleDamagePractice проверяет корпус102/109; лодка отдельно')
    if args.boat_practice and (args.mode != 'walk' or args.climb_practice):
        parser.error('BoatPractice требует Mode walk безClimbPractice')
    if args.climb_practice and (args.kit != 'climb' or args.mode != 'walk'):
        parser.error('ClimbPractice требует Kit climb и Mode walk')
    if args.diagnostic_departure and not args.native_evacuation:
        parser.error('DiagnosticDeparture требует NativeEvacuation')
    if args.native_evacuation and args.mode != 'cycle':
        parser.error('NativeEvacuation требует Mode cycle')
    if args.cycle_scale != 1 and args.mode != 'cycle':
        parser.error('CycleScale требует Mode cycle')
    if args.diagnostic_hazard and args.mode != 'cycle':
        parser.error('DiagnosticHazard требует Mode cycle')
    if args.native_evacuation and args.cycle_scale != 1:
        parser.error('NativeEvacuation пока требует CycleScale1')
    if args.death_on_zero and args.mode != 'cycle':
        parser.error('DeathOnZero требует Mode cycle')
    if args.idle_handoff and not args.reliable_udp:
        parser.error('IdleHandoff требует ReliableUDP')
    if args.bot_behavior and (not args.bots or not args.bot_ground_route or args.mode != 'cycle'):
        parser.error('BotBehavior требует Bots, BotGroundRoute и Mode cycle')
    if args.bot_ground_route and not args.bots:
        parser.error('BotGroundRoute требует Bots')
    if args.bots and args.target != 'none':
        parser.error('Выберите Bots либо Target: endpoint поддерживает одну тестовую сущность')
    if args.target_los != 'off' and args.target == 'none':
        parser.error('TargetLOS требует Target plain/armored')
    if os.name != 'nt':
        def interrupt(signum,frame):raise KeyboardInterrupt
        signal.signal(signal.SIGTERM,interrupt)
    if not 120<=args.duration<=7200:parser.error('duration120..7200')
    if not args.verify_only and not args.services_only and os.name!='nt':
        parser.error('Игровой запуск предназначен для Windows11 x64')
    if not args.key_file.is_file() or args.key_file.stat().st_size!=16:
        raise ValueError('Добавьте локальный private/candidate-001.key; см. private/README.md. Ключ не распространяется в Git')
    run=ROOT/'runs'/(datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S')+'-'+uuid.uuid4().hex[:6])
    run.mkdir(parents=True)
    write_launch_summary(run, args)
    if args.live_control:
        (run/"live-commands.json").write_text("[]\n",encoding="utf-8")
    if args.verify_only:
        configs=materialize(run,args.kit,client=args.client,cycle=args.mode=='cycle' and not args.remote_peer,weapon_profile=args.weapon_profile,target_los=args.target_los,
                            loot_catalog=args.loot_catalog, death_on_zero=args.death_on_zero,
                            own_armor_absorb_percent=args.own_armor_absorb_percent,
                            validate_movement=args.validate_movement, frag_damage=args.frag_damage,
                            start_hour=args.start_hour, temperature_raw=args.temperature_raw,
                            native_airdrop=args.native_airdrop, native_evacuation=args.native_evacuation, diagnostic_departure=args.diagnostic_departure, original_jeeps=args.original_jeeps, climb_practice=args.climb_practice, vehicle_profile=args.vehicle_profile, boat_practice=args.boat_practice, bot_ground_route=args.bot_ground_route, bot_behavior=args.bot_behavior, account_profile=args.profile, winter_doors=args.winter_doors, winter_windows=args.winter_windows, cycle_scale=args.cycle_scale, diagnostic_hazard=args.diagnostic_hazard)
        from actor_probe_2022 import ActorFixture
        if args.bots:ActorFixture.load(configs['actor'])
        if args.target != 'none':ActorFixture.load(configs['target-'+args.target])
        from game_endpoint_probe_2022 import load_scene_rules
        from roe_room_2023 import decode_enter_room_response
        from local_cosmetics_2022 import LocalCosmetics
        for mode in ('walk','cycle'):load_scene_rules(configs['scene-'+mode])
        room=json.loads(configs['room'].read_text())['room_file']
        decode_enter_room_response(Path(room).read_bytes());catalog=LocalCosmetics(configs['cosmetics'])
        from weapon_probe_2022 import WeaponFixture
        fixture = WeaponFixture.load(configs['weapon-'+args.kit])
        extra = 0
        if 'custom-loot-catalog' in configs:
            from loot_catalog_2022 import LootCatalog
            from weapon_probe_2022 import WeaponFixture
            fixture = WeaponFixture.load(configs['weapon-'+args.kit])
            extra = len(LootCatalog.load(configs['custom-loot-catalog'], fixture.all_loot[0].entity).items)
        print('Файлы проверены: winter16010,',args.weapon_profile,', стартовый лут',len(fixture.all_loot),', дополнительный',extra,', каталог',len(catalog.ids),len(catalog.characters),len(catalog.accessories),len(catalog.clothes));return 0
    if args.services_only:
        runtime=args.client.resolve()
    else:
        runtime=prepare_client_in_place(args.client, run)
        subprocess.run(['powershell','-NoProfile','-ExecutionPolicy','Bypass','-File',str(ROOT/'tools/ensure_firewall.ps1'),'-Client',str(runtime)],check=True)
    configs=materialize(run,args.kit,runtime,args.mode=='cycle' and not args.remote_peer,args.weapon_profile,args.target_los,
                        args.loot_catalog, death_on_zero=args.death_on_zero,
                        own_armor_absorb_percent=args.own_armor_absorb_percent,
                        validate_movement=args.validate_movement, frag_damage=args.frag_damage,
                        start_hour=args.start_hour, temperature_raw=args.temperature_raw,
                            native_airdrop=args.native_airdrop, native_evacuation=args.native_evacuation, diagnostic_departure=args.diagnostic_departure, original_jeeps=args.original_jeeps, climb_practice=args.climb_practice, vehicle_profile=args.vehicle_profile, boat_practice=args.boat_practice, bot_ground_route=args.bot_ground_route, bot_behavior=args.bot_behavior, account_profile=args.profile, winter_doors=args.winter_doors, winter_windows=args.winter_windows, cycle_scale=args.cycle_scale, diagnostic_hazard=args.diagnostic_hazard)
    if args.remote_peer:
        check_ports([(8001,socket.SOCK_STREAM),(19001,socket.SOCK_STREAM),(18001,socket.SOCK_DGRAM)])
    elif args.lan_tunnel:
        check_ports([(8001,socket.SOCK_STREAM),(9001,socket.SOCK_STREAM),(18001,socket.SOCK_DGRAM),(19001,socket.SOCK_STREAM)])
    else:
        check_ports()
    project=ROOT/'server/lobby/LobbyEmulator.Sdk/LobbyEmulator.Sdk.csproj'
    dll=project.parent/'bin/Release/net8.0/LobbyEmulator.dll'
    if not args.remote_peer and not dll.is_file():
        with (run/'build.log').open('w',encoding='utf-8') as log:
            subprocess.run([args.dotnet,'build',str(project),'-c','Release','--nologo'],stdout=log,stderr=subprocess.STDOUT,check=True,cwd=ROOT)
    processes=[];handles=[];job=WindowsJob() if os.name=='nt' else None;debug_session=None
    def start(name,command):
        log=run/(name+'.log');handle=log.open('w',encoding='utf-8');handles.append(handle)
        process=subprocess.Popen(command,cwd=ROOT,stdout=handle,stderr=subprocess.STDOUT)
        processes.append(process)
        if job:job.add(process)
        return process,log
    try:
        watched=[]
        if args.remote_peer:
            print('Подключаю SSH к '+args.remote_peer+'; используйте свою обычную авторизацию Linux.',flush=True)
            tunnel,log=start('ssh',ssh_args)
            wait_ready(tunnel,log,'Local forwarding listening on 127.0.0.1 port 19001',timeout=120)
            watched.append(('ssh',tunnel))
            bridge,log=start('udp-tunnel',[sys.executable,'-B','-u',str(ROOT/'tools/lan_tunnel_2022.py'),'client','--profile',args.profile,'--duration',str(args.duration)])
            wait_ready(bridge,log,'"kind": "ready"')
            watched.append(('udp-tunnel',bridge))
            print('Удалённый peer подключён. Профиль: '+args.profile+'. Настройки матча задаются на Linux. Журнал клиента: '+str(run),flush=True)
        else:
            lobby,log=start('lobby',[args.dotnet,str(dll)]);wait_ready(lobby,log,'Started on port 9001')
            proxy,log=start('proxy',[sys.executable,'-X','utf8','-B','-u',str(ROOT/'tools/run_service.py'),'proxy',
                '--session-key-file',str(args.key_file),'--local-server-clock','--reply','--team-reply','--match-reply','--novice-state','1',
                '--training-reply','--match-found-delay','5','--join-instance-config',str(configs['join']),
                '--local-cosmetics-config',str(configs['cosmetics']),'--actor-uid',str(account['actor_uid']),'--duration',str(args.duration+30),'--output',str(run/'lobby')])
            wait_ready(proxy,log,'"kind": "ready"')
            room=json.loads(configs['room'].read_text())['room_file']
            command=[sys.executable,'-X','utf8','-B','-u',str(ROOT/'tools/run_service.py'),'endpoint','--handshake','--ident','--grant','--auth',
                '--room-template',room,'--scene-rules',str(configs['scene-'+args.mode]),'--scene-clock','--selection-seconds','47',
                '--weapon-config',str(configs['weapon-'+args.kit]),'--parcel-config',str(configs['parcel']),
                '--environment-config',str(configs['environment']),
                '--duration',str(args.duration+30),'--output',str(run/'scene')]
            if args.vehicle_damage_practice:command+=['--diagnostic-vehicle-pellet-damage','500']
            if args.reliable_udp:command+=['--reliable-udp']
            if args.idle_handoff:command+=['--idle-handoff']
            if 'winter-breakables' in configs:
                command+=['--breakable-config',str(configs['winter-breakables'])]
            if 'winter-doors' in configs:
                command+=['--door-config',str(configs['winter-doors'])]
            if 'custom-loot-catalog' in configs:
                command+=['--loot-catalog',str(configs['custom-loot-catalog'])]
            if args.mode=='cycle':command+=['--world-config',str(configs['world']),'--evacuation-delay-seconds','8','--evacuation-result-config',str(configs['evacuation'])]
            if args.live_control:command+=['--live-commands',str(run/'live-commands.json')]
            if args.bots:command+=['--actor-config',str(configs['actor'])]
            elif args.target != 'none':command+=['--actor-config',str(configs['target-'+args.target])]
            peer,log=start('endpoint',command);wait_ready(peer,log,'"kind": "ready"')
            print(f'Сервисы готовы. Режим: {args.mode}; оружие: {args.weapon_profile}; комплект: {args.kit}. Журнал: {run}',flush=True)
            if args.boat_practice:
                print('BoatPractice: фиксированный старт на лодке203. После приземления F — водитель, W/S — ход/тормоз, F — выход в воду; WASD — плавание.',flush=True)
            if args.climb_practice:
                print('ClimbPractice: оставьте комплект кирок; место появления фиксировано у скалы. После приземления повернитесь к203° по компасу, F — кирки, W/S — вверх/вниз, F — выход.',flush=True)
            print('Training: во время подготовки выберите клетку и комплект. Без выбора используется начальный пресет.',flush=True)
            if args.mode == 'walk':
                print('Walk: без таймеров закрытия зон; дроп и вертолёт — отдельные события. Для цикла используйте -Mode cycle.',flush=True)
            watched.extend([('lobby',lobby),('proxy',proxy),('endpoint',peer)])
            if args.lan_tunnel:
                bridge,log=start('udp-tunnel',[sys.executable,'-B','-u',str(ROOT/'tools/lan_tunnel_2022.py'),'server','--profile',args.profile,'--duration',str(args.duration)])
                wait_ready(bridge,log,'"kind": "ready"')
                watched.append(('udp-tunnel',bridge))
                print('SSH backend готов: TCP127.0.0.1:8001 иUDP tunnel TCP127.0.0.1:19001. Один активный клиент.',flush=True)
        game=None
        if not args.services_only:
            if args.debug_console:
                from debug_console_2022 import DebugConsoleSession
                debug_session=DebugConsoleSession(runtime,run)
                command=debug_session.install()
                print('DebugConsole: в игре Enter, команда из '+str(run/'client-debug-command.txt')+' затем Enter. '+command,flush=True)
            client_log=(run/'client.log').open('w',encoding='utf-8');handles.append(client_log)
            game=subprocess.Popen([str(runtime/'Europa_Client.exe'),'-language=en','-garena','-uid=1','-server=127.0.0.1:8001'],cwd=runtime,stdout=client_log,stderr=subprocess.STDOUT)
            processes.append(game)
            if job:job.add(game)
            print('Закройте Event Center/Escape, Play → Training → Start Matchmaking. Дождитесь47с экрана подготовки; в обычном профиле клетка задаёт место появления. WASD/мышь,1/2 — оружейные слоты,R — перезарядка,Tab — инвентарь,F — подбор/транспорт. Для конца закройте игру или Ctrl+C.',flush=True)
            if args.target != 'none':
                print('Мишень стоит восточнее стартового лута, около Jeep. Она не атакует. Попадания/HP/прочность записываются в scene/events.jsonl. Это учебный баланс; для новой мишени перезапустите сеанс.',flush=True)
        deadline=time.monotonic()+args.duration
        while time.monotonic()<deadline:
            for name,service in watched:
                if service.poll() is not None:raise RuntimeError(f'{name} завершился, см. {run}')
            if game and game.poll() is not None:
                if game.returncode:raise RuntimeError(f'Клиент завершился с кодом {game.returncode}; см. {run}')
                break
            time.sleep(.5)
        return 0
    finally:
        for process in reversed(processes):
            if process.poll() is None:process.terminate()
        for process in reversed(processes):
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
        for handle in handles:handle.close()
        if job:job.close()
        if debug_session:debug_session.close()
        print('Собственные процессы сеанса остановлены',flush=True)


if __name__=='__main__':
    try:raise SystemExit(main())
    except KeyboardInterrupt:raise SystemExit(0)
    except Exception as error:
        print('Ошибка: '+str(error),file=sys.stderr,flush=True);raise SystemExit(1)
