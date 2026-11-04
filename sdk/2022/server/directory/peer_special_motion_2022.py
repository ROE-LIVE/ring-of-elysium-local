"""MOVE_SPEC37/version124+: decoder140C569D0, BC38decoder140C59B80.

NODE19×N и MOVEVEC9×M имеют независимые счётчики. Extra остаётся
непрозрачным. Непривязанный режим и проверенный трос разделены.
"""
import math
import struct


def decode_special_motion(payload):
    if not 33 <= len(payload) <= 1024:
        raise ValueError('Неверная длина MOVE_SPEC')
    count = struct.unpack_from('>i', payload)[0]
    if not 1 <= count <= 20 or len(payload) < 33 + 19 * count:
        raise ValueError('Неверное число точек MOVE_SPEC')
    points = []
    at = 4
    for _ in range(count):
        x, y, z, b0, b1, b2, tick = struct.unpack_from('>iiiBBBI', payload, at)
        at += 19
        points.append(dict(position=(x,y,z), bytes=(b0,b1,b2), value=tick))
    counter, mode, x, y, z, extra_float, speed, b1, ref_count = struct.unpack_from('>IB4fIBB', payload, at)
    at += 27
    if ref_count > 20 or at + 9 * ref_count + 2 > len(payload):
        raise ValueError('Неверное число привязок MOVE_SPEC')
    refs = [struct.unpack_from('>BQ', payload, at + 9*i) for i in range(ref_count)]
    at += 9 * ref_count
    strings = []
    for maximum in (16,32):
        if at >= len(payload):
            raise ValueError('Обрыв дополнительной строки MOVE_SPEC')
        size = payload[at]
        at += 1
        if size > maximum or at + size > len(payload):
            raise ValueError('Неверная дополнительная строка MOVE_SPEC')
        strings.append(bytes(payload[at:at+size]))
        at += size
    if at != len(payload):
        raise ValueError('Лишние данные MOVE_SPEC')
    if (not all(math.isfinite(v) for v in (x,y,z,extra_float)) or speed > 2000
            or any(any(abs(v)>10000000 for v in p['position']) for p in points)):
        raise ValueError('Неверная скорость, направление или позиция MOVE_SPEC')
    return dict(count=count,points=points,word_0=counter,word_1=speed,
                bytes=(mode,b1,0),floats=(x,y,z),extra_float=extra_float,
                extras=refs,extra_lengths=[len(s)for s in strings],spec_extra=strings[0])


def decode_rope_motion(payload, ropes, rope_positions):
    movement = decode_special_motion(payload)
    refs = movement['extras']
    if movement['bytes'][0] != 33 or not refs or len(set(refs)) != 1 or refs[0][0] != 1:
        raise ValueError('Неисследованный режим MOVE_SPEC')
    rope = refs[0][1]
    origin = rope_positions.get(rope)
    if rope not in ropes or origin is None:
        raise ValueError('Неизвестный трос MOVE_SPEC')
    for point in movement['points']:
        position = point['position']
        if math.dist(position[:2],origin[:2])>1500 or abs(position[2]-origin[2])>10000:
            raise ValueError('MOVE_SPEC вне существующего троса')
    movement['rope_uid'] = rope
    # Прежний bitfield2 был числом привязок, а не признаком движения.
    return movement


def decode_climb_motion(payload, kit, current_position):
    """Наблюдённый крюк: tag2/static-object и тип1 extra, не вертолётный UID.

    Полный индекс статических объектов ещё не восстановлен; граница позиции
    и обычные часы SC38 сохраняются, чужие actor/vehicle attachment запрещены.
    """
    movement=decode_special_motion(payload);refs=movement['extras'];extra=movement['spec_extra']
    if (kit!=200904 or current_position is None or not refs or len(set(refs))!=1
            or refs[0][0]!=2 or not 0<refs[0][1]<2**32
            or movement['bytes'][0]not in (16,33)
            or len(extra)!=4 or extra[0]not in (0x10,0x11,0x12,0x13)
            or extra[1:]!=bytes(3)):
        raise ValueError('Неисследованная привязка крюка MOVE_SPEC')
    if any(math.dist(point['position'],current_position)>1500 for point in movement['points']):
        raise ValueError('Крюк вне текущего положения игрока')
    movement['climb_anchor']=refs[0][1]
    return movement
