"""Модификация машины (тактика REFIT 70023): EU_VEHICLE_MSGID_LEVELUP_* и START_LEVELUP_BC.

Имена/поля из SWIG клиента (память процесса, сессия 20261030T012153), декодеры 0x652D-таблицы:
  0x6537 LEVELUP_REQ       ullVehicle_rid, bRepair                    (140bf35d0)
  0x6538 LEVELUP_RSP       iRet, ullVehicle_rid, bRepair             (140c01ac0)
  0x6539 LEVELUP_BC        ullVehicle_rid, bVehicle_level, bRepair   (140c9ca90; bRepair — версионное поле, последним)
  0x6593 START_LEVELUP_BC  два U64: порядок ullVehicle_rid, ullActor_rid — гипотеза (как SWITCH_SEAT_SYNC)
EuVehicleTable_car (TableBin #0x444, SHA 8a8ebefc…): mLevelCfg nLevel1, nToLevelSingingMs5000, nInitHp ниже.
Последовательность — наша реконструкция: BC_START сразу; через5с LEVELUP_BC + новый HP, выход из статуса
E_EU_ST_VEHICLE_LEVELUP75 (0x2C) и RSP iRet0 автору. RSP в начале оставлял анимацию/звук навсегда
(сессия20261030T013558).
"""
import struct

LEVEL_HP = {101: 46080, 102: 34560, 104: 38800, 105: 46080, 107: 34560, 114: 48000, 115: 39744}
SINGING_SECONDS = 5.0
REFIT_ABILITY, REFIT_COUNT = 25, 26          # ATR_INIT_ABILITY_REFIT, ATR_REFIT_LEFT_COUNT
ST_VEHICLE_LEVELUP = 75                       # E_EU_ST_VEHICLE_LEVELUP
RET_OK, RET_FAIL = 0, 1


def decode_levelup_request(payload):
    if len(payload) != 9:
        raise ValueError('LEVELUP_REQ ожидает9байт')
    return struct.unpack('>QB', payload)


def encode_levelup_response(ret, uid, repair):
    return struct.pack('>iQB', ret, uid, repair)


def encode_levelup_bc(uid, level, repair):
    return struct.pack('>QBB', uid, level, repair)


def encode_start_levelup_bc(uid, actor_uid):
    return struct.pack('>QQ', uid, actor_uid)


def encode_status_leave(actor_uid, status=ST_VEHICLE_LEVELUP):
    # 0x2C SCENE_MSGID_STATUS_LEAVE: U64 unit, U32 E_EU_ST_* (как 0x2B).
    return struct.pack('>QI', actor_uid, status)


class VehicleLevelups:
    """Модификации в процессе: uid → (актор, срок, bRepair); уровни уже модифицированных машин."""

    def __init__(self):
        self.pending, self.levels = {}, {}

    def reject_reason(self, vehicle, uid, occupied, charges, dead):
        if dead:
            return 'dead'
        if vehicle is None or vehicle.get('configuration') not in LEVEL_HP:
            return 'model_without_level'
        if not vehicle.get('hp'):
            return 'vehicle_dead'
        if self.levels.get(uid, 0) >= 1:
            return 'already_level1'
        if uid in self.pending:
            return 'already_levelling'
        if occupied:
            return 'vehicle_has_member'
        if charges <= 0:
            return 'no_refit_charge'
        return None

    def start(self, uid, actor_uid, repair, now):
        self.pending[uid] = (actor_uid, now + SINGING_SECONDS, repair)

    def cancel_actor(self, actor_uid):
        for uid in [u for u, p in self.pending.items() if p[0] == actor_uid]:
            del self.pending[uid]

    def due(self, now):
        done = [(uid, *p) for uid, p in self.pending.items() if p[1] <= now]
        for uid, *_ in done:
            del self.pending[uid]
            self.levels[uid] = 1
        return [(uid, actor, repair) for uid, actor, _due, repair in done]


# Функции уровня1 по Shift: 0x6591 FUNC_OP_REQ (iOp_type; stOp_param версионный, не приходит),
# 0x6592 FUNC_OP_RSP два I32 (140c27d10): порядок iRet, iOp_type — гипотеза, как iRet первым в LEVELUP_RSP.
# E_EU_VEHICLE_FUNC_*: THROW_OILDRUM1, START/STOP_RADAR2/3, INVISIBLE4/5, BOOST6/7, REAPER8/9.
# Бит в iCur_st 0x6554 (EU_VEHICLE_STATUS_*): BOOST64, INVISIBLE128, RADAR256; базовое состояние — маска3.
# Время из mParts уровня1 (#0x444): 102 RADAR18с/перезарядка180с, 104 STEALTH20/40, 107 STEALTH40/10.
OP_START_RADAR, OP_STOP_RADAR, OP_START_INVISIBLE, OP_STOP_INVISIBLE = 2, 3, 4, 5
STATUS_INVISIBLE, STATUS_RADAR = 128, 256
FUNCTIONS = {102: (OP_START_RADAR, OP_STOP_RADAR, STATUS_RADAR, 18.0, 180.0),
             104: (OP_START_INVISIBLE, OP_STOP_INVISIBLE, STATUS_INVISIBLE, 20.0, 40.0),
             107: (OP_START_INVISIBLE, OP_STOP_INVISIBLE, STATUS_INVISIBLE, 40.0, 10.0)}


def decode_func_op_request(payload):
    if len(payload) < 4:
        raise ValueError('FUNC_OP_REQ ожидает iOp_type')
    return struct.unpack_from('>i', payload)[0]


def encode_func_op_response(ret, op_type):
    return struct.pack('>ii', ret, op_type)


class VehicleFunctions:
    """Активные функции (бит статуса до срока) и перезарядка по машине."""

    def __init__(self):
        self.active, self.ready_at = {}, {}

    def operate(self, uid, model, op_type, now):
        """→ (бит, включить?) или причина отказа (str)."""
        spec = FUNCTIONS.get(model)
        if spec is None or op_type not in spec[:2]:
            return 'unsupported_op'
        start, _stop, bit, duration, cooldown = spec
        if op_type == start:
            if uid in self.active:
                return 'already_active'
            if now < self.ready_at.get(uid, 0):
                return 'cooldown'
            self.active[uid] = (bit, now + duration)
            self.ready_at[uid] = now + duration + cooldown
            return bit, True
        if uid not in self.active:
            return 'not_active'
        del self.active[uid]
        return bit, False

    def expired(self, now):
        done = [(uid, bit) for uid, (bit, until) in self.active.items() if until <= now]
        for uid, _bit in done:
            del self.active[uid]
        return done
