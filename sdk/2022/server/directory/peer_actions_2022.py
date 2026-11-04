"""Действия удалённого игрока. UID выбирает сервер; чужой own-инвентарь не выдаётся.

ADS536/16→SC2B24,17→40: собственный ввод Proton01.11 23:07UTC.
Reload SC2B41→27:140E8882A/1412F58F0; IK11D6/корпус30 — прежние codecs.
"""
import math
import struct
from peer_motion_2022 import packed_direction
from peer_serialized_motion_2022 import accepted_controls


def input_action(member,command,payload,tick):
    uid=member['avatar'];packets=[];action=None
    if command==0x1159:return accepted_controls(member,payload,tick)
    if command==0x536 and len(payload)==4:
        word=struct.unpack('>I',payload)[0]
        if word in (16,17):
            value=word==16
            if member.get('aiming',False)==value:return [],None
            member['aiming']=value;packets=[(0x2b,struct.pack('>QI',uid,24 if value else 40))];action='aim'
    elif command in (0x2f,0x11d5) and len(payload)==12:
        values=struct.unpack('>3f',payload)
        if any(not math.isfinite(v) or abs(v)>10000000 for v in values):return [],None
        if command==0x2f:
            if sum(v*v for v in values)<1e-12:return [],None
            body=struct.pack('>QHHff',uid,*packed_direction(values),0,0)
            field='facing';code=0x30
        else:
            if any(abs(v)>360 for v in values):return [],None
            body=struct.pack('>Q3fII',uid,*values,tick,0);field='ik';code=0x11d6
        if member.get(field)==payload:return [],None
        member[field]=payload;packets=[(code,body)];action=field
    elif command==0x11d7 and payload in (b'\0',b'\x03'):
        mode=payload[0]
        if member.get('firing',3)==mode:return [],None
        member['firing']=mode
        packets=[(0x11d8,struct.pack('>BQII',mode,uid,tick,0))];action='fire_motion'
    return packets,action


def accepted_event(member,event,tick=0,payload=b''):
    uid=member['avatar'];action=event.get('action');packets=[]
    if action=='fire' and len(payload)==49:
        values=struct.unpack('>6fIBIIfII',payload)
        shot=values[:6];counter=values[6]
        # 11DA содержит world-end, в отличие от части вариантов11D9.
        # Только принятый WeaponState выстрел: empty/replay не создаютFX.
        if not all(math.isfinite(v) and abs(v)<=10000000 for v in shot):return [],None
        packets=[(0x11d8,struct.pack('>BQII',0,uid,tick,counter)),
                 (0x11d4,struct.pack('>Q6fBII',uid,*shot,0,tick,counter))]
    elif action=='reload_started':
        member['reloading']=True
        packets=[(0x2b,struct.pack('>QI',uid,41))]
    elif (action in ('reload','reload_cancelled','reload_cancelled_on_death') or event.get('reload_cancelled')) and member.pop('reloading',False):
        packets=[(0x2b,struct.pack('>QI',uid,27))]
    elif action=='medical_started':
        member['medical_definition']=event['definition']
        packets=[(0xbee,struct.pack('>QI',uid,event['definition']))]
    elif action in ('medical_finished','medical_cancelled') and member.pop('medical_definition',None):
        packets=[(0x2b,struct.pack('>QI',uid,27))]
    return packets,action if packets else None


def snapshot(member,tick):
    uid=member['avatar'];packets=[]
    if member.get('facing') is not None:
        values=struct.unpack('>3f',member['facing'])
        packets.append((0x30,struct.pack('>QHHff',uid,*packed_direction(values),0,0)))
    if member.get('ik') is not None:
        packets.append((0x11d6,struct.pack('>Q3fII',uid,*struct.unpack('>3f',member['ik']),tick,0)))
    if member.get('aiming'):packets.append((0x2b,struct.pack('>QI',uid,24)))
    if member.get('reloading'):packets.append((0x2b,struct.pack('>QI',uid,41)))
    if member.get('medical_definition'):packets.append((0xbee,struct.pack('>QI',uid,member['medical_definition'])))
    return packets


def aim_snapshot(member):
    """Сохранённый ADS после нативной смены позы/547, без повтора выстрела."""
    if member.get('aiming') and not member.get('reloading') and not member.get('medical_definition'):
        return [(0x2b,struct.pack('>QI',member['avatar'],24))]
    return []
