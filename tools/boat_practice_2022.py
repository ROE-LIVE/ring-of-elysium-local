"""Лодка203 в исходной точке135136 Iceland; диагностический spawn игрока.

Native decoder140c97ef0: base + два пустых vector + tail =79байт.
Это одиночный стенд, не генератор парка/серверная гидродинамика.
"""
import copy
from pathlib import Path
import struct

BOAT_UID = 0x5040000150136
BOAT_POSITION = (517135,363253,247413)
PLAYER_POSITION = (517135,363253,248200)


def practice_scene(scene):
    """Добавляет лодку и старт над палубой; текущий UID игрока подставит peer."""
    result=copy.deepcopy(scene)
    prototype=None
    own_positions=0
    for rule in result:
        for response in rule.get('responses',[]):
            code=int(response['command'],0)
            if code not in (0x654b,0x27):
                continue
            body=bytearray(Path(response['payload_file']).read_bytes() if 'payload_file' in response
                           else bytes.fromhex(response['payload_hex']))
            if code==0x654b:
                if len(body)>=8 and struct.unpack_from('>Q',body)[0]==BOAT_UID:
                    raise ValueError('BoatPractice: UID лодки уже занят')
                if len(body)==164 and struct.unpack_from('>I',body,8)[0] in (102,109):
                    if body[65] or struct.unpack_from('>2I',body,66)!=(0,5):
                        raise ValueError('Нужна проверенная base/parts fixture дляBoatPractice')
                    prototype=body
            elif rule.get('after_selection'):
                if len(body)!=40 or 0 not in response.get('actor_uid_offsets',[]):
                    raise ValueError('BoatPractice требует own0x27/40')
                struct.pack_into('>3i',body,8,*PLAYER_POSITION)
                response.pop('payload_file',None)
                response.update(payload_hex=body.hex(),fixed_position=True)
                own_positions+=1
    if prototype is None or not own_positions:
        raise ValueError('BoatPractice: нет исходной vehicle или позиции игрока')
    boat=bytearray(prototype[:70]+bytes(4)+prototype[-5:])
    struct.pack_into('>QIII3i',boat,0,BOAT_UID,203,1,24000,*BOAT_POSITION)
    # Проверенный начальный heading270; не объявлять consumer Direction восстановленным.
    struct.pack_into('>4f',boat,33,0,0,-2**-.5,2**-.5)
    result.append(dict(trigger='0x1f49',after_selection=True,batch_responses=True,
                       responses=[dict(command='0x654b',payload_hex=boat.hex())]))
    return result
