"""Диагностический срок транспорта комнаты; не исходный timeout ROE.

Срок45с превышает существующее окно RELAY30с и не заменяет его авторизацию.
Проверяем только участников, привязанных к комнатам, а не весь UDP session pool.
"""


def expired_members(peer_avatars, shared_loot, now, timeout=45):
    states = {}
    if peer_avatars:
        for member in peer_avatars.members.values():
            states[id(member['state'])] = member['state']
    if shared_loot:
        for room in shared_loot.rooms.values():
            for state in room['members'].values():
                states[id(state)] = state
    expired = []
    for state in states.values():
        anchor = state.get('peer_avatar_anchor')
        last_seen = anchor[2] if anchor else state.get('last_application_at', now)
        if state.get('match_finished'):
            expired.append((state, 'match_finished'))
        elif state.get('transport_retired'):
            expired.append((state, 'transport_retired'))
        elif now - last_seen >= timeout:
            expired.append((state, 'peer_idle_timeout'))
    return expired
