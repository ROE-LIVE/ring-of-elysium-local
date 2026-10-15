"""Сверка локального каталога с четырьмя публичными таблицами2022.

Постоянство одежды и объединение одинаковых моделей — явная offline-policy.
Наличие строки не доказывает её продажу/активность на историческом сервере.
"""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

from local_cosmetics_2022 import LocalCosmetics

TABLES = {
    'owned_gun_skin_ids': ('000002cf.xml', 'mWeaponSkins', 'mSkinId'),
    'owned_character_ids': ('00000989.xml', 'm_Items', 'ID'),
    'owned_accessory_ids': ('000005fb.xml', 'm_Items', 'ID'),
    'owned_clothing_ids': ('00000a89.xml', 'mItems', 'dwStringID'),
}
# Native339: public OnSaveEquip/send и позиции первичной00000A89.
CLOTHING_SLOTS = dict(GLASSES=13,MASK=14,SHIRT=15,COAT=16,GLOVE=17,PANT=18,SHOE=19,HAT=22)
CLOTHING_POSITIONS = set(CLOTHING_SLOTS)


def table_rows(path, tag, key):
    path = Path(path)
    if path.stat().st_size > 2 * 1024 * 1024:
        raise ValueError('Таблица превышает2МиБ')
    raw = path.read_bytes()
    text = raw.decode('utf-8-sig')
    if '<!DOCTYPE' in text.upper() or '<!ENTITY' in text.upper():
        raise ValueError('DTD/ENTITY не разрешены в публичной таблице')
    clean = re.sub(r'\s+\[XlsProp\]="[^"]*"', '', text)
    root = ET.fromstring(clean)
    rows = [dict(item.attrib) for item in root.iter(tag) if item.get(key) is not None]
    if not rows:
        raise ValueError(f'Нет записей {tag}/{key}')
    unique, duplicates = {}, []
    for row in rows:
        identifier = int(row[key])
        if not 0 < identifier <= 0xffffffff:
            raise ValueError('ID внеU32')
        if identifier in unique:
            if unique[identifier] != row:
                raise ValueError(f'Конфликт строк ID{identifier}')
            duplicates.append(identifier)
        else:
            unique[identifier] = row
    return unique, dict(file=str(path), sha256=hashlib.sha256(raw).hexdigest(),
                        row_count=len(rows), unique_count=len(unique),
                        identical_duplicate_ids=sorted(set(duplicates)))


def build_catalog(tables):
    tables = Path(tables)
    catalog, evidence, loaded = {}, {}, {}
    for category, (file, tag, key) in TABLES.items():
        loaded[category], evidence[category] = table_rows(tables / file, tag, key)
        catalog[category] = sorted(loaded[category])
    catalog['character_groups'] = {
        str(identifier): int(row['group_id'])
        for identifier, row in loaded['owned_character_ids'].items()
    }
    groups = defaultdict(list)
    temporary = []
    for identifier, row in loaded['owned_clothing_ids'].items():
        if row.get('szPosition') not in CLOTHING_POSITIONS:
            continue
        duration = int(row.get('nExpireDuration', 0))
        if duration < 0:
            raise ValueError('Отрицательный срок одежды')
        if duration:
            temporary.append(identifier)
            continue
        visual = tuple(row.get(key) for key in ('szPosition', 'szAvatar3D_b', 'szAvatar3D_d'))
        if not all(visual):
            raise ValueError(f'Одежда{identifier} без пары моделей')
        groups[visual].append(identifier)
    catalog['owned_clothing_ids'] = sorted(min(ids) for ids in groups.values())
    catalog['clothing_inventory_container'] = 6
    catalog['clothing_equipment_slots'] = {
        str(identifier): CLOTHING_SLOTS[loaded['owned_clothing_ids'][identifier]['szPosition']]
        for identifier in catalog['owned_clothing_ids']
    }
    evidence['owned_clothing_ids'].update(
        temporary_ids=sorted(temporary),
        permanent_visual_groups=len(groups),
        permanent_aliases={str(min(ids)): sorted(ids) for ids in groups.values() if len(ids) > 1},
        policy='Минимальный постоянный ID на позицию и пару моделей; срок по умолчанию0')
    evidence['weapon_skin_to_weapon'] = {
        str(identifier): int(row['mWeaponId'])
        for identifier, row in loaded['owned_gun_skin_ids'].items()
    }
    catalog['weapon_skin_to_weapon'] = dict(evidence['weapon_skin_to_weapon'])
    return catalog, evidence


def compare_catalog(expected, actual):
    result = {}
    for category in TABLES:
        ids = actual.get(category, [])
        if not isinstance(ids, list) or any(type(x) is not int for x in ids):
            raise ValueError(f'Неверные ID {category}')
        result[category] = dict(expected_count=len(expected[category]), actual_count=len(ids),
                                missing=sorted(set(expected[category]) - set(ids)),
                                extra=sorted(set(ids) - set(expected[category])),
                                duplicate_ids=sorted(x for x in set(ids) if ids.count(x) > 1))
    result['character_groups_equal'] = expected['character_groups'] == actual.get('character_groups', {})
    result['matches'] = result['character_groups_equal'] and all(
        not result[key]['missing'] and not result[key]['extra'] and not result[key]['duplicate_ids']
        for key in TABLES)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tables', type=Path, required=True, help='Каталог четырёх ordinalXML TableBin')
    parser.add_argument('--compare', type=Path, required=True, help='Проверяемый JSON локального аккаунта')
    parser.add_argument('--output', type=Path, required=True, help='Новый файл отчёта; существующий не перезаписывается')
    args = parser.parse_args()
    expected, evidence = build_catalog(args.tables)
    actual = json.loads(args.compare.read_text(encoding='utf-8'))
    comparison = compare_catalog(expected, actual)
    # Валидация wire-границ не требует игры, ключа или nativeMemory.
    LocalCosmetics(args.compare)
    report = dict(tables=evidence, comparison=comparison,
                  caveat='Наличие в таблице, не доказательство исторической serveravailability')
    with args.output.open('x', encoding='utf-8') as stream:
        stream.write(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(comparison, ensure_ascii=False))
    return 0 if comparison['matches'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
