"""Внешность удалённого игрока2022 из его серверного профиля.

BE7 decoder140C2A730→140C29C80→140BE86F0: avatar@1240/flag@1260
для проверенного шаблона1516B/name13. Не переносить cache+7BD в wire.
"""
import struct


def apply_peer_profile(payload, avatar, applied, nickname, head=None):
    if (len(payload) != 1516 or struct.unpack_from('>II',payload) != (3,1)
            or struct.unpack_from('>I',payload,16)[0] != 13 or payload[32] != 0
            or len(avatar) != 20 or type(applied) is not bool):
        raise ValueError('Нужен проверенный BE7/name13 и блок внешности20B')
    if not isinstance(nickname,str) or not 1 <= len(nickname) <= 32:
        raise ValueError('Имя игрока:1..32 символа')
    name=nickname.encode('utf-8')+b'\0'
    if len(name)>128 or any(ord(c)<32 for c in nickname):
        raise ValueError('Некорректное имя игрока')
    result=bytearray(payload)
    result[1240:1260]=avatar
    result[1260]=int(applied)
    if head is not None:
        from base_character_2022 import validate_head
        head=validate_head(head)
        # ActorHeadCfg разнесён в BE7: fixed сразу после имени, extended
        # после avatar/accessories/type. Шаблон имеет0морфов и0аксессуаров.
        if struct.unpack_from('>I',result,1261)[0]!=0 or struct.unpack_from('>I',result,1355)[0]!=0:
            raise ValueError('Нужен BE7 с пустыми аксессуарами и морфами')
        result[33:81]=head[:48]
        result[1267:1359]=head[48:]
    # Сначала адресные поля исходного шаблона, затем переменная строка:
    # позиция/clock также патчатся вызывающим кодом ДО этого splice.
    return bytes(result[:16])+struct.pack('>I',len(name))+name+bytes(result[33:])
