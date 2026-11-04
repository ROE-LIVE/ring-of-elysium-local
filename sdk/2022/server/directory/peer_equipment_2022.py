"""Удалённая экипировка2022 из текущего WeaponState, без выдачи own инвентаря.

547 decoder140C356B0/140C35320, consumer140E7DBD0. Native296/297
подтвердили полный набор, definition0 для снятия и tail−1 для пустой руки.
Магазин/перезарядка этим сообщением отдельно не восстанавливаются.
"""
import struct


SLOTS = (1, 2, 10, 11, 12)


def npc_clothing_record(definition,avatar_uid,slot):
    """Проверенный80B ITEM_DATA одежды; cosmetic instance локален NPC."""
    if (type(definition)is not int or not 300000<=definition<400000
            or type(avatar_uid)is not int or not 0<avatar_uid<2**64
            or type(slot)is not int or slot not in (13,14,15,16,17,18,19,22)):
        raise ValueError('Неверное определение одежды NPC')
    data=bytearray(80);data[:2]=b'\x01\x00'
    instance=0x1e00000400000000+((avatar_uid&0xffffff)<<8)+slot
    struct.pack_into('>IQ',data,2,definition,instance)
    struct.pack_into('>H',data,78,1)
    return bytes(data)


def npc_protection_instance_uid(avatar_uid, slot):
    """Один синтетический ID NPC-защиты для delta и полного снимка547."""
    if type(avatar_uid) is not int or not 0 < avatar_uid < 2**64 or type(slot) is not int or slot not in (10, 12):
        raise ValueError('Нужны UID actor и защитный слот10/12')
    namespace = 0x1e00000300000000 if slot == 10 else 0x1e00000200000000
    return namespace + (avatar_uid & 0xffffffff)


def encode_peer_equipment(weapon, avatar_uid, dead=False, *, npc_protection=False, player_profile=False):
    # Обычные peer-аватары сохраняют прежний wire. Флаг только у вызовов NPC.
    if type(npc_protection) is not bool:
        raise ValueError('npc_protection должен быть bool')
    records = []
    # Handgun slot добавляется явно для трёхслотовой модели. Старый peer-wire
    # с двумя оружиями сохраняет прежний состав и смещения записей.
    slots=(*SLOTS,3) if (npc_protection or player_profile) and weapon.fixture.weapon_slots>=3 else SLOTS
    for slot in slots:
        gun = weapon.guns.get(slot) if slot in (1,2,3) else None
        definition = gun.definition if gun else weapon.equipment.get(slot,0)
        if gun:
            instance = gun.uid
        elif definition and npc_protection and slot in (10, 12):
            instance = npc_protection_instance_uid(avatar_uid, slot)
        else:
            instance = 0x1e00000000000000 + definition if definition else 0
        parts = gun.parts if gun else {}
        record = struct.pack('>IQIBI',definition,instance,slot,0,len(parts))
        record += b''.join(struct.pack('>III',index,part.definition,0)
                           for index,part in sorted(parts.items()))
        # Snapshot ITEM_DATA: metadata32 и семь gun-properties36..63.
        # 547 размещает accessories перед ними. Equipment имеет другой union.
        properties = bytearray(weapon.fixture.gun[36:64]) if gun else bytes(28)
        if gun:
            # Вместимость принадлежит текущему оружию/магазину, не Citori-шаблону.
            struct.pack_into('>I',properties,20,weapon.gun_magazine_capacity(gun))
        metadata = struct.unpack_from('>I',weapon.fixture.gun,32)[0] if gun else 0
        durability = weapon.equipment_durability.get(slot,0) if not gun else 0
        record += properties+struct.pack('>4I',metadata,durability,int(bool(definition)),getattr(gun,'skin_id',0) if gun else 0)
        records.append(record)
    if npc_protection or player_profile:
        # Только явный NPC-гардероб. Cosmetic slots не становятся armor и
        # не выдаются собственному игроку через5FB/3E82.
        for slot in ((13,14,15,16,17,18,19,22) if player_profile else sorted(weapon.cosmetic_clothes)):
            data=weapon.cosmetic_clothes.get(slot,bytes(80))
            if slot not in (13,14,15,16,17,18,19,22) or len(data)!=80:
                raise ValueError('Неверная одежда NPC')
            definition,instance=struct.unpack_from('>IQ',data,2)
            instance=(0x1e00000400000000+((avatar_uid&0xffffff)<<8)+slot) if definition else 0
            record=struct.pack('>IQIBI',definition,instance,slot,0,0)
            records.append(record+bytes(28)+struct.pack('>4I',0,0,int(bool(definition)),0))
    # −1 ветка140E7DD98 очищает hand-present, а0 не находит slot0.
    hand = weapon.hand_slot if not dead and weapon.hand_slot in weapon.guns else 0xffffffff
    return struct.pack('>QI',avatar_uid,len(records))+b''.join(records)+struct.pack('>IB',hand,0)


def encode_peer_kit_attributes(weapon, avatar_uid):
    """10D1: удалённые raw2/3/4; 547 меняет вид, но не маску actor+354.

    Проверено native02.11: raw2=1 меняет маску0→1, 547 отдельно ставит
    visual378=2. Только серверная экипировка, без пересылки клиентских attrs.
    """
    definitions = {200907: 2, 200906: 3, 200904: 4}
    selected = definitions.get(weapon.equipment.get(11))
    return [(0x10d1,struct.pack('>QII',avatar_uid,index,int(index==selected)))
            for index in (2,3,4)]
