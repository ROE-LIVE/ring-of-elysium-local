"""Ограниченный опыт транспорта2022: Jeep/SnowMotor/boat/эвакуация.

Формы проверены native-декодерами c98400/c98580; физика остаётся
клиентской. Это диагностический сервер, без проверки столкновений.
"""
from collections import OrderedDict
from dataclasses import dataclass
import json
import math
from pathlib import Path
import struct
import time
from match_result_2022 import MatchEndPolicy

_DEPARTURE_MOVE = bytes.fromhex('00050400000084fa00007d55000007d0160008009f000401030044866000c46f8000000000000000000000000000000000000000000000000000000000bf6999673ed1736500042392')

def diagnostic_departure_move(uid, origin, seconds, tick):
    """Собственный прямой отлёт: скорости1328/1382 из PlaneBattleEnd/group1.

    Направление продолжает исходный подход; поворот12 и оригинальный
    алгоритм отлёта не восстановлены. Не выдавать эту кривую за захват.
    """
    if type(uid) is not int or not 0<uid<2**64:
        raise ValueError('Неверный UID plane6')
    if (len(origin)!=3 or any(type(n) is not int or not -2**31<=n<2**31 for n in origin)
            or type(seconds) not in (int,float) or not math.isfinite(seconds) or not 0<=seconds<=30
            or type(tick) is not int or not 0<=tick<2**32):
        raise ValueError('Неверное время/позиция/тик диагностического отлёта')
    scale=1328/math.hypot(1075,-958)
    position=tuple(round(a+seconds*v) for a,v in zip(origin,(1075*scale,-958*scale,1382)))
    if any(not -2**31<=n<2**31 for n in position):raise ValueError('XYZ вне int32')
    body=bytearray(_DEPARTURE_MOVE)
    struct.pack_into('>QI',body,0,uid,tick)
    struct.pack_into('>3i',body,13,*position)
    return bytes(body),position



def survivor_event(helicopter_uid, actor_uid, name, slot):
    """6580: проверенный путь EVENT_NEWSPAPER_ANOTHER_SURVIVALNAME.

    Native140e71ff8 использует wire+0x0c как индекс места. Последнее
    слово передаётся AnotherSurvival как rankIconId (140e72200), а строки
    Lua добавляет по порядку. Ранг не восстановлен, поэтому0 без значка.
    Первое слово1 сохранено из положительного опыта. Это не флаг победы.
    """
    encoded = name.encode('utf-8')
    if not encoded or len(encoded) > 127 or b'\0' in encoded or slot not in range(1, 5):
        raise ValueError('Имя выжившего: 1..127 байт без NUL; строка 1..4')
    if not helicopter_uid or not actor_uid:
        raise ValueError('Нужны UID вертолёта и игрока')
    return (struct.pack('>QIIQI', helicopter_uid, 1, slot, actor_uid, len(encoded)+1)
            + encoded + b'\0' + struct.pack('>II', 0, 0))


@dataclass(frozen=True)
class EvacuationUIFixture:
    """Явный диагностический мост к экрану итогов, с двумя режимами.

    106E → D62 перед 6589 подтверждено на клиенте. Семантика причины15
    и оригинальный расчёт наград ещё не восстановлены. Архивные числа
    включаются явно; session_statistics подставляет проверенный учёт
    собственного сеанса, оставляя рейтинг и награды нулевыми.
    """
    terminal: bytes
    outcome: bytes
    climb_protection_seconds: float = 0
    session_statistics: bool = False
    result_on_death: bool = False
    timeout_seconds: float | None = None
    diagnostic_departure_seconds: float = 0

    @classmethod
    def load(cls, path):
        path = Path(path)
        config = json.loads(path.read_text())
        session_statistics = config.get('reconstructed_session_statistics') is True
        archive_statistics = config.get('diagnostic_archive_statistics') is True
        if session_statistics == archive_statistics:
            raise ValueError('Нужен один явный режим: архивный или учёт собственного сеанса')
        policy = MatchEndPolicy(config.get('singleplayer_result_on_death', False),
                                config.get('singleplayer_timeout_seconds'))
        if policy.enabled and not session_statistics:
            raise ValueError('Окончание своего матча требует reconstructed_session_statistics')
        terminal_path, outcome_path = path.parent/config['terminal_file'], path.parent/config['outcome_file']
        if terminal_path.stat().st_size != 41 or outcome_path.stat().st_size != 174:
            raise ValueError('Неверные размеры терминальных fixture')
        terminal = terminal_path.read_bytes()
        outcome = outcome_path.read_bytes()
        if (len(terminal) != 41 or len(outcome) != 174
                or struct.unpack_from('>I', terminal, 8)[0] != 4
                or terminal[12:16] != b'XXX\0'
                or terminal[16:29] != bytes(8)+struct.pack('>I', 1)+b'\0'
                or terminal[29:] != struct.pack('>III', 0, 0, 15)
                or struct.unpack_from('>Q', outcome)[0] != 1
                or struct.unpack_from('>I', outcome, 16)[0] != 4
                or outcome[20:24] != b'XXX\0'
                or outcome[-2:] != b'\0\1'):
            raise ValueError('Нужны проверенные терминальные fixture 2022 для комнаты1')
        protection = config.get('climb_protection_seconds', 0)
        if type(protection) not in (int, float) or not math.isfinite(protection) or not 0 <= protection <= 30:
            raise ValueError('Диагностическая защита подъёма: 0..30 секунд')
        departure=config.get('diagnostic_departure_seconds',0)
        if (type(departure) not in (int,float) or not math.isfinite(departure)
                or departure!=0 and not 2<=departure<=30
                or departure and not session_statistics):
            raise ValueError('Собственный отлёт:0 либо2..30сек, только reconstructed statistics')
        return cls(terminal, outcome, protection, session_statistics,
                   policy.on_death, policy.timeout_seconds, departure)

    def messages(self, actor_uid, room_uid=1, statistics=None, display_name=None):
        terminal, outcome = bytearray(self.terminal), bytearray(self.outcome)
        struct.pack_into('>Q', terminal, 0, actor_uid)
        struct.pack_into('>Q', outcome, 0, room_uid)
        struct.pack_into('>Q', outcome, 8, actor_uid)
        if self.session_statistics:
            if statistics is None:
                raise ValueError('Для собственного результата нужен завершённый учёт сеанса')
            encoded = (display_name or 'LOCAL').encode('utf-8')
            if not encoded or len(encoded) > 127 or b'\0' in encoded:
                raise ValueError('Имя результата: 1..127 байт без NUL')
            # Проверенные wire-поля исходного шаблона с именем XXX. Урон
            # и damage points — U64, decoder140C47D6E/140C47D85. UI делит
            # raw damage на10; distance на100. Награды не восстановлены.
            for offset in (24, 28, *range(40, 108, 4)):
                struct.pack_into('>I', outcome, offset, 0)
            struct.pack_into('>II', outcome, 24, int(bool(statistics['rescued'])), 1)
            struct.pack_into('>I', outcome, 40, statistics['kills'])
            struct.pack_into('>Q', outcome, 48, statistics['damage_raw'])
            struct.pack_into('>I', outcome, 84, statistics['distance_cm'])
            struct.pack_into('>I', outcome, 88, statistics['rescued'])
            struct.pack_into('>I', outcome, 92, statistics['survival_seconds'])
            # Рейтинг/награды/суммарные счётчики аккаунта пока0; структуры
            # и NUL-строки хвоста сохраняются. Причина106E15 остаётся
            # диагностическим мостом к UI, её исходный смысл неизвестен.
            outcome[112:124] = bytes(12)
            outcome[144:172] = bytes(28)
            terminal = terminal[:8]+struct.pack('>I', len(encoded)+1)+encoded+b'\0'+terminal[16:]
            outcome = outcome[:16]+struct.pack('>I', len(encoded)+1)+encoded+b'\0'+outcome[24:]
        return [(0x106e, bytes(terminal)), (0xd62, bytes(outcome))]


def decode_vehicle_hit(payload):
    """Проверенный WITH_DIR_REQ98: SWIG1414821B0..1414869D0.

    iBullet_id/+82 соответствует counter принятого11DA; iPellet_index/+94
    отдельный от сквозного dwShoot_id/+0. Позиции float32 в мировых см.
    """
    if len(payload) != 98:
        raise ValueError('SHOOT_VEHICLE_TARGET_WITH_DIR_REQ ожидает98байт')
    fields = {
        'shoot_id': struct.unpack_from('>I', payload)[0],
        'target': struct.unpack_from('>Q', payload, 4)[0],
        'shooter_stand': struct.unpack_from('>3i', payload, 12),
        'gun_position': struct.unpack_from('>3f', payload, 25),
        'target_stand': struct.unpack_from('>3i', payload, 41),
        'hit_position': struct.unpack_from('>3f', payload, 54),
        'target_tick': struct.unpack_from('>I', payload, 66)[0],
        'part': payload[74],
        'counter': struct.unpack_from('>I', payload, 82)[0],
        'shooter_tick': struct.unpack_from('>I', payload, 90)[0],
        'pellet': struct.unpack_from('>I', payload, 94)[0],
    }
    for name in ('shooter_stand', 'gun_position', 'target_stand', 'hit_position'):
        if any(not math.isfinite(x) or abs(x) > 10000000 for x in fields[name]):
            raise ValueError('Неверная мировая позиция попадания транспорта')
    return fields


class VehicleState:
    def __init__(self, actor_uid, evacuation_delay=None, survivor_name=None, result_fixture=None, room_uid=1, statistics=None, diagnostic_pellet_damage=None):
        if diagnostic_pellet_damage is not None and (
                type(diagnostic_pellet_damage) is not int or not 1 <= diagnostic_pellet_damage <= 5000):
            raise ValueError('Учебный урон транспорту требует1..5000')
        self.diagnostic_pellet_damage = diagnostic_pellet_damage
        self.shots = OrderedDict()
        self.vehicle_hits = set()
        self.actor_uid = actor_uid
        self.vehicles = {}
        self.ropes = {}
        self.seated = None
        self.seat = None
        self.evacuation_delay = evacuation_delay
        self.seated_at = None
        self.evacuation_finished = False
        self.survivor_name = survivor_name
        self.result_fixture = result_fixture
        self.room_uid = room_uid
        self.statistics = statistics
        self.climb_until = 0
        self.dead = False
        self.departure_origin = None
        self.departure_tick = None
        if survivor_name is not None:
            survivor_event(1, actor_uid, survivor_name, 1)

    def register(self, command, payload):
        if command == 0x6554 and len(payload) == 16:
            # Native/SWIG STATUS_BC: UID,+8 iCur_hp,+12 iCur_st.
            uid, hp, status = struct.unpack('>QII', payload)
            vehicle = self.vehicles.get(uid)
            maximum = {102: 21600, 109: 21600, 203: 24000}.get(vehicle['configuration']) if vehicle else None
            if maximum is not None and hp <= maximum and status in (1, 2, 3):
                vehicle.update(hp=hp, status=status)
            return
        if command == 0x6575 and len(payload) == 73:
            # Серверный MOVE_BC, decoder140C98C90; не принимать как client MOVE_REQ.
            uid = struct.unpack_from('>Q', payload)[0]
            vehicle = self.vehicles.get(uid)
            if vehicle and vehicle['configuration'] == 6:
                vehicle['position'] = struct.unpack_from('>iii', payload, 13)
                vehicle.setdefault('flight_phase', 0)
            return
        if command == 0x6588 and len(payload) == 12:
            uid, phase = struct.unpack('>QI', payload)
            vehicle = self.vehicles.get(uid)
            if vehicle and vehicle['configuration'] == 6 and phase in (1, 2):
                vehicle['flight_phase'] = phase
            return
        if command == 0x654b and len(payload) == 87:
            uid, configuration = struct.unpack_from('>QI', payload)
            if uid and configuration == 7:
                self.ropes[uid] = None
            return
        if command == 0x657b and len(payload) == 16:
            rope, parent = struct.unpack('>QQ', payload)
            if rope in self.ropes and parent in self.vehicles and self.vehicles[parent]['configuration'] == 6:
                self.ropes[rope] = parent
            return
        if command != 0x654b or len(payload) not in (79, 104, 164):
            return
        uid, configuration, status, hp = struct.unpack_from('>QIII', payload)
        if (configuration, len(payload)) not in ((102, 164), (109, 164), (203, 79), (6, 104)) or not uid:
            return
        self.vehicles[uid] = {'configuration': configuration, 'hp': hp, 'status': status,
                              'position': struct.unpack_from('>iii', payload, 20)}
        if configuration == 203:
            self.vehicles[uid]['initial_rotation'] = struct.unpack_from('>4f', payload, 33)

    def note_fire(self, payload, event, now=None):
        if event.get('action') != 'fire' or len(payload) != 49:
            return
        counter, tick = struct.unpack_from('>I', payload, 24)[0], struct.unpack_from('>I', payload, 29)[0]
        self.shots[(counter, tick)] = (struct.unpack_from('>3f', payload),
                                      event.get('gun_definition'), time.monotonic() if now is None else now)
        while len(self.shots) > 64:
            key, _ = self.shots.popitem(last=False)
            self.vehicle_hits = {hit for hit in self.vehicle_hits if hit[:2] != key}

    def vehicle_hit(self, payload, now):
        hit = decode_vehicle_hit(payload)
        uid = hit['target']
        vehicle = self.vehicles.get(uid)
        event = dict(action='vehicle_hit_decoded', uid=hex(uid), part=hit['part'],
                     counter=hit['counter'], tick=hit['shooter_tick'], pellet=hit['pellet'],
                     original_damage_formula=False)
        if self.diagnostic_pellet_damage is None:
            return [], event
        key = (hit['counter'], hit['shooter_tick'])
        identity = (*key, hit['pellet'])
        accepted = self.shots.get(key)
        reason = None
        if vehicle is None or vehicle['configuration'] not in (102, 109) or not vehicle['hp']:
            reason = 'unknown_or_dead_ground_vehicle'
        elif self.seated is not None:
            reason = 'shooter_seated'
        elif hit['part'] != 0:
            reason = 'only_body_supported'
        elif accepted is None or not 0 <= now-accepted[2] <= 2:
            reason = 'unaccepted_or_expired_shot'
        elif identity in self.vehicle_hits:
            reason = 'duplicate_pellet'
        elif sum(h[:2] == key for h in self.vehicle_hits) >= (12 if accepted[1] == 10402 else 1):
            reason = 'shot_hit_limit'
        elif math.dist(hit['gun_position'], accepted[0]) > 2:
            reason = 'gun_origin_mismatch'
        elif math.dist(accepted[0], vehicle['position']) > 10000:
            reason = 'diagnostic_range'
        elif (math.dist(hit['target_stand'], vehicle['position']) > 300
              or math.dist(hit['hit_position'], vehicle['position']) > 600):
            reason = 'outside_diagnostic_vehicle_radius'
        if reason:
            return [], dict(event, action='vehicle_hit_rejected', reason=reason)
        self.vehicle_hits.add(identity)
        before = vehicle['hp']
        hp = max(0, before-self.diagnostic_pellet_damage)
        # Выбранная учебная связь порога и состояния; не исходный consumer.
        status = 3 if hp == 0 else (2 if hp <= 10800 else 1)
        self.register(0x6554, struct.pack('>QII', uid, hp, status))
        return [(0x6554, struct.pack('>QII', uid, hp, status))], dict(
            event, action='diagnostic_vehicle_damage', damage=before-hp,
            hp=hp, status=status, collision_mesh_verified=False)

    def handle(self, command, payload, now=None):
        now = time.monotonic() if now is None else now
        if self.dead:
            return [], {'action': 'vehicle_request_after_death', 'command': hex(command)}
        # После 6589 клиент ещё способен отправить F/GETOFF с нулевой
        # позицией. Завершённый одиночный опыт не возобновляет игру.
        if self.evacuation_finished:
            return [], {'action': 'vehicle_request_after_finish', 'command': hex(command)}
        if command == 0x11de:
            return self.vehicle_hit(payload, now)
        if command == 0x657a:
            if len(payload) != 33:
                raise ValueError('ROPE_OPERATE_REQ ожидает33байта')
            rope = struct.unpack_from('>Q', payload)[0]
            parent = self.vehicles.get(self.ropes.get(rope), {})
            if (self.ropes.get(rope) is None or self.seated is not None
                    or parent.get('flight_phase', 2) != 2):
                return [], {'action': 'climb_rejected', 'rope': hex(rope)}
            grace = self.result_fixture.climb_protection_seconds if self.result_fixture else 0
            # Контрольный опыт, не найденное исходное правило: исключить
            # прерывание подъёма атакой упрощённого бота каждые3секунды.
            self.climb_until = now+grace
            return [], {'action': 'climb_requested', 'rope': hex(rope),
                        'diagnostic_protection_seconds': grace, 'experimental': True}
        if command == 0x6541:
            if len(payload) != 12:
                raise ValueError('GETON_REQ ожидает12байт')
            uid, seat = struct.unpack('>QI', payload)
            vehicle = self.vehicles.get(uid)
            seats = (range(1, 5) if vehicle and vehicle['configuration'] == 6 else
                     (range(1, 3) if vehicle and vehicle['configuration'] in (102, 109) else (1,)))
            if (vehicle is None or seat not in seats or self.seated is not None
                    or vehicle.get('flight_phase', 2) != 2
                    or vehicle['configuration'] in (102, 109, 203) and (not vehicle['hp'] or (vehicle['status'] & 3) == 3)):
                return [], {'action': 'geton_rejected', 'uid': hex(uid), 'seat': seat}
            self.seated = uid
            self.seat = seat
            self.seated_at = now
            self.departure_origin = self.departure_tick = None
            self.climb_until = 0
            response = struct.pack('>QIIQIIiiiB', uid, vehicle['configuration'],
                                   0, self.actor_uid, seat, 0,
                                   *vehicle['position'], 0)
            return [(0x6542, response)], {'action': 'geton', 'uid': hex(uid),
                                         'seat': seat, 'configuration': vehicle['configuration']}
        if command == 0x6547:
            if len(payload) != 4:
                raise ValueError('SWITCH_SEAT_REQ ожидает4байта')
            destination = struct.unpack('>I', payload)[0]
            vehicle = self.vehicles.get(self.seated)
            # Проверены102/109, два места. Другие модели не включать по имени.
            if (vehicle is None or vehicle['configuration'] not in (102, 109)
                    or destination not in (1, 2) or not vehicle['hp'] or vehicle['status'] == 3):
                return [], {'action': 'seat_switch_rejected', 'destination': destination}
            previous = self.seat
            if destination == previous:
                return [], {'action': 'seat_switch_duplicate', 'seat': destination}
            self.seat = destination
            response = struct.pack('>QQIII', self.seated, self.actor_uid, previous, destination, 0)
            return [(0x6548, response)], {'action': 'seat_switch', 'uid': hex(self.seated),
                                        'source': previous, 'destination': destination}
        if command == 0x6549:
            if len(payload) != 73:
                raise ValueError('MOVE_REQ наземного транспорта ожидает73байта')
            uid = struct.unpack_from('>Q', payload)[0]
            if uid != self.seated or self.vehicles[uid]['configuration'] not in (102, 109, 203):
                return [], {'action': 'move_rejected', 'uid': hex(uid)}
            if self.seat != 1:
                return [], {'action': 'move_rejected', 'uid': hex(uid), 'reason': 'passenger_cannot_drive'}
            if not self.vehicles[uid]['hp'] or (self.vehicles[uid]['status'] & 3) == 3:
                return [], {'action': 'move_rejected', 'uid': hex(uid), 'reason': 'destroyed_vehicle'}
            position = struct.unpack_from('>iii', payload, 13)
            self.vehicles[uid]['position'] = position
            return [], {'action': 'vehicle_move', 'uid': hex(uid), 'position': position}
        if command == 0x6543:
            if len(payload) != 14:
                raise ValueError('GETOFF_REQ ожидает14байт')
            if self.seated is None:
                return [], {'action': 'getoff_rejected'}
            uid = self.seated
            position = struct.unpack_from('>iii', payload, 1)
            vehicle=self.vehicles[uid]
            boat_exit_fallback = False
            if vehicle['configuration'] == 203 and position == (0,0,0):
                # Собственный fallback для запроса205 с нулевыми XYZ.
                # Seat1 off=(215,163,200) из EUVEHICLETABLE_SHIP203.
                # Используется начальная ориентация fixture, не исходная
                # серверная физика выхода после поворота/столкновения.
                x,y,z,w = vehicle['initial_rotation']
                if not all(math.isfinite(v) for v in (x,y,z,w)) or not .99 <= x*x+y*y+z*z+w*w <= 1.01:
                    return [],dict(action='getoff_rejected',uid=hex(uid),reason='invalid_boat_fixture_rotation')
                v=(215,163,200)
                t=(2*(y*v[2]-z*v[1]),2*(z*v[0]-x*v[2]),2*(x*v[1]-y*v[0]))
                cross=(y*t[2]-z*t[1],z*t[0]-x*t[2],x*t[1]-y*t[0])
                position=tuple(round(p+a+w*b+c) for p,a,b,c in zip(vehicle['position'],v,t,cross))
                boat_exit_fallback = True
            # Собственная диагностическая граница10м для Jeep: отказ не
            # меняет место/позицию и не разрешает удалённый выход-телепорт.
            if vehicle['configuration'] in (102,109,203) and math.dist(position,vehicle['position'])>1000:
                return [],dict(action='getoff_rejected',uid=hex(uid),
                    reason='outside_diagnostic_exit_radius',experimental=True)
            # В двух первичных GETOFF_SYNC (72958/95008) первый POS13
            # содержит мировую позицию, второй нулевой. Семантика второго
            # пока не названа: дублирование позиции давало огромный скачок.
            response = struct.pack('>QIQIIiiiBiiiB', uid, 1, self.actor_uid,
                                   self.seat, 0, *position, 0, 0, 0, 0, 0)
            self.seated = None
            self.seat = None
            self.seated_at = None
            self.departure_origin = self.departure_tick = None
            return [(0x6544, response)], {'action': 'getoff', 'uid': hex(uid),
                                        'position': position, 'experimental': True,
                                        'boat_zero_exit_fallback': boat_exit_fallback}
        return [], {'action': 'ignored', 'command': hex(command)}

    def climb_protected(self, now):
        return now < self.climb_until

    def cancel_on_death(self):
        """Смерть отменяет своё pending завершение; газета не включает погибшего."""
        if self.dead:
            return None
        was_seated = self.seated is not None
        self.dead = True
        self.seated = self.seat = self.seated_at = None
        self.climb_until = 0
        return {'action': 'evacuation_cancelled_on_death', 'was_seated': was_seated}

    def poll(self, now, tick=None):
        # Только явно включённый одиночный опыт: это не матч на 4 игроков.
        if (self.dead or self.evacuation_delay is None or self.seated is None
                or self.evacuation_finished or self.seated_at is None
                or self.vehicles[self.seated]['configuration'] != 6
                or now-self.seated_at < self.evacuation_delay):
            return [], []
        responses = []
        departure=self.result_fixture.diagnostic_departure_seconds if self.result_fixture else 0
        if departure:
            elapsed=max(0,now-self.seated_at-self.evacuation_delay)
            if self.departure_origin is None:
                self.departure_origin=self.vehicles[self.seated]['position']
            motion_tick=int(now*25)&0xffffffff if tick is None else tick
            if elapsed<departure and self.departure_tick==motion_tick:
                return [],[]
            body,position=diagnostic_departure_move(self.seated,self.departure_origin,
                                                   min(elapsed,departure),motion_tick)
            self.departure_tick=motion_tick
            self.vehicles[self.seated]['position']=position
            responses.append((0x6575,body))
            if elapsed<departure:
                return responses,[dict(action='diagnostic_helicopter_departure',
                    uid=hex(self.seated),position=position,elapsed=elapsed,
                    original_trajectory=False,experimental=True)]
        self.evacuation_finished = True
        statistics = self.statistics.finish(now, rescued=True) if self.statistics else None
        if self.survivor_name is not None:
            responses.append((0x6580, survivor_event(self.seated, self.actor_uid,
                                                   self.survivor_name, self.seat)))
        if self.result_fixture is not None:
            responses.extend(self.result_fixture.messages(self.actor_uid, self.room_uid,
                                                           statistics, self.survivor_name))
        responses.append((0x6589, struct.pack('>BQ', 1, self.seated)))
        return responses, [{
            'action': 'singleplayer_evacuation_finish', 'uid': hex(self.seated),
            'seat': self.seat, 'survivor_notified': self.survivor_name is not None,
            'diagnostic_archive_statistics': bool(self.result_fixture and not self.result_fixture.session_statistics),
            'match_statistics': statistics,
            'experimental': True}]
