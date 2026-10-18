"""Инвентарь зимней сессии2022; наш peer, исходная симуляция оружия не восстановлена."""
from collections import deque
from fractions import Fraction
from dataclasses import dataclass, field, replace
import json
import math
from pathlib import Path
import struct
import time

from inventory_codec_2022 import encode_snapshot, encode_delta, decode_discard
from cosmetic_selection_2022 import load_weapon_skins, load_clothing_records
from throwable_inventory_2022 import THROWABLE_PROFILES, THROWABLE_SLOTS, throwable_record, move_throwable

from attachment_probe_2022 import (
    ATTACHMENT_BAG_SLOTS, ATTACHMENT_PROFILES, SUPPORTED_ATTACHMENTS,
    AttachmentInstance, attachment_record, gun_attachment_record, move_attachment,
    EXTENDED_CAPACITIES, pickup_attachment_to_gun)

# Позиции equipment и определения из TableBin/A89; проверка wire в опыте20261007.
EQUIPMENT_SLOTS = {201001: 12, 201002: 12, 201003: 12, 201004: 12,
                   200101: 10, 200102: 10, 200103: 10, 200104: 10,
                   200904: 11, 200906: 11, 200907: 11}

# TableBin/A89: способность и вместимость зимних наборов. Индексы RAW_ATR
# подтверждены публичными descriptor142d94e88/eb8/ee8 и handler140eaee10.
# Вместимость — EU attribute5; это отдельная синхронизация, не свойство5fb.
WINTER_KITS = {200907: (2, 150), 200906: (3, 225), 200904: (4, 300)}


# TableBin/A89 nDurableValue; wire record+32 -> native item+9e -> obj+3c.
# UI показывает значение/10. Снижение урона и расход прочности не восстановлены.
ARMOR_DURABILITY = {200101: 800, 200102: 1500, 200103: 2300, 200104: 3000,
                    201001: 2000, 201002: 2200, 201003: 2500, 201004: 3000}

# TableBin/A81, строки 4/19: 5.56 = 0.5, 12ga = 1.25, nPackMax = 999.
# Целые сотые веса исключают float-ошибку на границе полной сумки.
# Citori использует30004 вslot1; остальные bag refs — наша раскладка.
AMMUNITION_WEIGHTS = {30004: 125, 30001: 50, 30002: 58, 30005: 40}
# A81:9мм вес0.375. Fraction сохраняет половину сотой без float округления.
# Новые номера bag slots — наша свободная раскладка, не исходная нумерация.
AMMUNITION_WEIGHTS.update({30003: Fraction(75, 2), 30006: 100, 30009: 1000})
AMMUNITION_SLOTS = {30004: 1, 30001: 2, 30002: 6, 30005: 8,
                    30003: 7, 30006: 9, 30009: 10}

# TableBin/A81, строки79/84/89: вес, mHealValue, nSinging (секунды).
MEDICAL_PROFILES = {70001: (200, 100, 3.0), 70002: (1200, 500, 6.0),
                    70003: (2000, 1000, 8.0)}
MEDICAL_SLOTS = {70001: 3, 70002: 4, 70003: 5}


def medical_record(definition, quantity):
    """ITEM_DATA type2/category7; decoder140bcf790→140bcefb0, cold53."""
    if definition not in MEDICAL_PROFILES or type(quantity) is not int or not 1 <= quantity <= 999:
        raise ValueError('Неверная стопка расходника')
    record = bytearray(80)
    record[:4] = bytes((2, MEDICAL_SLOTS[definition], 2, 0))
    struct.pack_into('>IQ', record, 4, definition, 0x1e00000000000000 + definition)
    struct.pack_into('>H', record, 30, 1)
    record[32] = 7
    struct.pack_into('>H', record, 78, quantity)
    return bytes(record)

# TableBin/A89, строки 268/744: тип патронов и базовый магазин.
# Исходные ammo/capacity; generic fire/reload не заменяет полную баллистику.
GUN_PROFILES = {10402: (30004, 2), 10201: (30001, 30),
                10101: (30001, 5), 10102: (30002, 5),
                10202: (30002, 30), 20001: (30005, 12), 20002: (30003, 17)}
# Дополнительные определения исходного зимнего pool: A89, сверка SFC
# loot-primary-sfc-verification.json. Это поддержка pickup/reload, не баллистика.
GUN_PROFILES.update({10104: (30002, 10),
 10105: (30006, 5),
 10107: (30001, 20),
 10110: (30002, 20),
 10203: (30002, 30),
 10204: (30001, 30),
 10205: (30002, 30),
 10206: (30001, 30),
 10208: (30001, 30),
 10301: (30003, 30),
 10303: (30003, 19),
 10305: (30003, 20),
 10306: (30003, 30),
 10401: (30004, 5),
 10403: (30004, 5),
 10601: (30002, 100),
 10605: (30009, 1),
 20003: (30006, 7)})
HANDGUN_PROFILES = {20001, 20002, 20003}
# A89 nBulletLoadTime/nNeBulletLoadTime: пустой/непустой магазин, секунды.
RELOAD_TIMES = {10402: (2.130, 1.480), 10201: (2.567, 2.083),
                10101: (3.933, 3.030), 10102: (3.170, 2.570),
                10202: (3.070, 2.200), 20001: (1.500, 1.500),
                20002: (2.030, 1.600)}
# A89/889 не содержит nNeBulletLoadTime USP45; повтор1.5с — политика peer.
RELOAD_TIMES.update({10104: (2.7, 2.45),
 10105: (4.25, 3.34),
 10107: (2.7, 2.2),
 10110: (3.29, 2.64),
 10203: (2.75, 2.0),
 10204: (2.54, 2.24),
 10205: (2.5, 1.7),
 10206: (3.1, 2.41),
 10208: (3.54, 2.58),
 10301: (3.43, 2.8),
 10303: (2.77, 2.2),
 10305: (3.1, 2.27),
 10306: (2.75, 2.3),
 10401: (1.16, 1.16),
 10403: (3.0, 2.33),
 10601: (10.4, 10.4),
 10605: (3.133, 3.133),
 20003: (2.24, 1.6)})
# R870/RPG без nNeBulletLoadTime: повтор empty-time — политика peer.
# Поочерёдное заряжание R870 и original projectile/RPG пока не восстановлены.


def encode_item_delta(actor_uid, container, slot, record, own=True):
    """3e82 собственного actor: own0 выбирает его world inventory."""
    return 0x3e82, encode_delta(container, slot, record[2:], actor_uid, own)


def equipment_record(template, definition, durability=None):
    if len(template) != 82 or definition not in EQUIPMENT_SLOTS:
        raise ValueError('Нужна разобранная equipment-запись и поддержанное определение')
    # Чистый item union с собственной прочностью брони из A89.
    # Round-trip writer140c282c0/decoder140c28460 совпал побайтно.
    record = bytearray(82)
    record[:4] = bytes((1, EQUIPMENT_SLOTS[definition], 1, 0))
    struct.pack_into('>I', record, 4, definition)
    struct.pack_into('>Q', record, 8, 0x1e00000000000000 + definition)
    maximum = ARMOR_DURABILITY.get(definition, 0)
    if durability is None:
        durability = maximum
    if type(durability) is not int or not 0 <= durability <= maximum:
        raise ValueError('Прочность вне диапазона выбранной брони')
    struct.pack_into('>I', record, 32, durability)
    struct.pack_into('>H', record, 80, 1)
    return bytes(record)


@dataclass(frozen=True)
class LootFixture:
    entity_uid: int
    index: int
    quantity: int
    position: tuple
    acknowledgement: bytes
    definition: int = 30004
    entity: bytes = b''
    clip: int | None = None
    durability: int | None = None
    instance_uid: int | None = None
    parts: tuple = ()
    skin_id: int | None = None


    @classmethod
    def load(cls, directory, config):
        entity = (directory / config['entity_file']).read_bytes()
        acknowledgement = (directory / config['acknowledgement_file']).read_bytes()
        # Ограниченные варианты ammo, Citori и equipment, не произвольный union.
        definition = struct.unpack_from('>I', entity, 63)[0] if len(entity) == 100 else None
        if (len(entity) != 100 or struct.unpack_from('>I', entity)[0] != 30201002
                or struct.unpack_from('>I', entity, 12)[0] != 13
                or struct.unpack_from('>I', entity, 46)[0] != 1
                or entity[62] != 2 or definition not in (*AMMUNITION_WEIGHTS, *GUN_PROFILES, *EQUIPMENT_SLOTS, *MEDICAL_PROFILES, *SUPPORTED_ATTACHMENTS, *THROWABLE_PROFILES)
                or len(acknowledgement) != 45 or acknowledgement[12] != 1
                or any(acknowledgement[17:])):
            raise ValueError('Нужны поддержанные 821/3b64 для прямого pickup')
        quantity, index = struct.unpack_from('>II', entity, 67)
        if not 1 <= quantity <= 100:
            raise ValueError('Количество лута вне диапазона 1..100')
        if definition not in (*AMMUNITION_WEIGHTS, *MEDICAL_PROFILES, *THROWABLE_PROFILES) and quantity != 1:
            raise ValueError('Equipment fixture должна содержать один предмет')
        acknowledgement = (struct.pack('>IIIBI', index, 0, quantity, 1, definition)
                           + acknowledgement[17:])
        durability = config.get('durability')
        if durability is not None and (definition not in ARMOR_DURABILITY
                or type(durability) is not int or not 0 <= durability <= ARMOR_DURABILITY[definition]):
            raise ValueError('durability требует поддержанную броню и целое значение0..maximum')
        return cls(struct.unpack_from('>Q', entity, 4)[0], index, quantity,
                   struct.unpack_from('>3i', entity, 29), acknowledgement, definition, entity,
                   durability=durability)


@dataclass
class GunInstance:
    definition: int
    clip: int
    uid: int
    parts: dict = field(default_factory=dict)
    skin_id: int = 0


@dataclass(frozen=True)
class WeaponFixture:
    gun: bytes
    ammunition: bytes
    capacity: int = 2
    reserve: int = 6
    loot: LootFixture | None = None
    additional_loot: tuple = ()
    gun_on_start: bool = True
    starting_equipment: tuple = ()
    weapon_slots: int = 1
    reload_update: str = 'snapshot'
    timed_reload: bool = False
    inventory_update: str = 'snapshot'
    handgun_slot: bool = False
    combat_armor_absorb_percent: int = 0
    throwable_actions: bool = False
    diagnostic_frag_damage: int = 0
    cosmetics_config_file: Path | None = None
    winter_starter_inventory: bool = False
    starter_items: tuple = ()

    @property
    def all_loot(self):
        return ((self.loot,) if self.loot else ()) + self.additional_loot

    @classmethod
    def load(cls, path):
        path = Path(path)
        config = json.loads(path.read_text())
        gun = (path.parent / config['gun_inventory_file']).read_bytes()
        ammunition = (path.parent / config['ammunition_inventory_file']).read_bytes()
        # Поддержан только разобранный вариант: одна Citori и 12ga без имени.
        if (len(gun) != 95 or gun[:8] != bytes.fromhex('0000000101010100')
                or struct.unpack_from('>I', gun, 8)[0] != 10402
                or len(ammunition) != 73
                or ammunition[:8] != bytes.fromhex('0000000102010200')
                or struct.unpack_from('>I', ammunition, 8)[0] != 30004
                or gun[-1] != 1 or ammunition[-1] != 1):
            raise ValueError('Нужны проверенные записи Citori 10402 и патронов 30004')
        reserve = struct.unpack_from('>H', ammunition, len(ammunition)-11)[0]
        if not 1 <= reserve <= 100:
            raise ValueError('Запас патронов вне диапазона 1..100')
        loot = LootFixture.load(path.parent, config['loot']) if config.get('loot') else None
        extra = config.get('additional_loot', [])
        if not isinstance(extra, list) or len(extra) > 31:
            raise ValueError('Нужно не более31 дополнительных точек лута')
        additional = tuple(LootFixture.load(path.parent, row) for row in extra)
        items = ((loot,) if loot else ()) + additional
        if len({x.index for x in items}) != len(items) or len({x.entity_uid for x in items}) != len(items):
            raise ValueError('Повторный index или entity_uid лута')
        gun_on_start = config.get('gun_on_start', True)
        if type(gun_on_start) is not bool:
            raise ValueError('gun_on_start должен быть bool')
        winter_starter_inventory = config.get('winter_starter_inventory', False)
        if type(winter_starter_inventory) is not bool:
            raise ValueError('winter_starter_inventory должен быть bool')
        starting = config.get('starting_equipment', [])
        if not isinstance(starting, list) or any(type(x) is not int or x not in EQUIPMENT_SLOTS for x in starting):
            raise ValueError('Неподдержанное стартовое снаряжение')
        if len({EQUIPMENT_SLOTS[x] for x in starting}) != len(starting):
            raise ValueError('Одновременно допустим один предмет на equipment-позиции')
        slots = config.get('weapon_slots', 1)
        if type(slots) is not int or slots not in (1, 2, 3):
            raise ValueError('Поддержаны один, два или три оружейных слота')
        reload_update = config.get('reload_update', 'snapshot')
        if reload_update not in ('snapshot', 'delta'):
            raise ValueError('Обновление reload: snapshot или delta')
        timed_reload = config.get('timed_reload', False)
        if type(timed_reload) is not bool or (timed_reload and reload_update != 'delta'):
            raise ValueError('timed_reload требует bool и reload_update=delta')
        inventory_update = config.get('inventory_update', 'snapshot')
        if inventory_update not in ('snapshot', 'delta'):
            raise ValueError('inventory_update требует snapshot или delta')
        handgun_slot = config.get('handgun_slot', False)
        if type(handgun_slot) is not bool:
            raise ValueError('handgun_slot должен быть bool')
        combat_armor_absorb_percent = config.get('combat_armor_absorb_percent', 0)
        if (type(combat_armor_absorb_percent) is not int
                or not 0 <= combat_armor_absorb_percent <= 100):
            raise ValueError('Учебное поглощение бронёй требует целое0..100')
        throwable_actions = config.get('throwable_actions', False)
        diagnostic_frag_damage = config.get('diagnostic_frag_damage', 0)
        if (type(throwable_actions) is not bool
                or type(diagnostic_frag_damage) is not int
                or not 0 <= diagnostic_frag_damage <= 1000
                or diagnostic_frag_damage and not throwable_actions):
            raise ValueError('Учебный урон гранаты0..1000 требует throwable_actions=true')
        cosmetics_path = config.get('cosmetics_config_file')
        if cosmetics_path is not None:
            if not isinstance(cosmetics_path, str) or not cosmetics_path:
                raise ValueError('cosmetics_config_file требует путь каталога')
            cosmetics_path = path.parent / cosmetics_path
            load_weapon_skins(cosmetics_path)
        return cls(gun[4:-9], ammunition[4:-9], reserve=reserve, loot=loot,
                   additional_loot=additional, gun_on_start=gun_on_start,
                   starting_equipment=tuple(starting), weapon_slots=slots,
                   reload_update=reload_update, timed_reload=timed_reload,
                   inventory_update=inventory_update, handgun_slot=handgun_slot,
                   combat_armor_absorb_percent=combat_armor_absorb_percent,
                   throwable_actions=throwable_actions,
                   diagnostic_frag_damage=diagnostic_frag_damage,
                   cosmetics_config_file=cosmetics_path,
                   winter_starter_inventory=winter_starter_inventory)


class WeaponState:
    def __init__(self, fixture, actor_uid):
        self.fixture = fixture
        self.guns = {}
        self.selected_slot = 1
        self.instance_counter = 0
        self.instance_allocator = None
        # Новый матч читает последний сохранённый выбор, а не снимок preflight.
        self.skin_selection = (load_weapon_skins(fixture.cosmetics_config_file)
                               if fixture.cosmetics_config_file else {})
        self.cosmetic_clothes = (load_clothing_records(fixture.cosmetics_config_file)
                                if fixture.cosmetics_config_file else {})
        if fixture.gun_on_start:
            uid = struct.unpack_from('>Q', fixture.gun, 8)[0]
            definition = next((definition for definition, _ in fixture.starter_items
                               if definition in GUN_PROFILES), 10402)
            skin = self.skin_selection.get(definition, struct.unpack_from('>I', fixture.gun, 72)[0]
                                           if definition == 10402 else 0)
            capacity = fixture.capacity if definition == 10402 else GUN_PROFILES[definition][1]
            self.guns[1] = GunInstance(definition, capacity, uid or self.new_instance_uid(), skin_id=skin)
        self.actor_uid = actor_uid
        self.reserve = fixture.reserve
        self.extra_ammunition = {}
        self.medical = {}
        for definition, quantity in fixture.starter_items:
            if definition in AMMUNITION_SLOTS:
                self.set_ammunition_quantity(definition, quantity)
            elif definition in MEDICAL_PROFILES:
                self.medical[definition] = quantity
        self.throwables = {}
        self.known_throwable_slots = set()
        self.equipped_throwables = {}
        self.known_equipped_throwable_slots = set()
        self.attachments = {}
        self.known_attachment_slots = set()
        self.hand_slot = 0
        self.shots = deque(maxlen=64)
        self.loot_available = False
        self.loot_picked = False
        self.available_loot = set()
        self.picked_loot = set()
        self.equipment = {EQUIPMENT_SLOTS[x]: x for x in fixture.starting_equipment}
        self.equipment_durability = {slot: ARMOR_DURABILITY.get(definition, 0)
                                     for slot, definition in self.equipment.items()}
        self.loot_registry = {item.index: item for item in fixture.all_loot}
        self.ground_template = next((x.entity for x in fixture.all_loot if x.entity), None)
        self.position = None
        self.drop_counter = 0
        self.ground_allocator = None
        self.pending_reload = None

    def new_instance_uid(self):
        if self.instance_allocator is not None:
            return self.instance_allocator()
        self.instance_counter += 1
        return 0x1e00000100000000 + self.instance_counter

    @property
    def gun_owned(self):
        return bool(self.guns)

    @gun_owned.setter
    def gun_owned(self, owned):
        # Совместимость адресных старых опытов; игровой путь использует registry.
        if not owned:
            self.guns.clear()
        elif not self.guns:
            self.guns[1] = GunInstance(10402, 0, self.new_instance_uid())

    @property
    def gun_definition(self):
        gun = self.guns.get(self.selected_slot)
        return gun.definition if gun else 10402

    @gun_definition.setter
    def gun_definition(self, definition):
        self.guns[self.selected_slot].definition = definition

    @property
    def clip(self):
        gun = self.guns.get(self.selected_slot)
        return gun.clip if gun else 0

    @clip.setter
    def clip(self, value):
        if self.selected_slot in self.guns:
            self.guns[self.selected_slot].clip = value

    def magazine_syncs(self):
        return [(0x4a0, self.ammunition_sync(slot=slot)) for slot in sorted(self.guns)]

    @property
    def bag_capacity(self):
        return WINTER_KITS.get(self.equipment.get(11), (0, 100))[1]

    @property
    def gun_ammunition(self):
        return GUN_PROFILES[self.gun_definition][0]

    @property
    def magazine_capacity(self):
        return self.gun_magazine_capacity(self.guns[self.selected_slot])

    def gun_magazine_capacity(self, gun):
        if 3 in gun.parts and gun.parts[3].definition in (40401, 40403, 40405):
            return EXTENDED_CAPACITIES.get(gun.definition, self.base_magazine_capacity(gun.definition))
        return self.base_magazine_capacity(gun.definition)

    def base_magazine_capacity(self, definition):
        return self.fixture.capacity if definition == 10402 else GUN_PROFILES[definition][1]

    @staticmethod
    def ammunition_definition(definition):
        return GUN_PROFILES[definition][0]

    @staticmethod
    def ammunition_weight(definition):
        return AMMUNITION_WEIGHTS[definition]

    def ammunition_slot_sync(self, definition):
        slot = AMMUNITION_SLOTS[definition]
        return self.item_delta(2, slot, self.ammunition_record(definition))

    def capacity_sync(self):
        # Веса A81; integer UI в 6f5.
        # Округление вниз — явное правило локального peer, не факт сервера ROE.
        return 0x6f5, struct.pack('>I', self.bag_weight_hundredths() // 100)

    def ammunition_quantity(self, definition):
        return self.reserve if definition == 30004 else self.extra_ammunition.get(definition, 0)

    def set_ammunition_quantity(self, definition, quantity):
        if definition == 30004:
            self.reserve = quantity
        elif quantity:
            self.extra_ammunition[definition] = quantity
        else:
            self.extra_ammunition.pop(definition,None)

    def bag_weight_hundredths(self):
        return self.reserve * AMMUNITION_WEIGHTS[30004] + sum(
            quantity * AMMUNITION_WEIGHTS[definition]
            for definition,quantity in self.extra_ammunition.items()) + sum(
            quantity * MEDICAL_PROFILES[definition][0]
            for definition,quantity in self.medical.items()) + sum(
            ATTACHMENT_PROFILES[item.definition][2] for item in self.attachments.values()) + sum(
            quantity * THROWABLE_PROFILES[definition][0]
            for definition,quantity in self.throwables.items()) + sum(
            quantity * THROWABLE_PROFILES[definition][0]
            for definition,quantity in self.equipped_throwables.values())

    def throwable_room(self, definition):
        available = max(0, self.bag_capacity * 100 - self.bag_weight_hundredths())
        weight, maximum = THROWABLE_PROFILES[definition]
        return max(0, min(maximum - self.throwables.get(definition, 0), available // weight))

    def medical_room(self, definition):
        available = max(0, self.bag_capacity * 100 - self.bag_weight_hundredths())
        return max(0, min(999 - self.medical.get(definition, 0),
                          available // MEDICAL_PROFILES[definition][0]))

    def ammunition_room(self, definition):
        available = max(0, self.bag_capacity * 100 - self.bag_weight_hundredths())
        return max(0, min(999 - self.ammunition_quantity(definition),
                          available // AMMUNITION_WEIGHTS[definition]))

    def clear_slot(self, container, slot):
        # 3e82: count1, BEH(index), B(container), EMPTY_ITEM_DATA37, Bown,Qactor.
        # Порядок ref отличается от5fb и3e80; decoder140bd4d60,
        # handler140e163e0 передаёт container/index в140fb0700.
        return 0x3e82, encode_delta(container, slot, bytes(37), self.actor_uid)

    def item_delta(self, container, slot, record):
        # Native140bd4d60: BE16 slot, U8 container, ITEM_DATA безref5fb.
        # Union тот же; полный ammo delta71B подтверждён cold46.
        # Native00418.10: flag0 не применяет pickup в выбранном own-профиле
        # (нет hand2/резерва M4), поэтому gameplay сохраняет проверенный flag1.
        return encode_item_delta(self.actor_uid, container, slot, record)

    def slot_sync(self, container, slot):
        record = next((record for record in self.inventory_records()
                       if (record[0], record[1]) == (container, slot)), None)
        return (self.item_delta(container, slot, record) if record is not None
                else self.clear_slot(container, slot))

    def ammunition_record(self, definition):
        record = bytearray(self.fixture.ammunition)
        record[:4] = bytes((2, AMMUNITION_SLOTS[definition], 2, 0))
        if definition != 30004:
            struct.pack_into('>IQ', record, 4, definition, 0x1e00000000000000 + definition)
        struct.pack_into('>H', record, len(record)-2, self.ammunition_quantity(definition))
        return bytes(record)

    def update_position(self, position):
        if (len(position) != 3 or any(type(v) is not int or not -2147483648 <= v <= 2147483647 for v in position)):
            raise ValueError('Неверная позиция ног игрока')
        self.position = tuple(position)

    def spawn_discard(self, definition, quantity, position, clip=None, durability=None, instance_uid=None, parts=(), skin_id=None):
        """Новое ground821 из проверенного шаблона, только известные предметы."""
        if not self.ground_template or self.drop_counter >= 256:
            return None
        self.drop_counter += 1
        index = 70000 + self.drop_counter
        while index in self.loot_registry:
            index += 1
        uid = 0x00031d0002000000 + self.drop_counter
        if self.ground_allocator is not None:
            index, uid = self.ground_allocator()
        body = bytearray(self.ground_template)
        struct.pack_into('>Q', body, 4, uid)
        struct.pack_into('>3i', body, 29, *position)
        struct.pack_into('>III', body, 63, definition, quantity, index)
        ack = struct.pack('>IIIBI', index, 0, quantity, 1, definition) + bytes(28)
        item = LootFixture(uid, index, quantity, tuple(position), ack, definition,
                           bytes(body), clip, durability, instance_uid, parts, skin_id)
        self.loot_registry[index] = item
        self.available_loot.add(uid)
        return item

    def gun_fits_slot(self, definition, slot):
        """Три общих слота — отдельный профиль; прежний pistol3 сохранён."""
        if self.fixture.weapon_slots == 3:
            return slot in (1, 2, 3)
        if definition in HANDGUN_PROFILES:
            return self.fixture.handgun_slot and slot == 3
        return 1 <= slot <= self.fixture.weapon_slots

    def move_gun(self, payload):
        """3e80/tag1: две ссылки B/H и Hquantity; decoder140c4ab40."""
        if len(payload) != 10:
            return [], {'action': 'rejected', 'reason': 'move_length'}
        tag, source_container, source, destination_container, destination, quantity, own = struct.unpack(
            '>BBHBHHB', payload)
        if ((source_container == 2 and source in THROWABLE_SLOTS.values())
                or (source_container == 1 and source in (5,6))):
            return move_throwable(self,payload)
        moving = self.guns.get(source)
        previous = self.guns.get(destination)
        checks = {'tag': tag == 1, 'source_container': source_container == 1,
                  'destination_container': destination_container == 1,
                  'source_present': moving is not None,
                  'destination_slot': moving is not None and self.gun_fits_slot(moving.definition, destination),
                  'swap_slot': previous is None or self.gun_fits_slot(previous.definition, source),
                  'quantity': quantity == 1, 'own': own == 1}
        if not all(checks.values()):
            return [], {'action': 'rejected', 'reason': 'move_ref_or_quantity',
                        'failed_checks': [key for key, passed in checks.items() if not passed],
                        'source_container': source_container, 'source_slot': source,
                        'target_container': destination_container, 'target_slot': destination,
                        'quantity': quantity, 'own': own}
        if self.pending_reload:
            return [(0x3e81, struct.pack('>BIIB', 1, 1, self.guns[source].definition, 1))], {
                'action': 'rejected', 'reason': 'move_reload_pending'}
        if source == destination:
            return [self.slot_sync(1, source)], {'action': 'move_noop', 'slot': source}
        moving = self.guns[source]
        previous = self.guns.get(destination)
        self.guns[destination] = moving
        if previous is None:
            del self.guns[source]
        else:
            self.guns[source] = previous
        # Рука/выбранный слот следуют экземпляру, а не старому номеру.
        def remap(slot):
            if slot == source:
                return destination
            if previous is not None and slot == destination:
                return source
            return slot
        self.hand_slot = remap(self.hand_slot)
        self.selected_slot = remap(self.selected_slot)
        replies = [(0x3e81, struct.pack('>BIIB', 1, 0, moving.definition, 1)),
                   self.slot_sync(1, source), self.slot_sync(1, destination)]
        replies.extend(self.magazine_syncs())
        replies.append((0x49f, struct.pack('>II', self.hand_slot, 0)))
        return replies, {'action': 'move_gun', 'source': source, 'destination': destination,
                         'swapped': previous is not None, 'hand_slot': self.hand_slot,
                         'definition': moving.definition, 'instance_uid': hex(moving.uid)}

    def discard(self, payload):
        # Настоящий drag12ga, decoder140c4b470: tag2, ref3, Hqty, I0,I0,B1.
        if len(payload) != 15:
            return [], {'action': 'rejected', 'reason': 'discard_length'}
        # Native140c4ae00: containerU8, slotBE16, quantityBE16, opaqueBE64.
        # Отдельного pageU8 здесь нет: прежний 'page' был старшим байтом slot.
        try:
            request = decode_discard(payload)
        except ValueError:
            return [], {'action': 'rejected', 'reason': 'discard_variant_or_position'}
        container, slot, quantity = request.container, request.slot, request.quantity
        if (request.extension or request.own != 1 or not quantity
                or self.position is None or self.ground_template is None):
            return [], {'action': 'rejected', 'reason': 'discard_variant_or_position'}
        ammunition_definition = next((definition for definition, item_slot
                                      in AMMUNITION_SLOTS.items() if item_slot == slot), None)
        if (container == 2 and ammunition_definition is not None
                and quantity <= self.ammunition_quantity(ammunition_definition)):
            definition = ammunition_definition
        elif container == 2 and slot in MEDICAL_SLOTS.values():
            definition = next(d for d, s in MEDICAL_SLOTS.items() if s == slot)
            if quantity > self.medical.get(definition, 0):
                return [], {'action': 'rejected', 'reason': 'discard_slot_or_quantity'}
        elif container == 2 and slot in self.attachments and quantity == 1:
            definition = self.attachments[slot].definition
        elif container == 2 and slot in THROWABLE_SLOTS.values():
            definition = next(d for d, s in THROWABLE_SLOTS.items() if s == slot)
            if quantity > self.throwables.get(definition, 0):
                return [], {'action': 'rejected', 'reason': 'discard_slot_or_quantity'}
        elif container == 1 and slot in self.guns and quantity == 1:
            definition = self.guns[slot].definition
        elif container == 1 and slot in self.equipped_throwables:
            definition, available = self.equipped_throwables[slot]
            if quantity > available:
                return [], {'action': 'rejected', 'reason': 'discard_slot_or_quantity'}
        elif container == 1 and slot in (10,12) and quantity == 1 and slot in self.equipment:
            definition = self.equipment[slot]
        else:
            return [], {'action': 'rejected', 'reason': 'discard_slot_or_quantity'}
        item = self.spawn_discard(definition, quantity, self.position,
                                  clip=self.guns[slot].clip if definition in GUN_PROFILES else None,
                                  instance_uid=(self.guns[slot].uid if definition in GUN_PROFILES
                                                else self.attachments[slot].uid if definition in SUPPORTED_ATTACHMENTS else None),
                                  parts=tuple(self.guns[slot].parts.items()) if definition in GUN_PROFILES else (),
                                  skin_id=self.guns[slot].skin_id if definition in GUN_PROFILES else None,
                                  durability=self.equipment_durability.get(slot)
                                  if container == 1 and definition in EQUIPMENT_SLOTS else None)
        if item is None:
            return [], {'action': 'rejected', 'reason': 'discard_limit'}
        if definition in AMMUNITION_WEIGHTS:
            self.set_ammunition_quantity(definition,self.ammunition_quantity(definition)-quantity)
        elif definition in MEDICAL_PROFILES:
            remaining = self.medical[definition] - quantity
            if remaining:
                self.medical[definition] = remaining
            else:
                del self.medical[definition]
        elif definition in SUPPORTED_ATTACHMENTS:
            del self.attachments[slot]
        elif definition in THROWABLE_PROFILES:
            if container == 2:
                remaining = self.throwables[definition] - quantity
                if remaining:self.throwables[definition] = remaining
                else:del self.throwables[definition]
            else:
                remaining = self.equipped_throwables[slot][1] - quantity
                if remaining:self.equipped_throwables[slot] = (definition,remaining)
                else:
                    del self.equipped_throwables[slot]
                    if self.hand_slot == slot:self.hand_slot = 0
        elif definition in GUN_PROFILES:
            del self.guns[slot]
            if self.pending_reload and self.pending_reload['slot'] == slot:
                self.pending_reload = None
            if self.hand_slot == slot:
                self.hand_slot = 0
            if self.selected_slot == slot:
                self.selected_slot = min(self.guns, default=1)
        else:
            del self.equipment[slot]
            self.equipment_durability.pop(slot, None)
        replies = [(0x3e81, struct.pack('>BIIB', 2, 0, definition, 1))]
        if self.fixture.inventory_update == 'delta':
            replies.append(self.slot_sync(container, slot))
        elif (definition in MEDICAL_PROFILES and definition not in self.medical
                or definition not in (*AMMUNITION_WEIGHTS, *MEDICAL_PROFILES)
                or definition in AMMUNITION_WEIGHTS and self.ammunition_quantity(definition) == 0):
            replies.append(self.clear_slot(container,slot))
        # 5fb пересоздаёт equipment, но не удаляет отсутствующие bag-записи.
        # После неё магазин синхронизируется отдельно, чтобы не сброситься в0.
        if self.fixture.inventory_update == 'snapshot':
            replies.append((0x5fb,self.inventory()))
        replies.extend(self.magazine_syncs())
        if container == 1 and definition in (*GUN_PROFILES,*THROWABLE_PROFILES) and self.hand_slot == 0:
            replies.append((0x49f,struct.pack('>II',0,0)))
        replies += [self.capacity_sync(), (0x821,item.entity)]
        return replies, {
                    'action': 'discard', 'definition': definition, 'quantity': quantity,
                    'index': item.index, 'position': item.position, 'reserve': self.reserve,
                    'ammunition_quantity':self.ammunition_quantity(definition) if definition in AMMUNITION_WEIGHTS else None}

    def kit_sync(self):
        """Инициализация собственного набора обычными сообщениями2022."""
        definition = self.equipment.get(11)
        if definition not in WINTER_KITS:
            return []
        selected, capacity = WINTER_KITS[definition]
        # При смене зимнего набора старые способности должны выключаться.
        responses = [(0x10d0, struct.pack('>II', index, int(index == selected)))
                     for index in (2, 3, 4)]
        responses.append((0x516, struct.pack('>HBII', 1, 5, capacity, capacity)))
        return responses

    def inventory_records(self):
        # Одежда занимает свои cosmetic slots и не заменяет armor/зимний kit.
        records = [bytes((1,slot)) + data
                   for slot,data in sorted(self.cosmetic_clothes.items())]
        for slot, instance in sorted(self.guns.items()):
            gun = bytearray(gun_attachment_record(self.fixture.gun, instance.parts))
            gun[:4] = bytes((1, slot, 1, 0))
            struct.pack_into('>IQ', gun, 4, instance.definition, instance.uid)
            # ITEM_DATA ref+56 (item+54) -> gun+810: вместимость для native
            # проверки полной R и reload prediction. Шаблон Citori содержит2;
            # смены definition/4A0 недостаточно для остальных пушек/магазинов.
            struct.pack_into('>I', gun, 56, self.gun_magazine_capacity(instance))
            # После вставки attachment records поле сдвигается на12 байт/part.
            struct.pack_into('>I', gun, 72 + 12 * len(instance.parts), instance.skin_id)
            records.append(bytes(gun))
        records.extend(equipment_record(self.fixture.gun, definition,
                                        self.equipment_durability.get(slot))
                       for slot, definition in sorted(self.equipment.items()))
        if self.reserve:
            records.append(self.ammunition_record(30004))
        for definition,quantity in sorted(self.extra_ammunition.items()):
            records.append(self.ammunition_record(definition))
        for definition, quantity in sorted(self.medical.items()):
            records.append(medical_record(definition, quantity))
        records.extend(attachment_record(self.fixture.gun, slot, item)
                       for slot, item in sorted(self.attachments.items()))
        records.extend(throwable_record(definition, quantity)
                       for definition, quantity in sorted(self.throwables.items()))
        records.extend(throwable_record(definition,quantity,1,slot)
                       for slot,(definition,quantity) in sorted(self.equipped_throwables.items()))
        return records

    def inventory(self):
        records = self.inventory_records()
        return encode_snapshot(records, self.actor_uid)

    def absorb_combat_damage(self, damage):
        """Учебная защита тела от дистанционной атаки; исходная формула неизвестна.

        Не применяется к зоне/падению. Поглощение расходует столько же raw
        прочности жилета; шлем и hit-zone этим опытом не восстанавливаются.
        """
        if type(damage) is not int or not 0 <= damage <= 100:
            raise ValueError('Учебная атака требует целый урон0..100')
        slot = 12
        definition = self.equipment.get(slot, 0)
        before = self.equipment_durability.get(slot, 0)
        percent = self.fixture.combat_armor_absorb_percent
        absorbed = min(before, damage * percent // 100) if definition in ARMOR_DURABILITY else 0
        packets = []
        if absorbed:
            self.equipment_durability[slot] = before - absorbed
            record = equipment_record(self.fixture.gun, definition, before - absorbed)
            packets.append(self.item_delta(1, slot, record))
        return damage - absorbed, packets, {
            'action': 'own_armor_damage', 'raw_damage': damage,
            'damage': damage - absorbed, 'absorbed': absorbed,
            'armor_definition': definition, 'armor_durability': before - absorbed,
            'armor_absorb_percent': percent, 'experimental': True,
            'validation': 'diagnostic_body_percent_durability'}

    def reconcile_inventory(self):
        """Handoff: текущее состояние известных слотов вместо потерянных delta.

        Не создаёт новые UID/ground items и не повторяет5fb, сбрасывавший hand.
        """
        records = self.inventory_records()
        present = {(record[0], record[1]) for record in records}
        known = {(1, slot) for slot in (1, 2, 10, 11, 12)} | {
            (2, slot) for slot in (*AMMUNITION_SLOTS.values(), *MEDICAL_SLOTS.values())}
        known.update((2, slot) for slot in self.known_attachment_slots)
        known.update((2, slot) for slot in self.known_throwable_slots)
        known.update((1, slot) for slot in self.known_equipped_throwable_slots)
        if self.fixture.handgun_slot:
            known.add((1, 3))
        packets = [self.clear_slot(container, slot) for container, slot in sorted(known - present)]
        packets.extend(self.item_delta(record[0], record[1], record) for record in records)
        return packets + self.magazine_syncs() + self.kit_sync() + [self.capacity_sync()]

    def ammunition_sync(self, counter=0, slot=None):
        # Последнее слово — идентификатор предсказания, а не запас патронов.
        slot = self.selected_slot if slot is None else slot
        return struct.pack('>QIII', self.actor_uid, slot, self.guns[slot].clip, counter)

    def poll(self, now):
        pending = self.pending_reload
        if not pending or now < pending['deadline']:
            return [], []
        self.pending_reload = None
        slot = pending['slot']
        gun = self.guns.get(slot)
        if gun is None or gun.uid != pending['uid'] or self.hand_slot != slot:
            return [], [{'action': 'reload_cancelled', 'slot': slot}]
        self.selected_slot = slot
        definition = self.gun_ammunition
        quantity = self.ammunition_quantity(definition)
        amount = min(self.magazine_capacity - gun.clip, quantity)
        gun.clip += amount
        self.set_ammunition_quantity(definition, quantity - amount)
        remaining = self.ammunition_quantity(definition)
        packets = []
        if amount:
            packets.append(self.item_delta(2, AMMUNITION_SLOTS[definition],
                           self.ammunition_record(definition)) if remaining else
                           self.clear_slot(2, AMMUNITION_SLOTS[definition]))
        packets.extend([(0x4a0, self.ammunition_sync(slot=slot)), self.capacity_sync()])
        return packets, [{'action': 'reload', 'slot': slot, 'amount': amount,
                         'clip': gun.clip, 'reserve': self.reserve,
                         'gun_definition': gun.definition, 'ammunition_definition': definition,
                         'ammunition_quantity': remaining, 'update': 'timed_delta'}]

    def handle(self, command, payload, now=None):
        """Ответы и диагностическое событие; неизвестные сообщения не меняют состояние."""
        if command == 0x3e80:
            if payload[:1] == b'\x06':
                return move_attachment(self, payload)
            if payload[:1] == b'\x01':
                return self.move_gun(payload)
            return self.discard(payload)
        if command == 0x3b63 and len(payload) == 33 and self.loot_registry:
            index, slot, target, byte, short, flag, x, y, z, final = struct.unpack('>IIQBHB3iB', payload)
            loot = self.loot_registry.get(index)
            if loot is None:
                return [], {'action': 'rejected', 'reason': 'unknown_loot_index'}
            distance_squared = sum((a-b)**2 for a, b in zip((x,y,z), loot.position))
            # Native140d61b30 записывает позицию камеры (с возможным transform),
            # а не ног actor. Радиус клиента225см сюда неприменим; это локальный
            # предел750см для одной fixture, не восстановленное правило сервера.
            available = loot.entity_uid in self.available_loot or (loot == self.fixture.loot and self.loot_available)
            # Native377: drag ground→equipment использует B/H destination ref,
            # auto flag0; ПКМ имеет пустую ссылку и auto flag1. Остальные виды
            # ручного подбора пока не разрешаются без отдельного wire-контроля.
            automatic = byte == 0 and short == 0 and flag == 1
            manual_gun = (byte == 1 and flag == 0 and loot.definition in GUN_PROFILES
                          and self.gun_fits_slot(loot.definition, short))
            # Native00115.10: рукоятка и магазин с земли передают UID оружия,
            # container3 и attachment point2/3. UID/совместимость проверяет helper.
            manual_attachment = byte == 3 and flag == 0 and loot.definition in SUPPORTED_ATTACHMENTS
            target_ok = target == 0 or manual_attachment
            if (not available or slot != 0 or not target_ok
                    or not (automatic or manual_gun or manual_attachment) or final != 0
                    or distance_squared >= 750**2):
                # Публичные поля подбора: разделяем отказ drag/дистанции,
                # не ослабляя ограничения и не записывая авторизацию.
                checks = {'available': available, 'slot_zero': slot == 0,
                          'target_zero': target_ok, 'destination_variant': automatic or manual_gun or manual_attachment,
                          'final_zero': final == 0, 'distance': distance_squared < 750**2}
                return [], {'action': 'rejected', 'reason': 'pickup_fixture_or_distance',
                            'failed_checks': [name for name, passed in checks.items() if not passed],
                            'loot_index': index, 'requested_slot': slot, 'requested_target': hex(target),
                            'request_byte': byte, 'request_short': short, 'request_flag': flag,
                            'request_final': final, 'distance_squared_cm': distance_squared}
            if manual_attachment:
                return pickup_attachment_to_gun(self, loot, target, short)
            duplicate = index in self.picked_loot or (loot == self.fixture.loot and self.loot_picked)
            amount = loot.quantity
            discarded = None
            reload_cancelled_on_replace = False
            if not duplicate:
                if loot.definition in GUN_PROFILES:
                    if manual_gun:
                        destination = short
                    elif loot.definition in HANDGUN_PROFILES and (self.fixture.weapon_slots != 3 or 3 not in self.guns):
                        if not self.fixture.handgun_slot:
                            return [], {'action': 'rejected', 'reason': 'handgun_slot_disabled'}
                        destination = 3
                    else:
                        # Пистолет в руках не является заменяемым primary slot.
                        primary_slots = range(1, self.fixture.weapon_slots + 1)
                        fallback = (self.hand_slot if self.hand_slot in primary_slots
                                    else self.selected_slot if self.selected_slot in primary_slots else 1)
                        destination = next((s for s in range(1, self.fixture.weapon_slots + 1)
                                            if s not in self.guns), fallback)
                    previous = self.guns.get(destination)
                    # Замена и повторный pickup не создают заново полный магазин.
                    if previous and self.ground_template:
                        if self.drop_counter >= 256:
                            return [], {'action': 'rejected', 'reason': 'discard_limit'}
                        discarded = self.spawn_discard(previous.definition, 1,
                                                       self.position or loot.position, clip=previous.clip,
                                                       instance_uid=previous.uid, parts=tuple(previous.parts.items()),
                                                       skin_id=previous.skin_id)
                    if self.fixture.inventory_update == 'snapshot' or self.selected_slot not in self.guns:
                        self.selected_slot = destination
                    # Наша политика: новая M4 пуста; отброшенная хранит свой clip.
                    clip = ((self.fixture.capacity if loot.definition == 10402 else 0)
                            if loot.clip is None else loot.clip)
                    if self.pending_reload and self.pending_reload['slot'] == destination:
                        self.pending_reload = None
                        reload_cancelled_on_replace = True
                    self.guns[destination] = GunInstance(loot.definition, clip,
                                                       loot.instance_uid or self.new_instance_uid(), dict(loot.parts),
                                                       self.skin_selection.get(loot.definition, 0) if loot.skin_id is None else loot.skin_id)
                elif loot.definition in SUPPORTED_ATTACHMENTS:
                    destination = next((s for s in ATTACHMENT_BAG_SLOTS if s not in self.attachments), None)
                    room = self.bag_capacity * 100 - self.bag_weight_hundredths()
                    amount = int(destination is not None and room >= ATTACHMENT_PROFILES[loot.definition][2])
                    if amount:
                        self.attachments[destination] = AttachmentInstance(
                            loot.definition, loot.instance_uid or self.new_instance_uid())
                        self.known_attachment_slots.add(destination)
                elif loot.definition in AMMUNITION_WEIGHTS:
                    # Вместимость и nPackMax999; частичный pickup сохраняет остаток.
                    amount = min(loot.quantity,self.ammunition_room(loot.definition))
                    if amount < loot.quantity and not loot.entity:
                        return [], {'action': 'rejected', 'reason': 'partial_pickup_requires_entity'}
                    self.set_ammunition_quantity(loot.definition,self.ammunition_quantity(loot.definition)+amount)
                elif loot.definition in MEDICAL_PROFILES:
                    amount = min(loot.quantity, self.medical_room(loot.definition))
                    if amount < loot.quantity and not loot.entity:
                        return [], {'action': 'rejected', 'reason': 'partial_pickup_requires_entity'}
                    if amount:
                        self.medical[loot.definition] = self.medical.get(loot.definition, 0) + amount
                elif loot.definition in THROWABLE_PROFILES:
                    amount = int(min(loot.quantity, self.throwable_room(loot.definition)))
                    if amount < loot.quantity and not loot.entity:
                        return [], {'action': 'rejected', 'reason': 'partial_pickup_requires_entity'}
                    if amount:
                        self.throwables[loot.definition] = self.throwables.get(loot.definition, 0) + amount
                        self.known_throwable_slots.add(THROWABLE_SLOTS[loot.definition])
                else:
                    previous = self.equipment.get(EQUIPMENT_SLOTS[loot.definition])
                    if previous and self.ground_template:
                        if self.drop_counter >= 256:
                            return [], {'action': 'rejected', 'reason': 'discard_limit'}
                        discarded = self.spawn_discard(previous, 1, self.position or loot.position,
                            durability=self.equipment_durability.get(EQUIPMENT_SLOTS[loot.definition]))
                    equipment_slot = EQUIPMENT_SLOTS[loot.definition]
                    self.equipment[equipment_slot] = loot.definition
                    self.equipment_durability[equipment_slot] = (
                        ARMOR_DURABILITY.get(loot.definition, 0)
                        if loot.durability is None else loot.durability)
                if amount == loot.quantity:
                    self.picked_loot.add(index)
                    if loot == self.fixture.loot:
                        self.loot_picked = True
            ack = struct.pack('>IIIBI', index, 0, amount, 1, loot.definition) + bytes(28)
            responses = [(0x3b64, ack)]
            if self.fixture.inventory_update == 'delta':
                if duplicate:
                    responses.extend(self.reconcile_inventory())
                else:
                    if loot.definition in GUN_PROFILES:
                        reference = (1, destination)
                    elif loot.definition in SUPPORTED_ATTACHMENTS:
                        reference = (2, destination) if amount else None
                    elif loot.definition in EQUIPMENT_SLOTS:
                        reference = (1, EQUIPMENT_SLOTS[loot.definition])
                    else:
                        reference = (2, (AMMUNITION_SLOTS | MEDICAL_SLOTS | THROWABLE_SLOTS)[loot.definition])
                    if reference is not None:
                        responses.append(self.slot_sync(*reference))
                    responses.extend(self.magazine_syncs())
                    responses.append(self.capacity_sync())
            else:
                responses.extend([(0x5fb, self.inventory()), self.capacity_sync(), *self.magazine_syncs()])
            if amount or duplicate:
                responses.append((0x82b, struct.pack('>Q', loot.entity_uid)))
            if not duplicate and 0 < amount < loot.quantity and loot.entity:
                body = bytearray(loot.entity)
                struct.pack_into('>I', body, 67, loot.quantity - amount)
                remaining = replace(loot, quantity=loot.quantity-amount, entity=bytes(body))
                self.loot_registry[index] = remaining
                responses.append((0x821, remaining.entity))
            if discarded:
                responses.append((0x821, discarded.entity))
            if not duplicate and loot.definition in WINTER_KITS:
                responses.extend(self.kit_sync())
            return responses, {
                'action': 'duplicate_pickup' if duplicate else 'pickup',
                'index': index, 'quantity': amount, 'reserve': self.reserve,
                'pickup_mode': 'automatic' if automatic else 'manual_gun',
                'requested_destination': short,
                'destination_slot': (destination if loot.definition in GUN_PROFILES and not duplicate else None),
                'reload_cancelled_on_replace': reload_cancelled_on_replace,
                'remaining': 0 if duplicate else loot.quantity - amount,
                             'discarded_index': discarded.index if discarded else None,
                             'ammunition_quantity': self.ammunition_quantity(loot.definition) if loot.definition in AMMUNITION_WEIGHTS else None}
        if command == 0x49e and len(payload) == 4:
            slot = struct.unpack('>I', payload)[0]
            if slot == 0 or slot in self.guns or slot in self.equipped_throwables:
                cancelled = bool(self.pending_reload and self.pending_reload['slot'] != slot)
                if cancelled:
                    self.pending_reload = None
                self.hand_slot = slot
                if slot in self.guns:
                    self.selected_slot = slot
                return [(0x49f, struct.pack('>II', slot, 0))], {'action': 'hand', 'slot': slot,
                                                           'reload_cancelled': cancelled}
        elif command == 0x11da and len(payload) == 49:
            values = struct.unpack('>6fIBIIfII', payload)
            counter, mode, tick = values[6:9]
            if not all(math.isfinite(v) for v in values[:6] + (values[10],)):
                return [], {'action': 'rejected', 'reason': 'nonfinite'}
            if mode == 1:
                return [], {'action': 'fire_finish', 'counter': counter}
            if mode != 0 or self.hand_slot not in self.guns:
                return [], {'action': 'rejected', 'reason': 'fire_mode_or_hand'}
            if self.pending_reload:
                return [], {'action': 'rejected', 'reason': 'reload_in_progress'}
            self.selected_slot = self.hand_slot
            # Повтор транспортного запроса не тратит второй патрон, даже если tick изменён.
            identity = counter
            if identity in self.shots:
                return [], {'action': 'duplicate_fire', 'counter': counter}
            self.shots.append(identity)
            fired = self.clip > 0
            if fired:
                self.clip -= 1
            return [(0x4a0, self.ammunition_sync(counter))], {
                'action': 'fire' if fired else 'empty', 'counter': counter,
                'clip': self.clip, 'reserve': self.reserve, 'slot': self.hand_slot,
                'gun_definition': self.gun_definition,
                # reserve — прежнее поле запаса12ga; для M4 и других семей
                # расход сверяется по явно указанному типу боеприпасов.
                'ammunition_definition': self.gun_ammunition,
                'ammunition_quantity': self.ammunition_quantity(self.gun_ammunition),
                'instance_uid': hex(self.guns[self.hand_slot].uid)}
        elif command == 0x49c and len(payload) == 4:
            slot = struct.unpack('>I', payload)[0]
            if slot not in self.guns or self.hand_slot != slot:
                return [], {'action': 'rejected', 'reason': 'reload_slot_or_hand'}
            self.selected_slot = slot
            ammunition_definition = self.gun_ammunition
            reserve = self.ammunition_quantity(ammunition_definition)
            amount = min(self.magazine_capacity - self.clip, reserve)
            if amount <= 0:
                # Успешная49D не прекращает клиентскую анимацию: native
                # 140E91F10 при result0 просто возвращается. Не выдаём
                # фиктивное начало и не меняем патроны при пустой операции.
                return [], {'action': 'reload_noop', 'amount': 0, 'slot': slot,
                            'reason': 'magazine_full' if self.clip >= self.magazine_capacity else 'reserve_empty',
                            'clip': self.clip, 'gun_definition': self.gun_definition,
                            'ammunition_definition': ammunition_definition,
                            'ammunition_quantity': reserve}
            if self.fixture.timed_reload and amount:
                if self.pending_reload:
                    return [], {'action': 'reload_pending', 'slot': slot}
                seconds = RELOAD_TIMES[self.gun_definition][int(self.clip > 0)]
                self.pending_reload = {'slot': slot, 'uid': self.guns[slot].uid,
                                       'deadline': (time.monotonic() if now is None else now) + seconds}
                return [(0x49d, struct.pack('>II', slot, 0))], {
                    'action': 'reload_started', 'slot': slot, 'seconds': seconds,
                    'clip': self.clip, 'gun_definition': self.gun_definition,
                    'ammunition_definition': ammunition_definition, 'ammunition_quantity': reserve}
            self.clip += amount
            self.set_ammunition_quantity(ammunition_definition, reserve - amount)
            responses = [(0x49d, struct.pack('>II', slot, 0))]
            if amount:
                if self.fixture.reload_update == 'delta':
                    remaining = self.ammunition_quantity(ammunition_definition)
                    responses.append(self.item_delta(2, AMMUNITION_SLOTS[ammunition_definition],
                                     self.ammunition_record(ammunition_definition)) if remaining else
                                     self.clear_slot(2, AMMUNITION_SLOTS[ammunition_definition]))
                    responses.extend([(0x4a0, self.ammunition_sync()), self.capacity_sync()])
                    return responses, {'action': 'reload', 'amount': amount, 'clip': self.clip,
                        'reserve': self.reserve, 'slot': slot, 'gun_definition': self.gun_definition,
                        'ammunition_definition': ammunition_definition,
                        'ammunition_quantity': remaining, 'update': 'delta'}
                if self.ammunition_quantity(ammunition_definition) == 0:
                    responses.append(self.clear_slot(2, AMMUNITION_SLOTS[ammunition_definition]))
                # Полная согласованная inventory вместо неразобранного delta-сообщения.
                responses += [(0x5fb, self.inventory()), *self.magazine_syncs(),
                              (0x49f, struct.pack('>II', slot, 0)), self.capacity_sync()]
            return responses, {'action': 'reload', 'amount': amount,
                               'clip': self.clip, 'reserve': self.reserve,
                               'gun_definition': self.gun_definition,
                               'ammunition_definition': ammunition_definition,
                               'ammunition_quantity': self.ammunition_quantity(ammunition_definition)}
        return [], {'action': 'rejected', 'reason': 'unsupported_or_malformed'}
