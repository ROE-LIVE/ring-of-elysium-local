"""0x0480 SCENE_MSGID_ROOM_ACTOR_KILL_BROADCAST — лента «X eliminated Y / Remaining N».

Формат (BE) по декодеру клиента2022 140c3d660 (switch 0x3E9..0x4A6, таблица 140c73194) и
SWIG getters ROOM_KILL_BROADCAST_*_get 141442590..141447080 (порядок getters = порядок полей):
  U64 ullKiller_rid, STR szKiller_name, U64 ullDowner_rid, STR szDowner_name,
  U32 iKill_weapon_id, U64 ullActor_rid, STR szActor_name,
  U32 iAlive (+0x19C), U32 iVehicle, U32 iReason (+0x1A4),
  U8 bHit_down, bKill_team, bDown_team, bCop_team, bHit_head (+0x1AC),
  U32 iExtra_exp, iKiller_rank_head_icon_id, iDowner_rank_head_icon_id, iActor_rank_head_icon_id.
STR = U32 длина (1..128, с завершающим NUL) + байты; пустая строка — один NUL.
iReason выбирает подпись STR_KILL_WAY_<iReason> (GAMESTRINGTABLE_EU_INGAME, TableBin00000028d,
English): с убийцей «eliminated» — 1, 2, 4, 5, 22, 23, 24; без убийцы « is eliminated» — 3, 6..11,
13..16, 19, 20, 27, 101..105, 122. Игра27/10: iReason0 показал сырой ключ STR_KILL_WAY_0 и не
вывел убийцу. Берём1 (убийство игроком) и3 (смерть без убийцы); различие зона/падение не известно.
"""
import struct

KILL_WAY_PLAYER = 1
KILL_WAY_SELF = 3


def encode_string(text):
    raw = (text or '').encode('utf-8')[:127] + b'\0'
    if raw.index(b'\0') != len(raw)-1:
        raise ValueError('Имя с NUL внутри')
    return struct.pack('>I', len(raw)) + raw


def encode_kill_broadcast(actor_rid, actor_name, alive, killer_rid=0, killer_name='',
                          weapon_id=0, hit_head=False, reason=None):
    """Тело0x0480. Без убийцы (зона/падение) — killer_rid0 и пустое имя."""
    if reason is None:
        reason = KILL_WAY_PLAYER if killer_rid else KILL_WAY_SELF
    if not 0 <= alive < 2**31 or not 0 <= weapon_id < 2**32:
        raise ValueError('Неверные поля ленты убийств')
    return (struct.pack('>Q', killer_rid) + encode_string(killer_name)
            + struct.pack('>Q', 0) + encode_string('')
            + struct.pack('>IQ', weapon_id, actor_rid) + encode_string(actor_name)
            + struct.pack('>III', alive, 0, reason)
            + bytes((0, 0, 0, 0, int(bool(hit_head))))
            + struct.pack('>IIII', 0, 0, 0, 0))


def decode_kill_broadcast(body):
    """Обратное чтение для тестов/журнала (повторяет проверки декодера клиента)."""
    offset = 0

    def take(fmt):
        nonlocal offset
        values = struct.unpack_from(fmt, body, offset)
        offset += struct.calcsize(fmt)
        return values

    def string():
        nonlocal offset
        size, = take('>I')
        raw = body[offset:offset+size]
        if not 1 <= size <= 128 or len(raw) != size or raw.index(b'\0') != size-1:
            raise ValueError('Неверная строка0x0480')
        offset += size
        return raw[:-1].decode('utf-8')

    killer_rid, = take('>Q'); killer_name = string()
    downer_rid, = take('>Q'); downer_name = string()
    weapon_id, actor_rid = take('>IQ'); actor_name = string()
    alive, vehicle, reason = take('>III')
    flags = take('>5B')
    extra = take('>IIII')
    if offset != len(body):
        raise ValueError('Лишние байты0x0480')
    return dict(killer_rid=killer_rid, killer_name=killer_name, downer_rid=downer_rid,
                downer_name=downer_name, weapon_id=weapon_id, actor_rid=actor_rid,
                actor_name=actor_name, alive=alive, vehicle=vehicle, reason=reason,
                hit_head=bool(flags[4]), flags=flags, extra=extra)


def encode_kill_count(actor_uid, kills, killed=0, assists=0):
    """0x047E ROOM_ACTOR_KILL_COUNT (декодер140c01cf0, getters141447de0..1414489c0):
    U32 iKill_count, U64 ullActor_rid, U32 iKilled_count, U32 iAssist_count."""
    return struct.pack('>IQII', kills, actor_uid, killed, assists)


def encode_alive_count(alive, team_alive):
    """0x047D ROOM_ALIVE_ACTOR_COUNT (декодер140c27d10, getters141447540/141447950):
    U32 iAlive_count, U32 iTeam_alive_count."""
    return struct.pack('>II', alive, team_alive)
