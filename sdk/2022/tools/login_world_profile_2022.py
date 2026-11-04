"""Идентичность начального LOGIN_WORLD_RSP, rootEXE2022.

Первичный decoder140BDC9C0→140BDBC30/version5B: rootUID+4,
count+16, первая записьUID+20, counted UTF8имя+32. Остальной профиль
сохраняется побайтно; это ограниченная ветка replay с одной записью.
"""
import struct


def apply_login_identity(body,uid,nickname):
    if type(uid)is not int or not 0<uid<2**64:raise ValueError('Неверный публичный UID')
    if not isinstance(nickname,str)or not 1<=len(nickname)<=32 or any(ord(c)<32 for c in nickname):
        raise ValueError('Неверное имя профиля')
    name=nickname.encode('utf-8')+b'\0'
    if len(name)>97:raise ValueError('Имя профиля длиннее96байт')
    if len(body)<37 or struct.unpack_from('>I',body)[0]!=0 or struct.unpack_from('>i',body,16)[0]!=1:
        raise ValueError('Требуется успешный LOGIN_WORLD2022 с одной записью')
    size=struct.unpack_from('>I',body,32)[0]
    if not 1<=size<=128 or 36+size>=len(body):raise ValueError('Неверная длина прежнего имени')
    old=body[36:36+size]
    if old[-1:]!=b'\0'or b'\0'in old[:-1]:raise ValueError('Неверная строка прежнего имени')
    old[:-1].decode('utf-8')
    patched=bytearray(body[:32]);struct.pack_into('>Q',patched,4,uid);struct.pack_into('>Q',patched,20,uid)
    return bytes(patched)+struct.pack('>I',len(name))+name+body[36+size:]
