"""SC25 для диагностического peer: decoder140C59870, consumer141194CA0.

Дельты узлов знаковые и отсчитываются от общего якоря. Это перенос
подтверждённых полей C2S2a; исходная серверная физика не восстановлена.
"""
import math
import struct


def packed_direction(direction):
    if len(direction) != 3 or any(not math.isfinite(v) for v in direction):
        raise ValueError('Неверное направление движения')
    length = math.sqrt(sum(v*v for v in direction))
    if length < 1e-6:
        return 32768, 32768
    x, y, z = (v/length for v in direction)
    return (round((math.atan2(y, x)/math.pi+1)*32767.5),
            round((max(-1, min(1, z))+1)*32767.5))


def encode_peer_trajectory(uid, movement, sequence, tick):
    """Обычное движение; неизвестные режимы/дальние узлы требуют fallback27.

    Позы передаются отдельным27: здесь event=0 не переключает FSM.
    Часы исходных точек сохраняются; клиент получает общий1f57/40мс.
    """
    points = movement['points']
    if not 1 <= len(points) <= 20:
        raise ValueError('Нужно от1 до20 точек движения')
    speed, flags = movement['word_1'], movement['bytes'][0]
    if type(speed) is not int or not 0 <= speed <= 2000 or flags not in (*range(9), 33):
        raise ValueError('Режим движения вне проверенного подмножества')
    anchor = points[0]['position']
    entries = []
    previous = None
    previous_fraction = None
    for point in points:
        position, stamp, fraction = point['position'], point['value'], point['bytes'][2]
        if (len(position) != 3 or any(type(v) is not int or abs(v) > 10000000 for v in position)
                or type(stamp) is not int or not 0 <= stamp < 2**32
                or type(fraction) is not int or not 0 <= fraction < 40):
            raise ValueError('Неверная точка движения')
        delta_tick = ((stamp-tick+2**31) % 2**32)-2**31
        if not -125 <= delta_tick <= 25:
            raise ValueError('Точка движения вне окна общих часов')
        if previous is not None and (((stamp-previous) & 0xffffffff) > 125
                                     or (stamp == previous and fraction < previous_fraction)):
            raise ValueError('Точки движения не упорядочены')
        previous, previous_fraction = stamp, fraction
        delta = tuple(v-a for v, a in zip(position, anchor))
        if any(abs(v) > 3000 for v in delta):
            raise ValueError('Траектория выходит за диагностический предел')
        entries.append((delta, fraction, stamp))
    u, v = packed_direction(movement['floats'])
    payload = struct.pack('>QHiiiBBIB', uid, speed, *anchor, 0,
                          entries[0][1], entries[0][2], len(entries)-1)
    payload += b''.join(struct.pack('>hhhBBI', *delta, 0, fraction, stamp)
                        for delta, fraction, stamp in entries[1:])
    return payload + struct.pack('>BHHI', flags, u, v, sequence)


def encode_peer_stop(uid, position, sequence, tick, pose, direction):
    """Fast commit141194D5A: speed0/N1/event!=0/node.tick==base.tick+1.

    Native255: fast commit сбросил attr134; 256/257 подтвердили автоматическую
    остановку. Опыт обычного N0 осложнён ошибкой журнала и не окончателен.
    Поддержанные события соответствуют выбранным стоянию/приседу/лежанию.
    """
    events = {0:1, 1:2, 2:3}
    if pose not in events:
        raise ValueError('Поза вне проверенного подмножества остановки')
    movement = dict(points=[dict(position=position,bytes=(0,0,0),value=tick),
                            dict(position=position,bytes=(0,0,0),value=(tick+1)&0xffffffff)],
                    word_1=0,bytes=(0,0,0),floats=direction)
    payload = bytearray(encode_peer_trajectory(uid,movement,sequence,tick))
    payload[22] = events[pose]
    return bytes(payload)
