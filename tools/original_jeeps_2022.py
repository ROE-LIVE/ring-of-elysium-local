"""Две фиксированные точки Jeep102 карты16010, проверенные Proton190/191/193.

Common1499 ENTITYPOINTCONFIG строки9/4. Выбор102 принудительный;
вероятности/пул/RNG не восстановлены. Quaternion270 — проверенная
диагностическая интерпретация Direction, исходный consumer не найден.
"""
import copy
import math
from pathlib import Path
import struct

POINTS = ((135009, 1001, (360453, 543119, 259497)),
          (135004, 1005, (346855, 565504, 263171)))
UIDS = (0x5040000150001, 0x5040000150002)


def add_original_jeeps(scene):
    """Добавляет машины к существующему сценарию без переноса игрока."""
    result = copy.deepcopy(scene)
    prototype = None
    known = set()
    for rule in result:
        for response in rule.get('responses', []):
            if int(response['command'], 0) != 0x654b:
                continue
            body = (Path(response['payload_file']).read_bytes() if 'payload_file' in response
                    else bytes.fromhex(response['payload_hex']))
            if len(body) >= 8:
                known.add(struct.unpack_from('>Q', body)[0])
            if len(body) == 164 and struct.unpack_from('>I', body, 8)[0] == 102:
                prototype = body
    if prototype is None:
        raise ValueError('Нужна проверенная Jeep102/164 fixture')
    if known.intersection(UIDS):
        raise ValueError('UID исходных точек уже занят')
    replies = []
    for uid, (_, _, position) in zip(UIDS, POINTS):
        body = bytearray(prototype)
        struct.pack_into('>Q', body, 0, uid)
        struct.pack_into('>3i', body, 20, *position)
        struct.pack_into('>4f', body, 33, 0, 0, -math.sqrt(.5), math.sqrt(.5))
        replies.append(dict(command='0x654b', payload_hex=body.hex()))
    result.append(dict(trigger='0x1f49', after_selection=True,
                       batch_responses=True, responses=replies))
    return result
