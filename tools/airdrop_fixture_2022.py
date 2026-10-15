"""AIRDROP_START и явный native501: primary117, одиночный диагностический режим."""
from pathlib import Path
import struct

# Только публичный501 из record30564; root UID/XYZ заменяются параметрами стенда.
_NATIVE501 = bytes.fromhex('00050400000084f6000001f5000000010000006400075b0400064b96000497c8008000000080000000bf3504f43f3504f300001e0b00000000000000000000000001ffffffff0000000000000002000000010000000100004e2000000000ff00000002000000010000000100000000ff0000000000')


def airdrop_notice(position):
    if (len(position) != 3 or any(type(x) is not int or not -0x80000000 <= x < 0x80000000 for x in position)):
        raise ValueError('AIRDROP_START: нужны3signed32 координаты')
    # Вторые XYZ в четырёх первичных packets равны0; смысл13-го байта неизвестен.
    return struct.pack('>iiiBiiiB', *position, 0, 0, 0, 0, 0)


def native_airdrop_entity(ground):
    if len(ground) != 117 or struct.unpack_from('>I', ground, 8)[0] != 501:
        raise ValueError('Нужен117-байтный ground501')
    body = bytearray(_NATIVE501)
    body[:8] = ground[:8]
    x, y, _ = struct.unpack_from('>3i', ground, 20)
    struct.pack_into('>3i', body, 20, x, y, 301000)
    return bytes(body)


def add_airdrop_notices(scene):
    """Уведомление только для117/501; пустые расписания и Jeep не затрагиваются."""
    for rule in scene:
        responses = rule.get('responses', [])
        if any(int(str(r['command']), 0) == 0x4a6 for r in responses):
            continue
        notices = []
        for response in responses:
            if int(str(response['command']), 0) != 0x654b:
                continue
            path = Path(response['payload_file']) if 'payload_file' in response else None
            if path is not None:
                if path.stat().st_size != 117:
                    continue
                body = path.read_bytes()
            else:
                body = bytes.fromhex(response.get('payload_hex', ''))
            if len(body) == 117 and struct.unpack_from('>I', body, 8)[0] == 501:
                notices.append(dict(command='0x4a6', payload_hex=airdrop_notice(
                    struct.unpack_from('>3i', body, 20)).hex()))
        responses.extend(notices)
    return scene
