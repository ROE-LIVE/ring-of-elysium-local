"""Проверенные ITEM_DATA/5fb/3e82/ref2022; неизвестные union не угадываются.

Первичные decoder:140bcf790,140bcf510,140bcec10,140bcf2f0,
140c28460,140bd4d60,140c4ae00. Не интерпретирует неизвестные поля.
"""
from dataclasses import dataclass
import struct

MAX_SNAPSHOT_ITEMS = 397

class Reader:
    def __init__(self, data):
        self.data = bytes(data)
        self.offset = 0

    def take(self, length):
        end = self.offset + length
        if length < 0 or end > len(self.data):
            raise ValueError('Укороченная запись инвентаря2022')
        value = self.data[self.offset:end]
        self.offset = end
        return value

    def number(self, format):
        return struct.unpack(format, self.take(struct.calcsize(format)))[0]

    def finish(self):
        if self.offset != len(self.data):
            raise ValueError('Лишние байты после инвентаря2022')

@dataclass(frozen=True)
class ItemData:
    raw: bytes
    item_type: int
    flags: int
    definition: int
    instance_uid: int
    quantity: int
    category: int | None
    part_count: int
    skin_id: int | None = None

@dataclass(frozen=True)
class InventoryEntry:
    container: int
    slot: int
    item: ItemData

@dataclass(frozen=True)
class InventoryMessage:
    entries: tuple
    actor_uid: int
    own: int

@dataclass(frozen=True)
class DiscardRequest:
    container: int
    slot: int
    quantity: int
    extension: int
    own: int


def read_item(reader):
    start = reader.offset
    item_type = reader.number('>B')
    flags = reader.number('>B')
    definition = reader.number('>I')
    instance_uid = reader.number('>Q')
    reader.take(8)
    name_present = reader.number('>B')
    if name_present not in (0, 1):
        raise ValueError('ITEM_DATA: неверный признак имени')
    if name_present:
        length = reader.number('>I')
        if not 1 <= length <= 128:
            raise ValueError('ITEM_DATA: длина имени вне native1..128')
        name = reader.take(length)
        if not name.endswith(b'\0') or b'\0' in name[:-1]:
            raise ValueError('ITEM_DATA: имя должно иметь единственный завершающийNUL')
    reader.take(7)
    category, part_count, skin_id = None, 0, None
    if item_type == 0:
        reader.take(1)
    elif item_type == 1:
        reader.take(32)
        part_count = reader.number('>I')
        if not 0 <= part_count <= 8:
            raise ValueError('ITEM_DATA: count weapon parts вне0..8')
        reader.take(12 * part_count + 4)
        # 140FB259F: ITEM+126→gun+6C; native328 подтвердил10402210.
        skin_id = reader.number('>I')
    elif item_type == 2:
        category = reader.number('>B')
        reader.take(21)
        if category == 7:
            reader.take(20)
        elif category == 10:
            reader.take(4)
        elif category == 5:
            # 140bcf47f→140bcee20: неизвестное BE64 и обязательная
            # строка1..128 с единственным NUL; pure native cold109.
            reader.take(8)
            length = reader.number('>I')
            if not 1 <= length <= 128:
                raise ValueError('ITEM_DATA category5: длина строки вне native1..128')
            name = reader.take(length)
            if not name.endswith(b'\0') or b'\0' in name[:-1]:
                raise ValueError('ITEM_DATA category5: нужен единственный завершающийNUL')
    else:
        raise ValueError('Неподдержанный ITEM_DATA union2022')
    reader.take(4)
    quantity = reader.number('>H')
    return ItemData(reader.data[start:reader.offset], item_type, flags,
                    definition, instance_uid, quantity, category, part_count, skin_id)


def decode_item(data):
    reader = Reader(data)
    item = read_item(reader)
    reader.finish()
    return item


def decode_snapshot(data):
    reader = Reader(data)
    count = reader.number('>I')
    if count > MAX_SNAPSHOT_ITEMS:
        raise ValueError('5fb: count вне native0..397')
    entries = []
    for _ in range(count):
        container, slot = struct.unpack('>BB', reader.take(2))
        entries.append(InventoryEntry(container, slot, read_item(reader)))
    actor_uid, own = reader.number('>Q'), reader.number('>B')
    reader.finish()
    return InventoryMessage(tuple(entries), actor_uid, own)


def decode_delta(data):
    reader = Reader(data)
    count = reader.number('>B')
    entries = []
    for _ in range(count):
        slot, container = struct.unpack('>HB', reader.take(3))
        entries.append(InventoryEntry(container, slot, read_item(reader)))
    own, actor_uid = reader.number('>B'), reader.number('>Q')
    reader.finish()
    return InventoryMessage(tuple(entries), actor_uid, own)


def decode_discard(data):
    if len(data) != 15:
        raise ValueError('3e80/tag2: нужны15байт')
    tag, container, slot, quantity, extension, own = struct.unpack('>BBHHQB', data)
    if tag != 2:
        raise ValueError('Нужен discard union/tag2')
    return DiscardRequest(container, slot, quantity, extension, own)


def encode_snapshot(records, actor_uid, own=True):
    records = tuple(bytes(record) for record in records)
    if len(records) > MAX_SNAPSHOT_ITEMS:
        raise ValueError('5fb: слишком много записей')
    for record in records:
        if len(record) < 2:
            raise ValueError('5fb: отсутствует ссылка предмета')
        decode_item(record[2:])
    return struct.pack('>I', len(records)) + b''.join(records) + struct.pack('>QB', actor_uid, int(own))


def encode_delta(container, slot, item_data, actor_uid, own=True):
    item = decode_item(item_data)
    return (b'\x01' + struct.pack('>HB', slot, container) + item.raw
            + struct.pack('>BQ', int(own), actor_uid))
