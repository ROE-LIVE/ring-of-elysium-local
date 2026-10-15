"""Диагностическая стартовая точка у исходной RockWall27930 карты16010.

Proton200/201: native F, FSM20/21, спуск/подъём и выход на землю.
Это фиксированный spawn для проверки; серверный Climb/RNG не реконструирован.
"""
import copy
from pathlib import Path
import struct

POSITION = (548255, 483380, 255000)
HEADING_DEGREES = 203


def practice_scene(scene):
    """Меняет только начальную позицию; UID и тики подставляет endpoint."""
    result = copy.deepcopy(scene)
    found = 0
    for rule in result:
        if not rule.get('after_selection'):
            continue
        for response in rule.get('responses', []):
            if int(response['command'], 0) != 0x27:
                continue
            body = bytearray(Path(response['payload_file']).read_bytes() if 'payload_file' in response
                             else bytes.fromhex(response['payload_hex']))
            if len(body) != 40 or 0 not in response.get('actor_uid_offsets', []):
                raise ValueError('ClimbPractice требует own0x27/40 с UID текущего игрока')
            struct.pack_into('>3i', body, 8, *POSITION)
            response.pop('payload_file', None)
            response.update(payload_hex=body.hex(), fixed_position=True)
            found += 1
    if not found:
        raise ValueError('Не найдена начальная позиция после выбора')
    return result
