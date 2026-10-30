"""Блоки внешности ENTER_ROOM_RSP2022 по decoder140C3AA30, версия0x5c."""
from local_cosmetics_2022 import LocalCosmetics
from roe_room_2023 import decode_enter_room_response
import struct


def account_cosmetics(catalog_path, actor_uid=None):
    """Внешность аккаунта комнаты: файл второго участника (прокси пишет cosmetics-<uid>.json),
    иначе основной профиль этого PC."""
    base = LocalCosmetics(catalog_path)
    if actor_uid is None or base.state_path is None:
        return base
    name = f'cosmetics-{actor_uid:x}.json'
    if base.state_path.with_name(name).exists():
        return LocalCosmetics(catalog_path, state_file=name)
    return base


def apply_room_cosmetics(payload, catalog_path, actor_uid=None):
    decoded = decode_enter_room_response(payload)
    sections = {s['name']:s for s in decoded['sections']}
    fields = {f['name']:f for f in decoded['fields']}
    avatar, accessories = sections['mce6'], sections['mcfb']
    flag = fields['mcfa']
    if (avatar['length'] != 20 or flag['offset'] != avatar['offset']+20
            or flag['length'] != 1 or accessories['offset'] != flag['offset']+1
            or accessories['offset']+accessories['length'] != len(payload)):
        raise ValueError('Нужен проверенный хвост ENTER_ROOM2022')
    cosmetics = account_cosmetics(catalog_path, actor_uid)
    # Этот хвост существует в текущем room decoder; это не BE7/cache+7BD.
    result = (bytes(payload[:avatar['offset']]) + cosmetics.avatar
              + bytes((int(cosmetics.avatar_applied),)) + cosmetics.accessory_sync())
    decode_enter_room_response(result)
    # Хвост (аватар + флаг + аксессуары) совпадает с концом карточки актёра 140c29710 (be86f0, U8, be91a0):
    # голограмма (0x74D0 тип2) берёт его целиком, иначе модель приманки без одежды.
    return result, dict(avatar_ids=list(struct.unpack('>5I',cosmetics.avatar)),
                        appearance_tail=bytes(result[avatar['offset']:]).hex(),
                        avatar_applied=cosmetics.avatar_applied,
                        accessory_groups=len({slot for slot,_ in cosmetics.accessory_selection}),
                        account_state=cosmetics.state_path.name if cosmetics.state_path else None)
