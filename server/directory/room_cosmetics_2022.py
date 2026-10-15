"""Блоки внешности ENTER_ROOM_RSP2022 по decoder140C3AA30, версия0x5c."""
from local_cosmetics_2022 import LocalCosmetics
from roe_room_2023 import decode_enter_room_response
import struct


def apply_room_cosmetics(payload, catalog_path):
    decoded = decode_enter_room_response(payload)
    sections = {s['name']:s for s in decoded['sections']}
    fields = {f['name']:f for f in decoded['fields']}
    avatar, accessories = sections['mce6'], sections['mcfb']
    flag = fields['mcfa']
    if (avatar['length'] != 20 or flag['offset'] != avatar['offset']+20
            or flag['length'] != 1 or accessories['offset'] != flag['offset']+1
            or accessories['offset']+accessories['length'] != len(payload)):
        raise ValueError('Нужен проверенный хвост ENTER_ROOM2022')
    cosmetics = LocalCosmetics(catalog_path)
    # Этот хвост существует в текущем room decoder; это не BE7/cache+7BD.
    result = (bytes(payload[:avatar['offset']]) + cosmetics.avatar
              + bytes((int(cosmetics.avatar_applied),)) + cosmetics.accessory_sync())
    decode_enter_room_response(result)
    return result, dict(avatar_ids=list(struct.unpack('>5I',cosmetics.avatar)),
                        avatar_applied=cosmetics.avatar_applied,
                        accessory_groups=len({slot for slot,_ in cosmetics.accessory_selection}))
