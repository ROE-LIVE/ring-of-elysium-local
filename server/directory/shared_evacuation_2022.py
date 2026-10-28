"""Учебная эвакуация комнаты: четыре общих места и единое завершение.

Условие all_boarded — явная интерпретация требования, не original rule.
Wire/native доставка проверяется отдельно от инвариантов этой модели.
"""
import math
import struct

SEATS = 4


# ICELAND_S.LUA stage04: DoDelayEvent(2400) → stage05 «финальный расчёт» для всех оставшихся.
MATCH_SECONDS = 2400


class SharedEvacuationRooms:
    def __init__(self, delay_seconds, match_seconds=MATCH_SECONDS):
        if (type(delay_seconds) not in (int, float)
                or not math.isfinite(delay_seconds) or not 2 <= delay_seconds <= 60):
            raise ValueError('Ожидание общей эвакуации: 2..60 секунд')
        if type(match_seconds) not in (int, float) or not 60 <= match_seconds <= 7200:
            raise ValueError('Предел матча: 60..7200 секунд')
        self.delay = delay_seconds
        # Вертолёт ждёт: улетает, когда заняты 4 места или сели все живые; иначе по пределу
        # матча (от начала боя комнаты) улетает с теми, кто внутри (возможно пустым) — остальные
        # не спасены. Прежнее правило «через 60 с после первой посадки» было нашим, не исходным.
        self.match_seconds = match_seconds
        self.rooms = {}

    def sync(self, avatars):
        grouped = {}
        for (room_uid, account_uid), member in avatars.members.items():
            state = member['state']
            if not state.get('transport_retired'):
                grouped.setdefault(room_uid, {})[account_uid] = state
        for room_uid in list(self.rooms):
            if room_uid not in grouped:
                del self.rooms[room_uid]
        for room_uid, members in grouped.items():
            room = self.rooms.setdefault(room_uid, dict(members={}, seats={},
                 helicopter=None, due=None, reason=None, finished=False, boarded_at=None))
            room['members'] = members
            for account_uid in list(room['seats']):
                state = members.get(account_uid)
                world = state.get('world') if state else None
                vehicles = state.get('vehicles') if state else None
                if (state is None or world is not None and world.dead
                        or vehicles is None or vehicles.seated != room['helicopter']):
                    del room['seats'][account_uid]

    def geton(self, state, payload, now):
        """Выбор свободного места и native GETON — одна синхронная транзакция."""
        if len(payload) != 12:
            raise ValueError('GETON_REQ ожидает 12 байт')
        uid, requested = struct.unpack('>QI', payload)
        room = self.rooms.get(state['room_uid'])
        account = state['actor_uid']
        vehicle_state = state['vehicles']
        vehicle = vehicle_state.vehicles.get(uid)
        if vehicle is None or vehicle['configuration'] != 6:
            return vehicle_state.handle(0x6541, payload, now)
        if (room is None or room['members'].get(account) is not state
                or room['finished'] or requested not in range(1,5)
                or 'world' not in state or state['world'].dead):
            return [], dict(action='shared_evacuation_geton_rejected', reason='invalid_member_or_state')
        if room['helicopter'] not in (None, uid):
            return [], dict(action='shared_evacuation_geton_rejected', reason='different_helicopter')
        occupied = set(room['seats'].values())
        free = set(range(1,5)) - occupied
        if not free or account in room['seats']:
            return [], dict(action='shared_evacuation_geton_rejected', reason='full_or_duplicate')
        seat = requested if requested in free else min(free)
        packets, event = vehicle_state.handle(0x6541, struct.pack('>QI',uid,seat), now)
        if event['action'] == 'geton':
            room['helicopter'] = uid
            room['seats'][account] = seat
            if room.get('boarded_at') is None:
                room['boarded_at'] = now
            event = dict(event, action='shared_evacuation_geton', requested_seat=requested,
                         occupied=len(room['seats']))
        return packets, event

    def seat_of(self, state):
        """Место участника в общем вертолёте эвакуации или None.

        F (GETOFF) на этом месте — только газета, без выхода (уточнение пользователя27/10:
        в оригинале F открывает газету, игрок остаётся до отлёта). Принятый GETOFF ронял
        игрока с вертолёта, повторный подъём по лестнице не завершался.
        """
        room = self.rooms.get(state.get('room_uid'))
        account = state.get('actor_uid')
        vehicles = state.get('vehicles')
        if (room is None or room['finished'] or room['members'].get(account) is not state
                or account not in room['seats'] or vehicles is None
                or vehicles.seated != room['helicopter']):
            return None
        return room['seats'][account]

    def poll(self, now):
        """Возвращает решение комнаты; fixture/result commit выполняет endpoint."""
        decisions, events = [], []
        for room_uid, room in self.rooms.items():
            # Досрочно вышедший (F в вертолёте) уже получил газету: не ждать его как «загружающегося».
            members = {uid: state for uid, state in room['members'].items() if not state.get('match_finished')}
            if room['finished'] or not members:
                continue
            # Загружающийся участник ещё не считается погибшим или спасённым.
            if any(state.get('world') is None for state in members.values()):
                if room['due'] is not None:
                    events.append(dict(action='shared_evacuation_wait_cancelled',
                                       room_uid=hex(room_uid), reason='loading_member'))
                room['due'] = room['reason'] = None
                continue
            alive = {uid for uid,state in members.items() if not state['world'].dead}
            seated = set(room['seats'])
            if not seated:
                room['boarded_at'] = None
            starts = [state['match_statistics'].started_at for state in members.values()
                      if state.get('match_statistics') is not None
                      and state['match_statistics'].started_at is not None]
            deadline = min(starts) + self.match_seconds if starts else None
            reason = ('no_survivors' if not alive else
                      'four_seats' if len(seated) == 4 else
                      'all_boarded' if seated and alive <= seated else
                      'timeout' if deadline is not None and now >= deadline else None)
            if reason is None:
                if room['due'] is not None:
                    events.append(dict(action='shared_evacuation_wait_cancelled',room_uid=hex(room_uid)))
                room['due'] = room['reason'] = None
                continue
            if room['due'] is None or room['reason'] != reason:
                room['reason'] = reason
                room['due'] = (now if reason == 'no_survivors' else
                               deadline if reason == 'timeout' else now+self.delay)
                events.append(dict(action='shared_evacuation_wait', room_uid=hex(room_uid),
                                   reason=reason, alive=len(alive), occupied=len(seated)))
            if now < room['due']:
                continue
            # Сначала приготовить все recipient-specific результаты; затем commit.
            decisions.append(dict(room_uid=room_uid, reason=reason, room=room,
                                  helicopter_uid=room['helicopter'] or 0,
                                  seats=dict(room['seats']), members=dict(members),
                                  ended_at=room['due']))
        return decisions, events

    def commit(self, decision):
        room = self.rooms.get(decision['room_uid'])
        if room is not decision['room'] or room['finished']:
            raise ValueError('Устаревшее решение эвакуации')
        room['finished'] = True


def encode_end_info(seats, occupied, position):
    """Второй U16 — свободные места (игра27/10: (4, 1) при одном на борту показало3 занятых)."""
    return _encode_end_info(seats, max(0, seats-occupied), position)


def _encode_end_info(seats, free, position):
    """0x657F EU_PLANE_MSGID_END_INFO_SYNC (декодер140c9b370, обработчик140e75fa0 → событие
    EVENT_ICELAND_SEAT_INFO_UPDATED): U16, U16, POS13, U32, POS13, U32 (38 байт).
    Обработчик пишет два U16 в объект вертолёта (+0x13C/+0x140), x,y первой POS13 и xyz второй.
    U16 мест всего, U16 свободно (проверено в игре); позиции — вертолёт; U32 — 0.
    """
    x, y, z = (int(v) for v in position)
    pos = struct.pack('>iiiB', x, y, z, 0)
    return struct.pack('>HH', seats, free) + pos + struct.pack('>I', 0) + pos + struct.pack('>I', 0)
