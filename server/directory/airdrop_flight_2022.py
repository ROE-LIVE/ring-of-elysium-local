"""Полёт аирдропа на сервере (собственная модель, опыт27/10 по описанию оригинала пользователем).

Оригинал (со слов пользователя): шар висит высоко несколько минут, затем объявление, медленный
спуск до касания ящиком земли, после чего шар отцепляется и улетает вверх. Исходный серверный
алгоритм не найден; клиент сам анимирует падение native501. Здесь сервер:
  1) держит501 над точкой (hover) MOVE_BC0x6575 каждые0,5с HOVER_SECONDS;
  2) отправляет отложенный AIRDROP_START0x4A6 и ведёт спуск со скоростью DESCENT_SPEED;
  3) на земле — PART_SYNC0x6546: hp0 у шара (part1, E_EUV_PART_BALOON=3) и огня (part2, =4).
Форматы:
  MOVE_BC (декодер140c98c90, getters EU_VEHICLE_MOVE_BC_*): U64 rid, U32 iLogic_tick, U8 offset,
    stMove (POS 3i…, скорость/направление 3f@26), …; шаблон — проверенный _DEPARTURE_MOVE.
  PART_SYNC (декодер140c98690): U64 ullVehicle_rid, U64 ullTarget_rid, EU_VEHICLE_PART_INFO
    (U32 iPart_id, U32 iStatus, U32 iHp, U32 iBullet_num, U8 bPart_type; доп. блок только для5),
    U32 iResult. Порядок полей — по getters1414f1c80..1414f2ce0; E_EUV_PART_* — регистрация имён.
iStatus разрушенной части не найден: берём3 (как разрушенный транспорт) — гипотеза.
Игра27/10: без владельца клиент сам симулировал падение (слал MOVE_REQ0x6549) и игнорировал
MOVE_BC. Поэтому сразу и каждые OWNER_PERIOD секунд — OWNER_SYNC0x656D с владельцем0
(декодер140C9AAA0, формат как в shared_vehicle_2022.owner_packet): гипотеза «без владельца
клиент не ведёт физику».
"""
import struct

from vehicle_probe_2022 import _DEPARTURE_MOVE

HOVER_SECONDS = 120
HOVER_HEIGHT = 20000          # см над землёй
DESCENT_SPEED = 250           # см/с
HOVER_PERIOD = 0.5
DESCENT_PERIOD = 0.2
PART_BALOON, PART_BALOON_FIRE = 3, 4
OWNER_PERIOD = 2.0
DESTROYED_STATUS = 3


def move_bc(uid, position, velocity_z, tick):
    body = bytearray(_DEPARTURE_MOVE)
    struct.pack_into('>QI', body, 0, uid, tick & 0xffffffff)
    struct.pack_into('>3i', body, 13, *position)
    struct.pack_into('>3f', body, 26, 0.0, 0.0, float(velocity_z))
    return bytes(body)


def owner_sync(uid, position, owner=0):
    return (0x656d, struct.pack('>QIQ', uid, 0, owner) + struct.pack('>iiiB', *position, 0)
            + struct.pack('>4f', 0, 0, 0, 1) + bytes(3))


def part_sync(uid, part_id, part_type, hp=0, status=DESTROYED_STATUS):
    return struct.pack('>QQIIIIBI', uid, 0, part_id, status, hp, 0, part_type, 0)


class AirdropFlight:
    def __init__(self, uid, x, y, ground_z, now):
        self.uid, self.x, self.y, self.ground_z = uid, x, y, ground_z
        self.top_z = ground_z + HOVER_HEIGHT
        self.started = now
        self.notice = None
        self.phase = 'hover'
        self.next_send = now
        self.next_owner = now

    def hover_entity(self, body):
        """Ящик501 сразу на высоте зависания над точкой."""
        patched = bytearray(body)
        struct.pack_into('>3i', patched, 20, self.x, self.y, self.top_z)
        return bytes(patched)

    def poll(self, now, tick):
        """Пакеты для клиента (возможно пусто) и событие смены фазы (или None)."""
        if self.phase == 'done':
            return [], None
        owner = []
        if now >= self.next_owner:
            self.next_owner = now + OWNER_PERIOD
            owner = [owner_sync(self.uid, (self.x, self.y, self.current_z(now)))]
        if now < self.next_send:
            return owner, None
        packets, phase = self.step(now, tick)
        return owner + packets, phase

    def current_z(self, now):
        elapsed = now - self.started
        if elapsed < HOVER_SECONDS:
            return self.top_z
        return max(self.ground_z, round(self.top_z - DESCENT_SPEED*(elapsed - HOVER_SECONDS)))

    def step(self, now, tick):
        elapsed = now - self.started
        if self.phase == 'hover':
            if elapsed < HOVER_SECONDS:
                self.next_send = now + HOVER_PERIOD
                return [(0x6575, move_bc(self.uid, (self.x, self.y, self.top_z), 0, tick))], None
            self.phase = 'descent'
            packets = [self.notice] if self.notice else []
            self.next_send = now
            return packets, 'descent'
        z = round(self.top_z - DESCENT_SPEED*(elapsed - HOVER_SECONDS))
        if z > self.ground_z:
            self.next_send = now + DESCENT_PERIOD
            return [(0x6575, move_bc(self.uid, (self.x, self.y, z), -DESCENT_SPEED, tick))], None
        self.phase = 'done'
        return [(0x6575, move_bc(self.uid, (self.x, self.y, self.ground_z), 0, tick)),
                (0x6546, part_sync(self.uid, 1, PART_BALOON)),
                (0x6546, part_sync(self.uid, 2, PART_BALOON_FIRE))], 'landed'
