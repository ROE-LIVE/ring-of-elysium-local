"""Выбор зимней способности и исходного состава набора до спавна2022.

InitItem.xml map16010/stage1: выбор1→200907,2→200906,3→200904.
ChooseInventoryPanelLogic.lua:149 отправляет RAW_ATTR_SET_REQ для ATR_INIT_EQUIP_1.
"""
from dataclasses import replace
import json
from pathlib import Path
import struct

WINTER_CHOICES = {1: 200907, 2: 200906, 3: 200904}
# Первичный INITITEM.XML map16010/stage1, строки217–268. Начальный
# магазин и положение оружия не заданы таблицей; их политика остаётся нашей.
WINTER_STARTER_ITEMS = {
    1: ((20002, 1), (30003, 15), (70001, 5), (200907, 1)),
    2: ((20003, 1), (30006, 10), (70001, 5), (200906, 1)),
    3: ((10402, 1), (30004, 10), (70001, 5), (200904, 1)),
}


def load_spawn_points(path=None, map_id=16010):
    """660 допустимых исходных клеток; высоты — проверяемые оценки коллеги.

    path задаёт опытный каталог другой карты в том же формате [cx, cy, x, y, z].
    """
    source = Path(path) if path else Path(__file__).with_name('winter_spawn_points_2022.json')
    config = json.loads(source.read_text(encoding='utf-8'))
    points = config['points']
    if config.get('map_id') != map_id or not 1 <= len(points) <= 1024:
        raise ValueError('Нужен ограниченный каталог рождения map%d' % map_id)
    if any(len(p) != 5 or any(type(x) is not int for x in p)
           or not all(0 <= x <= 31 for x in p[:2])
           or not all(0 < x < 1000000 for x in p[2:]) for p in points):
        raise ValueError('Неверные клетки или координаты рождения')
    if len({tuple(p[:2]) for p in points}) != len(points):
        raise ValueError('Повтор клетки рождения')
    return tuple(tuple(p) for p in points)


def choose_cell(payload, actor_uid, now, deadline, inventory_started, points):
    if len(payload) != 24:
        raise ValueError('BORN_POS_REQ ожидает24байта')
    kind, uid, x, y, trailing_flag = struct.unpack('>IQIII', payload)
    # Клиенты Desert/KillZone шлют trailing=0xFFFFFFFF («не задан»; так же у MLVP), Dione 0..1.
    if uid != actor_uid or x > 31 or y > 31 or trailing_flag not in (0, 1, 0xFFFFFFFF):
        return None, [], {'action': 'born_position_rejected', 'reason': 'identity_or_cell',
                          'request_kind': kind, 'actor_matches': uid == actor_uid,
                          'requested_cell': [x, y], 'request_flag': trailing_flag}
    if deadline is None or now >= deadline or inventory_started:
        return None, [], {'action': 'born_position_rejected', 'reason': 'closed'}
    if kind != 2:
        return None, [(0x11e0, struct.pack('>II', 0, 2)),
                      (0x11e2, struct.pack('>III', 2, 0, 0))], {
            'action': 'born_position_resync', 'reason': 'born_type'}
    point = min(points, key=lambda p: ((p[0]-x)**2+(p[1]-y)**2, p[0], p[1]))
    response = struct.pack('>IIQIII', 1, 2, actor_uid, point[0], point[1], 0)
    return point, [(0x11e0, response)], {
        'action': 'born_position_selected', 'requested_cell': [x, y],
        'selected_cell': list(point[:2]), 'position': list(point[2:]),
        'request_flag': trailing_flag, 'height_basis': 'team_l_estimate',
        'snapped': point[:2] != (x, y),
    }


def default_choice(fixture):
    if fixture is None:
        return None
    return next((choice for choice, definition in WINTER_CHOICES.items()
                 if definition in fixture.starting_equipment), None)


def selected_fixture(fixture, choice):
    """Состав InitItem включается явно; старые диагностические профили сохраняются."""
    if fixture is not None and fixture.winter_starter_inventory and choice is None:
        choice = default_choice(fixture)
    if choice not in WINTER_CHOICES or default_choice(fixture) is None:
        return fixture
    equipment = tuple(x for x in fixture.starting_equipment
                      if x not in WINTER_CHOICES.values()) + (WINTER_CHOICES[choice],)
    if fixture.winter_starter_inventory:
        items = WINTER_STARTER_ITEMS[choice]
        return replace(fixture, starting_equipment=(WINTER_CHOICES[choice],),
                       gun_on_start=True, reserve=10 if choice == 3 else 0,
                       starter_items=items)
    return replace(fixture, starting_equipment=equipment)


def choose(command, payload, now, deadline, inventory_started):
    """Ответы штатного raw-attribute протокола; поздние запросы не меняют инвентарь."""
    if command == 0x10cc:
        if len(payload) != 8:
            raise ValueError('RAW_ATTR_SET_REQ ожидает8байт')
        index, value = struct.unpack('>II', payload)
        if index != 1:
            return None
    elif command == 0xbfc:
        if len(payload) != 4:
            raise ValueError('SET_INIT_EQUIP_REQ ожидает4байта')
        value = struct.unpack('>I', payload)[0]
    else:
        return None
    accepted = value in WINTER_CHOICES and deadline is not None and now < deadline and not inventory_started
    replies = [(0x10d0, struct.pack('>II', 1, value))] if accepted else []
    if command == 0x10cc:
        replies.append((0x10cd, payload + struct.pack('>I', int(not accepted))))
    else:
        replies.append((0xbfd, struct.pack('>II', int(not accepted), value)))
    return (value if accepted else None), replies, {
        'action': 'winter_loadout_choice' if accepted else 'winter_loadout_rejected',
        'choice': value, 'inventory_started': inventory_started,
        'reason': None if accepted else ('choice' if value not in WINTER_CHOICES else 'closed'),
        'original_starter_inventory': False,
    }


# InitItem map16021 (TableBin #0x96c): этап1 передвижение 1 Motor200908, 2 Glider200901,
# 3 BMX200902, 4 Grappling200903; этап2 тактика (70020…70026, 20006); этап3 оружие.
# Peer знает только зимние комплекты, поэтому передвижение заменяется поддержанным:
# Glider/Motor/BMX → планер200907, Grappling → скалолазный200904. Тактика не выдаётся.
STAGED_MAPS = (16021,)
DESERT_TRAVERSAL = {1: (200908, 200907), 2: (200901, 200907), 3: (200902, 200907), 4: (200903, 200904)}
DESERT_WEAPONS = {
    1: ((20002, 1), (30003, 30), (70001, 5)),
    2: ((20003, 1), (30006, 10), (70001, 5)),
    3: ((10402, 1), (30004, 6), (70001, 5)),
}
DESERT_DEFAULT = {1: 2, 3: 1}
# Индекс RAW_ATTR этапа по живому клиенту16021 (сессии20261026T015031/015748):
# передвижение1, тактика20 (значения1/3/7 есть только в тактике), оружие31 (клик Citori=3
# во время выбора). 18 приходит до начала выбора со значением1 — принимается как оружие,
# но обычно отклоняется как ранний. Вывод из наблюдения, не из таблицы атрибутов.
STAGE_BY_ATTR = {1: 1, 20: 2, 31: 3, 18: 3}
ATTR_BY_STAGE = {1: 1, 2: 20, 3: 31}


def staged_fixture(fixture, loadout):
    """Стартовый набор многоэтапной карты: оружие этапа3 + заменённое передвижение этапа1."""
    if fixture is None or not fixture.winter_starter_inventory:
        return fixture
    traversal, weapon = loadout.get(1, DESERT_DEFAULT[1]), loadout.get(3, DESERT_DEFAULT[3])
    kit = DESERT_TRAVERSAL.get(traversal, DESERT_TRAVERSAL[DESERT_DEFAULT[1]])[1]
    items = DESERT_WEAPONS.get(weapon, DESERT_WEAPONS[DESERT_DEFAULT[3]]) + ((kit, 1),)
    reserve = dict(items).get(30004, 0) if weapon == 3 else 0
    return replace(fixture, starting_equipment=(kit,), gun_on_start=True, reserve=reserve, starter_items=items)


def choose_staged(command, payload, now, deadline, inventory_started):
    """RAW_ATTR_SET_REQ этапов1..3 карты16021; ответ тем же индексом этапа."""
    if command != 0x10cc:
        return None
    if len(payload) != 8:
        raise ValueError('RAW_ATTR_SET_REQ ожидает8байт')
    attr, value = struct.unpack('>II', payload)
    stage = STAGE_BY_ATTR.get(attr)
    valid = {1: DESERT_TRAVERSAL, 3: DESERT_WEAPONS}.get(stage)
    known = valid is not None and value in valid or stage == 2 and 1 <= value <= 8
    accepted = known and deadline is not None and now < deadline and not inventory_started
    replies = [(0x10d0, struct.pack('>II', attr, value))] if accepted else []
    replies.append((0x10cd, payload + struct.pack('>I', int(not accepted))))
    event = {'action': 'staged_loadout_choice' if accepted else 'staged_loadout_rejected',
             'stage': stage, 'attr_index': attr, 'choice': value, 'inventory_started': inventory_started,
             'reason': None if accepted else ('choice' if not known else 'closed'),
             'supported': stage != 2, 'original_starter_inventory': False}
    if stage == 1 and value in DESERT_TRAVERSAL:
        event.update(original_item=DESERT_TRAVERSAL[value][0], substitute_item=DESERT_TRAVERSAL[value][1])
    return (stage, value) if accepted else None, replies, event
