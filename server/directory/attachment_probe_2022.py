"""Ограниченный оборот обвесов2022; A89 и native cold62, без исходного server engine."""
from dataclasses import dataclass
import struct

# A89/963..991: (точка крепления, тип, вес в сотых единицы).
ATTACHMENT_PROFILES = {
    40101: (0, 5, 2500), 40102: (0, 1, 1000), 40103: (0, 22, 2000),
    40104: (0, 2, 1000), 40105: (0, 3, 1500), 40106: (0, 7, 800),
    40107: (0, 4, 500), 40108: (0, 6, 800), 40109: (0, 5, 1200),
    40110: (0, 2, 1000), 40111: (0, 23, 1200), 40112: (0, 26, 2000),
    40201: (1, 8, 1000), 40202: (1, 8, 1000), 40203: (1, 8, 1000),
    40204: (1, 8, 1000), 40301: (2, 14, 2500), 40302: (2, 14, 2000),
    40303: (2, 13, 1500), 40304: (2, 24, 1500), 40305: (2, 25, 1000),
    40306: (2, 12, 1000), 40401: (3, 20, 1800), 40403: (3, 18, 1500),
    40405: (3, 19, 1300), 40407: (3, 21, 1000), 40502: (4, 16, 1500),
    40503: (4, 15, 1200), 40602: (5, 17, 1000),
}
# Пересечение исходных TypeCanUse/IndexCanUse; спорные/secondary refs пока не разрешены.
GUN_ATTACHMENT_COMPATIBILITY = {
    10402: ({4, 17}, {0}),
    10201: ({2, 8, 13, 12, 16, 18, 22, 24, 25}, {0, 1, 2, 3, 4}),
    10101: ({5, 14, 13, 12, 20, 23, 24, 25}, {0, 2, 3}),
    10102: ({5, 20}, {3}),
    10202: ({2, 13, 12, 18, 22, 24, 25}, {0, 2, 3}),
    20001: (set(), set()),
}
GUN_ATTACHMENT_COMPATIBILITY.update({10104: ({5, 8, 12, 13, 14, 20, 23, 24, 25, 26}, {0, 1, 2, 3, 5}),
 10105: ({12, 13, 14, 24, 25, 26}, {0, 2, 5}),
 10107: ({5, 8, 12, 13, 14, 20, 23, 24, 25, 26}, {0, 1, 2, 3, 5}),
 10110: ({5, 12, 13, 14, 20, 23, 24, 25, 26}, {0, 2, 3, 5}),
 10203: ({2, 8, 12, 13, 16, 18, 22, 24, 25}, {0, 1, 2, 3, 4, 5}),
 10204: ({2, 8, 12, 13, 16, 18, 22, 24, 25}, {0, 1, 2, 3, 5}),
 10205: ({2, 12, 13, 18, 22, 24, 25}, {0, 2, 3, 5}),
 10206: ({2, 8, 12, 13, 16, 18, 22, 24, 25}, {0, 1, 2, 3, 5}),
 10208: ({2, 8, 12, 13, 16, 18, 22, 24, 25}, {0, 1, 2, 3, 4, 5}),
 10301: ({3, 6, 7, 8, 12, 13, 19, 24, 25}, {0, 1, 2, 3, 5}),
 10303: ({3, 6, 7, 8, 12, 13, 16, 19, 24, 25}, {0, 1, 2, 3, 4, 5}),
 10305: ({7, 8, 12, 13, 19, 24, 25}, {1, 2, 3, 5}),
 10306: ({3, 6, 7, 8, 12, 13, 19, 24, 25}, {0, 1, 2, 3, 5}),
 10401: ({4, 12, 13, 24, 25}, {0, 2, 5}),
 10403: ({2, 4, 8, 12, 13, 18, 24, 25}, {0, 1, 2, 3, 5}),
 10601: ({24, 25, 12}, {2, 5}),
 10605: (set(), set()),
 20003: ({25}, {2, 5})})
# В проверенной A89 USP45 не содержит TypeCanUse/IndexCanUse; не выдумываем их.
SUPPORTED_ATTACHMENTS = {40305, 40103, 40101, 40403}
# Прочие обвесы исходного зимнего pool; native контроль отдельно от таблиц.
SUPPORTED_ATTACHMENTS.update({40104, 40105, 40106, 40107, 40108, 40109, 40110, 40111, 40112, 40201, 40202, 40302, 40303, 40304, 40306, 40401, 40405, 40502})
# A89: nMaxAmmoExtended M4/AK47; пока только проверяемый AR-магазин40403.
EXTENDED_CAPACITIES = {10201: 40, 10202: 40, 10101: 10, 10102: 10}
EXTENDED_CAPACITIES.update({10104: 20,
 10105: 5,
 10107: 30,
 10110: 30,
 10203: 40,
 10204: 40,
 10205: 40,
 10206: 40,
 10208: 40,
 10301: 40,
 10303: 33,
 10305: 30,
 10306: 40,
 10401: 5,
 10403: 10,
 10601: 100,
 10605: 1,
 20003: 10})
ATTACHMENT_BAG_SLOTS = range(20, 64)


@dataclass(frozen=True)
class AttachmentInstance:
    definition: int
    uid: int


def attachment_record(template, slot, instance):
    if len(template) != 82 or slot not in ATTACHMENT_BAG_SLOTS or instance.definition not in ATTACHMENT_PROFILES:
        raise ValueError('Неподдержанная запись обвеса')
    record = bytearray(template)
    record[:4] = bytes((2, slot, 1, 0))
    struct.pack_into('>IQ', record, 4, instance.definition, instance.uid)
    record[32:80] = bytes(48)
    struct.pack_into('>H', record, 80, 1)
    return bytes(record)


def gun_attachment_record(template, parts):
    """140bcec10→140bceab0: BE32count и до8 (index,definition,zero)."""
    if len(template) != 82 or len(parts) > 8:
        raise ValueError('Неподдержанная запись weapon parts')
    record = bytearray(template)
    struct.pack_into('>I', record, 64, len(parts))
    entries = b''
    for index, instance in sorted(parts.items()):
        if (instance.definition not in ATTACHMENT_PROFILES
                or ATTACHMENT_PROFILES[instance.definition][0] != index):
            raise ValueError('Обвес не соответствует точке крепления')
        entries += struct.pack('>III', index, instance.definition, 0)
    record[68:68] = entries
    return bytes(record)


def compatible(gun_definition, attachment_definition, index):
    profile = ATTACHMENT_PROFILES.get(attachment_definition)
    types, indexes = GUN_ATTACHMENT_COMPATIBILITY.get(gun_definition, (set(), set()))
    return attachment_definition in SUPPORTED_ATTACHMENTS and profile is not None and profile[0] == index and profile[1] in types and index in indexes


def move_attachment(weapon, payload):
    """3e80/tag6: UID+ref B/H для источника/назначения, Hqty, Bown."""
    if len(payload) != 26:
        return [], {'action': 'rejected', 'reason': 'attachment_length'}
    tag, source_uid, source_container, source, target_uid, target_container, target, quantity, own = struct.unpack(
        '>BQBHQBHHB', payload)
    if tag != 6 or quantity != 1 or own != 1:
        return [], {'action': 'rejected', 'reason': 'attachment_quantity_or_own'}
    if weapon.pending_reload:
        return [], {'action': 'rejected', 'reason': 'attachment_reload_pending'}
    guns = {gun.uid: (slot, gun) for slot, gun in weapon.guns.items()}
    instance = None
    overflow = 0
    if source_container == 2:
        instance = weapon.attachments.get(source)
        # Native cold109 передаёт UID самого обвеса в bag ref. Нулевой
        # UID сохраняем для ранее проверенных fixtures; ненулевой обязан
        # совпадать с текущим экземпляром, иначе перенос запрещён.
        if instance is not None and source_uid not in (0, instance.uid):
            return [], {'action': 'rejected', 'reason': 'attachment_source_uid'}
    elif source_container == 3 and source_uid in guns:
        instance = guns[source_uid][1].parts.get(source)
    if instance is None:
        return [], {'action': 'rejected', 'reason': 'attachment_source'}
    definition = instance.definition

    def reject(reason):
        return [(0x3e81, struct.pack('>BIIB', 6, 1, definition, 1))], {
            'action': 'rejected', 'reason': reason, 'definition': definition}

    if source_container == 2 and target_container == 3 and target_uid in guns:
        slot, gun = guns[target_uid]
        if not compatible(gun.definition, definition, target):
            return reject('incompatible_attachment')
        previous = gun.parts.get(target)
        # Возвращаем заменённый обвес в освобождённую ячейку, без второго экземпляра.
        previous_weight = ATTACHMENT_PROFILES[previous.definition][2] if previous else 0
        delta_weight = previous_weight - ATTACHMENT_PROFILES[definition][2]
        if weapon.bag_weight_hundredths() + delta_weight > weapon.bag_capacity * 100:
            return reject('attachment_bag_full')
        del weapon.attachments[source]
        gun.parts[target] = instance
        if previous:
            weapon.attachments[source] = previous
        weapon.known_attachment_slots.add(source)
        replies = [(0x3e81, struct.pack('>BIIB', 6, 0, definition, 1)),
                   weapon.slot_sync(2, source), weapon.slot_sync(1, slot)]
        action = 'attachment_installed'
    elif source_container == 3 and source_uid in guns and target_uid == 0 and target_container == 2:
        slot, gun = guns[source_uid]
        destination = target or next((index for index in ATTACHMENT_BAG_SLOTS
                                      if index not in weapon.attachments), None)
        if destination not in ATTACHMENT_BAG_SLOTS or destination in weapon.attachments:
            return reject('attachment_destination')
        if weapon.bag_weight_hundredths() + ATTACHMENT_PROFILES[definition][2] > weapon.bag_capacity * 100:
            return reject('attachment_bag_full')
        if definition in (40401, 40403, 40405):
            # Локальная политика: избыток возвращается в сумку, без потери патронов.
            base = weapon.base_magazine_capacity(gun.definition)
            overflow = max(0, gun.clip - base)
            ammunition = weapon.ammunition_definition(gun.definition)
            if weapon.ammunition_quantity(ammunition) + overflow > 999:
                return reject('attachment_overflow_stack_full')
            weight = weapon.ammunition_weight(ammunition) * overflow
            if (weapon.bag_weight_hundredths() + ATTACHMENT_PROFILES[definition][2]
                    + weight > weapon.bag_capacity * 100):
                return reject('attachment_overflow_bag_full')
        del gun.parts[source]
        weapon.attachments[destination] = instance
        weapon.known_attachment_slots.add(destination)
        if overflow:
            gun.clip -= overflow
            weapon.set_ammunition_quantity(ammunition, weapon.ammunition_quantity(ammunition) + overflow)
        replies = [(0x3e81, struct.pack('>BIIB', 6, 0, definition, 1)),
                   weapon.slot_sync(1, slot), weapon.slot_sync(2, destination)]
        action = 'attachment_removed'
    else:
        return reject('attachment_route_unsupported')
    if overflow:
        replies.append(weapon.ammunition_slot_sync(ammunition))
    replies.extend(weapon.magazine_syncs())
    replies.append(weapon.capacity_sync())
    return replies, {'action': action, 'definition': definition, 'gun_definition': gun.definition,
                     'gun_slot': slot, 'instance_uid': hex(instance.uid),
                     'gun_uid': hex(gun.uid), 'bag_items': len(weapon.attachments),
                     'returned_ammunition': overflow}
