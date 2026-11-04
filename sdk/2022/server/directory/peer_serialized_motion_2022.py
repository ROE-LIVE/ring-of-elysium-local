"""Выбранный subchannel12 из настоящего around1159 сноуборда2022.

Это ограниченный перенос сериализованного управления, не общий RPC-relay.
Образцы 07.10:33/37B, own AccountUIDLE заменяется серверным UnitUIDLE.
"""
import struct


def accepted_controls(member,payload,tick):
    if len(payload) not in (33,37):
        return [],None
    size=struct.unpack_from('>I',payload)[0]
    channel,inner=struct.unpack_from('<II',payload,4)
    owner,count,stamp,fraction=struct.unpack_from('<QIII',payload,12)
    subtype=payload[32]
    if (size!=len(payload)-4 or channel!=12 or inner!=len(payload)-20 or count!=1
            or owner!=member['state']['actor_uid'] or fraction>=40
            or subtype not in ((0,4) if len(payload)==33 else (3,))):
        return [],None
    if len(payload)==37 and struct.unpack_from('<I',payload,33)[0]>0xffff:
        return [],None
    age=((stamp-tick+2**31)%2**32)-2**31
    if not -125<=age<=25:
        return [],None
    previous=member.get('serialized_control_stamp')
    if previous is not None:
        delta=((stamp-previous[0]+2**31)%2**32)-2**31
        if delta<0 or delta==0 and fraction<previous[1]:return [],None
    history=member.setdefault('serialized_controls_seen',[])
    if payload in history:return [],None
    history.append(bytes(payload));del history[:-32]
    member['serialized_control_stamp']=(stamp,fraction)
    body=bytearray(payload);struct.pack_into('<Q',body,12,member['avatar'])
    return [(0x1159,bytes(body))],'serialized_motion'
