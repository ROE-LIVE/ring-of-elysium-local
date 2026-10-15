"""Диагностическая траектория plane6 по публичному захвату2022.

MOVE_BC6575/73 decoder140C98C90; PATH_CHANGE6588/12.
Данные исходные, перенос площадки и интерполяция — наш сценарий.
Полный departure в первичном захвате отсутствует.
"""
import copy
import math
from pathlib import Path
import struct

_ENTER = bytes.fromhex('00050400000084fa0000000600000009000000640007d0160008009f00040103000000000000000000bf6999673ed1736500001b00000000010000000000000000020000000000000000000000000000000100000001000000010000000000000000ff0000000000')
_MOVE = bytes.fromhex('00050400000084fa00007d55000007d0160008009f000401030044866000c46f8000000000000000000000000000000000000000000000000000000000bf6999673ed1736500042392')
_POINTS = ((30883, (460335, 570508, 262403)), (32085, (512022, 524447, 262403)), (32235, (518472, 518699, 262403)), (32385, (524922, 512951, 262403)), (32535, (531372, 507203, 262403)), (32685, (537822, 501455, 262403)), (32835, (544272, 495707, 262403)), (32985, (550722, 489960, 262403)), (33135, (557172, 484212, 262403)), (33285, (563623, 478464, 262403)), (33435, (570073, 472716, 262403)), (33584, (572321, 470713, 260068)), (33734, (572321, 470713, 256420)), (33884, (572321, 470713, 252772)), (33885, (572321, 470713, 252771)))


def _body(response):
    return (Path(response['payload_file']).read_bytes() if 'payload_file' in response
            else bytes.fromhex(response['payload_hex']))


def native_evacuation_scene(scene):
    """Заменяет одну фиксированную выдачу вертолёта, не двигая игрока.

    Сохраняет время hover и текущие rope/link/end-сообщения. Полёт длится
    120.08сек, поэтому слишком ранняя выдача явно отклоняется.
    Tick+8 патчится по текущим часам; интерполяция с шагом10ticks=0.4сек.
    """
    scene=copy.deepcopy(scene)
    matches=[]
    for index,rule in enumerate(scene):
        for response in rule['responses']:
            if int(response['command'],0)!=0x654b:continue
            body=_body(response)
            if len(body)==104 and struct.unpack_from('>I',body,8)[0]==6:
                matches.append((index,rule,response,body))
    if len(matches)!=1:
        raise ValueError('Нужна одна проверенная выдача plane6/104')
    index,rule,response,old=matches[0]
    if rule.get('after_selection') is not True:
        raise ValueError('Нужен отсчёт после выбора старта')
    hover_at=rule.get('after_selection_delay_seconds',0)
    duration=(_POINTS[-1][0]-_POINTS[0][0])/25
    if type(hover_at) not in (int,float) or not math.isfinite(hover_at) or not duration<=hover_at<=1800:
        raise ValueError('Hover должен оставлять120.08сек на полёт')
    uid=struct.unpack_from('>Q',old)[0]
    target=struct.unpack_from('>3i',old,20)
    delta=tuple(a-b for a,b in zip(target,_POINTS[-1][1]))
    def position(p):
        result=tuple(a+b for a,b in zip(p,delta))
        if any(not -2**31<=v<2**31 for v in result):raise ValueError('XYZ вне int32')
        return result
    entry=bytearray(_ENTER)
    struct.pack_into('>Q',entry,0,uid)
    struct.pack_into('>3i',entry,20,*position(_POINTS[0][1]))
    replies=[r for r in rule['responses'] if r is not response]
    replies.insert(0,dict(command='0x6588',payload_hex=struct.pack('>QI',uid,2).hex()))
    rule['responses']=replies
    rule['batch_responses']=True
    start=hover_at-duration
    def append(at,responses):
        scene.append(dict(trigger=rule['trigger'],after_selection=True,
            after_selection_delay_seconds=round(at,5),batch_responses=True,responses=responses))
    append(start,[dict(command='0x654b',payload_hex=entry.hex())])
    move=bytearray(_MOVE)
    struct.pack_into('>Q',move,0,uid)
    ticks=list(range(_POINTS[0][0],_POINTS[-1][0],10))+[_POINTS[-1][0]]
    for tick in ticks:
        for left,right in zip(_POINTS,_POINTS[1:]):
            if left[0]<=tick<=right[0]:break
        fraction=(tick-left[0])/(right[0]-left[0])
        p=tuple(round(a+(b-a)*fraction) for a,b in zip(left[1],right[1]))
        struct.pack_into('>3i',move,13,*position(p))
        append(start+(tick-_POINTS[0][0])/25,[dict(command='0x6575',payload_hex=move.hex(),clock_tick_offsets=[8])])
    # state1 первичного захвата: начало снижения через104.178503сек.
    append(start+104.178503,[dict(command='0x6588',payload_hex=struct.pack('>QI',uid,1).hex())])
    # Последняя координата MOVE должна примениться до state2/rope.
    rule['after_selection_delay_seconds']=round(hover_at+.08,5)
    return sorted(scene,key=lambda r:r.get('after_selection_delay_seconds',0))
