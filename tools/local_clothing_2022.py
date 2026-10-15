"""Локальный гардероб2022: проверенный3E80/tag1, контейнер6 и equipment1.

Слоты берутся из явной привязки каталога. Это наша offline-policy хранения;
исходные аренда, совместимость моделей и исторический баланс не восстановлены.
"""
import struct


def item_data(definition):
    if not definition:
        return bytes(37)
    data = bytearray(80)
    data[:2] = b'\x01\x00'
    struct.pack_into('>IQ', data, 2, definition, 0x1d00000000000000 + definition)
    struct.pack_into('>H', data, 78, 1)
    return bytes(data)


class ClothingSelection:
    def __init__(self, ids, slots, saved=None):
        self.ids = tuple(ids)
        if (len(self.ids) > 255 or len(set(self.ids)) != len(self.ids)
                or any(type(x) is not int or not 0 < x <= 0xffffffff for x in self.ids)):
            raise ValueError('Неверный каталог одежды')
        if (not isinstance(slots, dict)
                or any(not isinstance(k, str) or str(int(k)) != k
                       or int(k) not in self.ids or type(v) is not int
                       or v not in (13,14,15,16,17,18,19,22) for k,v in slots.items())
                or slots and set(map(int, slots)) != set(self.ids)):
            raise ValueError('Неверная привязка одежды к equipment slot')
        self.slots = {int(k): v for k,v in slots.items()}
        self.catalog_slots = {item: index for index, item in enumerate(self.ids)}
        saved = saved or {}
        self.equipped = self.load_map(saved.get('clothing_selection', {}), equipment=True)
        default = {str(i): x for i,x in enumerate(self.ids) if x not in self.equipped.values()}
        self.storage = self.load_map(saved.get('clothing_storage', default))
        all_items = [*self.storage.values(), *self.equipped.values()]
        if len(all_items) != len(set(all_items)) or set(all_items) != set(self.ids):
            raise ValueError('Одежда дублируется или отсутствует в сохранённом гардеробе')
        # Старые сохранения могли менять местами ссылки каталога при замене.
        # После проверки сохранности возвращаем ненадетые вещи на исходные места.
        self.storage = {self.catalog_slots[item]: item for item in self.storage.values()}

    def load_map(self, value, equipment=False):
        if not isinstance(value, dict):
            raise ValueError('Неверный список слотов одежды')
        result = {}
        for key,item in value.items():
            if (not isinstance(key, str) or not key.isascii() or not key.isdecimal()
                    or str(int(key)) != key or not 0 <= int(key) < 255
                    or type(item) is not int or item not in self.ids
                    or equipment and self.slots.get(item) != int(key)):
                raise ValueError('Неверная сохранённая ссылка одежды')
            result[int(key)] = item
        return result

    def state(self):
        return dict(clothing_selection=self.equipped, clothing_storage=self.storage)

    def snapshot(self, uid):
        rows = [bytes((container,slot)) + item_data(item)
                for container,items in ((6,self.storage),(1,self.equipped))
                for slot,item in sorted(items.items())]
        return struct.pack('>I',len(rows)) + b''.join(rows) + struct.pack('>QB',uid,0)

    def delta(self, container, slot, uid):
        items = self.storage if container == 6 else self.equipped
        return (0x3e82, b'\x01' + struct.pack('>HB',slot,container)
                + item_data(items.get(slot,0)) + struct.pack('>BQ',0,uid))

    def handle(self, body, uid):
        if len(body) != 10:
            return [], None
        tag,sc,source,dc,destination,quantity,own = struct.unpack('>BBHBHHB',body)
        if tag != 1 or (sc,dc) not in ((6,1),(1,6)):
            return [], None
        source_items = self.storage if sc == 6 else self.equipped
        destination_items = self.storage if dc == 6 else self.equipped
        moving = source_items.get(source)
        previous = destination_items.get(destination)
        valid = (moving is not None and quantity == 1 and own == 0
                 and source < 255 and destination < 255 and bool(self.slots))
        if sc == 6:
            valid = valid and self.slots.get(moving) == destination
        else:
            # Снятие — только в свободный слот; server-side swaps не угадываем.
            valid = valid and self.slots.get(moving) == source and previous is None
        # OnSaveEquip повторяет исходную ссылку уже надетой вещи.
        # Подтверждаем только точное совпадение каталога/категории/количества.
        if (sc == 6 and moving is None and quantity == 1 and own == 0
                and 0 <= source < len(self.ids)
                and self.ids[source] == previous
                and self.slots.get(previous) == destination):
            reply = (0x3e81, struct.pack('>BIIB', 1, 0, previous, 0))
            return [reply, self.delta(6, source, uid),
                    self.delta(1, destination, uid)], 'clothing_move_noop'
        reply = (0x3e81,struct.pack('>BIIB',1,0 if valid else 1,moving or 0,0))
        if not valid:
            return [reply], 'clothing_move_rejected'
        source_items.pop(source)
        changed = [(sc, source)]
        if previous is not None:
            # Замена A→B возвращает A в её исходный слот, а не в слот B.
            returned = self.catalog_slots[previous]
            self.storage[returned] = previous
            changed.append((6, returned))
        if dc == 6:
            destination = self.catalog_slots[moving]
        destination_items[destination] = moving
        changed.append((dc, destination))
        # Одну ссылку публикуем один раз, уже с окончательным содержимым.
        changed = dict.fromkeys(changed)
        return [reply, *(self.delta(c, slot, uid) for c, slot in changed)], 'move_clothing'
