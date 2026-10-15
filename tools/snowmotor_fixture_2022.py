"""Явная замена Jeep102 на SnowMotor109; без исходного vehicle RNG.

EUVEHICLETABLE_CAR109: HP21600, части1/3/4/5/6 совпадают с выбранной
164-byte fixture. Пассажир, повреждения и прокачка здесь не реализуются.
"""
import copy
from pathlib import Path
import struct


def snowmotor_scene(scene):
    """Сохраняет UID, точки и движение; меняет config только Jeep164."""
    result = copy.deepcopy(scene)
    found = 0
    for rule in result:
        for response in rule.get('responses', []):
            if int(response['command'], 0) != 0x654b:
                continue
            body = bytearray(Path(response['payload_file']).read_bytes() if 'payload_file' in response
                             else bytes.fromhex(response['payload_hex']))
            if len(body) != 164 or struct.unpack_from('>I', body, 8)[0] != 102:
                continue
            if struct.unpack_from('>I', body, 16)[0] != 21600:
                raise ValueError('SnowMotor требует проверенную исходную fixture21600HP')
            struct.pack_into('>I', body, 8, 109)
            response.pop('payload_file', None)
            response['payload_hex'] = body.hex()
            found += 1
    if not found:
        raise ValueError('SnowMotor: нет Jeep102/164 для замены')
    return result
