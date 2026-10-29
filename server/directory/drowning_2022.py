"""Кислород под водой и удушье: скорости из таблицы баффов клиента, остальное — собственное.

Таблица баффов (TableBin000000ac, та же в0000015d/000007a1/000009a9/00000a3a):
  buff3 «水下扣除氧气» (под водой снимать кислород): dwIntervalTime1000, PowerSet Oxygen −3;
  buff4 «窒息扣血» (удушье снимает HP): dwIntervalTime1000, PowerSet Life −40, причина7
  («死亡原因：溺水», E_POWER_UPDATE_REASON_DROWN7 в комментарии строковой таблицы0000028b).
EuStatusTable (00000c07): E_EU_ST_SWIM_BREATH m_nDescBuff3, группа BREATH; E_EU_ST_ASPHYXIA
m_nDescBuff4, группа ASPHYXIA; обе — в mServerStatusDebugContext (BREATH_22, ASPHYXIA_18),
то есть статусы ставит сервер. Значения enum: ASPHYXIA26, SWIM_BREATH67 (analises/dados).
0x1069 — UNIT_POWER_UPDATE: U64 ullTarget_rid, U8 bReason, U8 bCount, bCount×{U8 bType,
I32 iCur_points, I32 iMax_points}. Handler1412ebcf0 (таблица переходов1412ec02c, 19 типов):
тип0 — HP (+5F0/+5F8), тип14 — кислород: пишется только текущий (+58C), максимум (+590,
отладочная строка OXYGEN_MAX) этим сообщением не задаётся и источник его не найден. Для типа0
bReason сохраняется (ветка1412ebff0 → +0xAC).
Собственное (исходное не найдено): максимум кислорода100 (≈33 с под водой до удушья),
восстановление20 в секунду над водой, глубина «под водой» — ниже поверхности более чем на1 м.
Поверхность — наибольшая z с момента входа в воду (плавать выше неё нельзя). Сессия
20261029T021955: FLOAT7 на37363, SWIN6 у поверхности37345..37358; в другом водоёме
поверхность ~36670, нырок до36148.
События C2S0x2A bytes[1] — E_EU_AT_*: SWIN6, FLOAT7, LAND_WATER23 — в воде; любое другое
ненулевое — вышел (0 — без перехода).
"""
import struct

OXYGEN_MAX = 100
OXYGEN_DRAIN = 3
OXYGEN_RECOVER = 20
ASPHYXIA_DAMAGE = 40
INTERVAL = 1.0
DIVE_DEPTH = 100
WATER_EVENTS = frozenset((6, 7, 23))
POWER_HP, POWER_OXYGEN = 0, 14
REASON_DROWN = 7
ST_ASPHYXIA, ST_SWIM_BREATH = 26, 67
STATUS_ENTER, STATUS_LEAVE = 0x2b, 0x2c


def encode_power(actor_uid, reason, entries):
    """0x1069 UNIT_POWER_UPDATE; entries — (bType, текущее, максимум), не более19."""
    if not 0 < len(entries) <= 19:
        raise ValueError('UNIT_POWER_UPDATE: от1 до19 записей')
    body = struct.pack('>QBB', actor_uid, reason, len(entries))
    for kind, current, maximum in entries:
        body += struct.pack('>BII', kind, current, maximum)
    return body


class BreathTracker:
    """observe — точки0x2A; poll(now) → (кислород, урон HP, [(команда, статус)]) или None."""

    def __init__(self):
        self.oxygen = OXYGEN_MAX
        self.surface = None
        self.z = None
        self.next_tick = None
        self.breath = self.asphyxia = False

    @property
    def in_water(self):
        return self.surface is not None

    @property
    def underwater(self):
        return self.in_water and self.surface-self.z > DIVE_DEPTH

    def leave_water(self):
        self.surface = self.z = None

    def observe(self, points):
        for point in points:
            event, z = point['bytes'][1], point['position'][2]
            if event in WATER_EVENTS and not self.in_water:
                self.surface = z
            elif event and event not in WATER_EVENTS:
                self.leave_water()
            if self.in_water:
                self.surface, self.z = max(self.surface, z), z

    def poll(self, now):
        under = self.underwater
        statuses = []
        if under != self.breath:
            self.breath = under
            statuses.append((STATUS_ENTER if under else STATUS_LEAVE, ST_SWIM_BREATH))
        if not under and self.oxygen >= OXYGEN_MAX:
            self.next_tick = None
        elif self.next_tick is None:
            self.next_tick = now+INTERVAL
        before, damage = self.oxygen, 0
        if self.next_tick is not None and now >= self.next_tick:
            periods = int((now-self.next_tick)/INTERVAL)+1
            self.next_tick += periods*INTERVAL
            for _ in range(periods):
                if not under:
                    self.oxygen = min(OXYGEN_MAX, self.oxygen+OXYGEN_RECOVER)
                elif self.oxygen > 0:
                    self.oxygen = max(0, self.oxygen-OXYGEN_DRAIN)
                else:
                    damage += ASPHYXIA_DAMAGE
        choking = under and self.oxygen == 0
        if choking != self.asphyxia:
            self.asphyxia = choking
            statuses.append((STATUS_ENTER if choking else STATUS_LEAVE, ST_ASPHYXIA))
        if self.oxygen == before and not damage and not statuses:
            return None
        return self.oxygen, damage, statuses

    def reset(self):
        """Смерть/выход: статусы снимаются, кислород полный."""
        statuses = [(STATUS_LEAVE, status) for status, active in
                    ((ST_SWIM_BREATH, self.breath), (ST_ASPHYXIA, self.asphyxia)) if active]
        self.__init__()
        return statuses
