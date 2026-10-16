"""Хвост11DD: countBE16 и до30 tagged union записей, без доверия их authority.

2022 decoder140C3FE00/140C40211→140C3F5A0. Tag0: дваu8,
materialBE32, floatXYZ; tag1: UIDBE64 иu8. Native memory stride19
не равен длине всех wire-вариантов: tag1 занимает10байт с тегом.
"""
import math
import struct


def decode_hit_records(payload):
    if len(payload) < 106:
        raise ValueError('11DD требует104фиксированных байта и countBE16')
    count = struct.unpack_from('>H',payload,104)[0]
    if count > 30:
        raise ValueError('11DD допускает не больше30записей')
    records = []
    offset = 106
    for _ in range(count):
        if offset >= len(payload):
            raise ValueError('Оборванный tag записи11DD')
        kind = payload[offset]
        if kind == 0:
            if len(payload)-offset < 19:
                raise ValueError('Оборванная surface-запись11DD')
            _,opaque1,opaque2,material,*point = struct.unpack_from('>BBBI3f',payload,offset)
            if not all(math.isfinite(x) and abs(x) <= 10000000 for x in point):
                raise ValueError('Неконечная/слишком большая позиция11DD record')
            records.append(dict(kind=0,opaque_u8_1=opaque1,opaque_u8_2=opaque2,
                                material_id=material,point=tuple(point)))
            offset += 19
        elif kind == 1:
            if len(payload)-offset < 10:
                raise ValueError('Оборванная unit-запись11DD')
            _,uid,part = struct.unpack_from('>BQB',payload,offset)
            records.append(dict(kind=1,unit_uid=hex(uid),part_id=part))
            offset += 10
        else:
            # Native codec пропускает неизвестный union-tag без тела.
            # Этот peer поддерживает только установленные варианты0/1.
            raise ValueError('Неизвестный tag записи11DD')
    if offset != len(payload):
        raise ValueError('Лишние байты после списка11DD')
    return tuple(records)
