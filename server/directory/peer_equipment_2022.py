"""Удалённая экипировка2022 из текущего WeaponState, без выдачи own инвентаря.

547 decoder140C356B0/140C35320, consumer140E7DBD0. Native296/297
подтвердили полный набор, definition0 для снятия и tail−1 для пустой руки.
Магазин/перезарядка этим сообщением отдельно не восстанавливаются.
"""
import struct


SLOTS = (1, 2, 10, 11, 12)


def encode_peer_equipment(weapon, avatar_uid, dead=False):
    records = []
    for slot in SLOTS:
        gun = weapon.guns.get(slot) if slot in (1,2) else None
        definition = gun.definition if gun else weapon.equipment.get(slot,0)
        instance = gun.uid if gun else (0x1e00000000000000+definition if definition else 0)
        parts = gun.parts if gun else {}
        record = struct.pack('>IQIBI',definition,instance,slot,0,len(parts))
        record += b''.join(struct.pack('>III',index,part.definition,0)
                           for index,part in sorted(parts.items()))
        # Snapshot ITEM_DATA: metadata32 и семь gun-properties36..63.
        # 547 размещает accessories перед ними. Equipment имеет другой union.
        properties = weapon.fixture.gun[36:64] if gun else bytes(28)
        metadata = struct.unpack_from('>I',weapon.fixture.gun,32)[0] if gun else 0
        durability = weapon.equipment_durability.get(slot,0) if not gun else 0
        record += properties+struct.pack('>4I',metadata,durability,int(bool(definition)),0)
        records.append(record)
    # −1 ветка140E7DD98 очищает hand-present, а0 не находит slot0.
    hand = weapon.hand_slot if not dead and weapon.hand_slot in weapon.guns else 0xffffffff
    return struct.pack('>QI',avatar_uid,len(records))+b''.join(records)+struct.pack('>IB',hand,0)
