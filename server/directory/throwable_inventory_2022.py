"""Три зимние гранаты как предметы; действия/взрыв/дым/огонь здесь не реализованы."""
import struct

# A89 строки1128/1138/1148: nWeight12,nPackMax100.
# Наши свободные bag refs; исходная раскладка слотов не восстановлена.
THROWABLE_PROFILES = {50001: (1200, 100), 50002: (1200, 100), 50003: (1200, 100)}
THROWABLE_SLOTS = {50001: 11, 50002: 12, 50003: 13}


def throwable_record(definition, quantity, container=2, slot=None):
    """ITEM type2/category5; decoder140bcf47f→140bcee20, pure cold109.

    Неизвестные поля нулевые, обязательная строка содержит один NUL.
    Значение BE64 и назначение строки не установлены; это наш контрольный
    вариант, принятый декодером, а не полный серверный пресет гранаты.
    """
    if (definition not in THROWABLE_PROFILES or type(quantity) is not int
            or not 1 <= quantity <= THROWABLE_PROFILES[definition][1]):
        raise ValueError('Неверная стопка зимних гранат')
    if slot is None:
        slot = THROWABLE_SLOTS[definition]
    if not ((container == 2 and slot == THROWABLE_SLOTS[definition])
            or (container == 1 and slot in (5, 6))):
        raise ValueError('Неверная ссылка зимней гранаты')
    record = bytearray(73)
    record[:4] = bytes((container, slot, 2, 0))
    struct.pack_into('>IQ', record, 4, definition, 0x1e00000000000000 + definition)
    record[32] = 5
    struct.pack_into('>QI', record, 54, 0, 1)
    struct.pack_into('>H', record, 71, quantity)
    return bytes(record)


def move_throwable(state, payload):
    """3e80/tag1 bag→slot5 наблюдался cold111; наша политика переносов.

    Количество и вес сохраняются. Другой тип в занятой ячейке возвращается
    в сумку; отсутствие room/неверные refs запрещают операцию целиком.
    Бросок и эффект гранаты не реализуются этим переносом.
    """
    tag, source_container, source, destination_container, destination, quantity, own = struct.unpack('>BBHBHHB', payload)
    def reject(reason):return [], {'action':'rejected','reason':reason}
    if tag != 1 or own != 1 or not 1 <= quantity <= 100:
        return reject('throwable_move_quantity_or_own')
    if state.pending_reload:
        return reject('throwable_move_reload_pending')
    bag = dict(state.throwables)
    equipped = dict(state.equipped_throwables)
    if source_container == 2:
        definition=next((d for d,s in THROWABLE_SLOTS.items() if s==source),None)
        available=bag.get(definition,0)
    elif source_container == 1:
        definition,available=equipped.get(source,(None,0))
    else:return reject('throwable_move_source')
    if definition is None or quantity > available:
        return reject('throwable_move_source')
    if (source_container,source)==(destination_container,destination):
        return [state.slot_sync(source_container,source)],{'action':'throwable_move_noop','definition':definition}
    if source_container==2:
        if available==quantity:bag.pop(definition)
        else:bag[definition]=available-quantity
    else:
        if available==quantity:equipped.pop(source)
        else:equipped[source]=(definition,available-quantity)
    if destination_container==2 and destination==THROWABLE_SLOTS[definition]:
        total=bag.get(definition,0)+quantity
        if total>100:return reject('throwable_move_stack_full')
        bag[definition]=total
    elif destination_container==1 and destination in (5,6):
        previous,old_quantity=equipped.get(destination,(definition,0))
        if previous==definition:
            if old_quantity+quantity>100:return reject('throwable_move_stack_full')
            equipped[destination]=(definition,old_quantity+quantity)
        else:
            if bag.get(previous,0)+old_quantity>100:return reject('throwable_move_stack_full')
            bag[previous]=bag.get(previous,0)+old_quantity
            equipped[destination]=(definition,quantity)
    else:return reject('throwable_move_destination')
    state.throwables=bag;state.equipped_throwables=equipped
    state.known_throwable_slots.update(THROWABLE_SLOTS.values())
    state.known_equipped_throwable_slots.update((5,6))
    replies=[(0x3e81,struct.pack('>BIIB',1,0,definition,1))]
    # Занятая ячейка могла вернуть другой тип в сумку. Согласуем все
    # пять известных ссылок, а не только source/destination.
    replies.extend(state.slot_sync(2,s) for s in THROWABLE_SLOTS.values())
    replies.extend(state.slot_sync(1,s) for s in (5,6))
    if state.hand_slot in (5,6) and state.hand_slot not in equipped:
        state.hand_slot=0
        replies.append((0x49f,struct.pack('>II',0,0)))
    replies.append(state.capacity_sync())
    return replies,{'action':'throwable_moved','definition':definition,'quantity':quantity,
                   'source':[source_container,source],'destination':[destination_container,destination]}
