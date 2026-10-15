"""Расходники2022: нативный запрос/анимация и явный локальный таймер лечения.

Параметры из A81; cold53 подтверждает3e80 action3,3e81 и отмену536/20.
Порядок серверного списания — наша модель, а не восстановленный backend ROE.
"""
import math
import struct

from weapon_probe_2022 import MEDICAL_PROFILES, MEDICAL_SLOTS, medical_record
from world_probe_2022 import encode_health


class MedicalState:
    def __init__(self, weapon, world):
        self.weapon, self.world = weapon, world
        self.pending = None
        self.completed_at = None

    def cancel(self, reason):
        if self.pending is None:
            return [], []
        definition = self.pending['definition']
        self.pending = None
        self.completed_at = None
        return [(0x537, struct.pack('>II', 0, 20)), self.finish_status()], [{
            'action': 'medical_cancelled', 'definition': definition, 'reason': reason}]

    def finish_status(self):
        # cold54: статус27 ->140e88543 ->140f06f00 выводит own actor из action8.
        return 0x2b, struct.pack('>QI', self.weapon.actor_uid, 27)

    def handle(self, command, payload, now):
        """None оставляет запрос обычному обработчику оружия/инвентаря."""
        if command == 0x536 and payload == struct.pack('>I', 20):
            packets, events = self.cancel('native_F')
            if not events:
                # Повторная отмена исправляет только состояние клиента, без списания.
                packets = [self.finish_status()]
            return packets, events or [{'action': 'medical_cancel_noop'}]
        if command != 0x3e80 or not payload or payload[0] != 3:
            return None
        if len(payload) != 10 or not math.isfinite(now):
            return [], [{'action': 'medical_rejected', 'reason': 'request_length_or_time'}]
        tag, container, slot, extra_tag, extra_value, own = struct.unpack('>BBHBIB', payload)
        definition = next((d for d, s in MEDICAL_SLOTS.items() if s == slot), None)
        # 140c4af40 ->140c2fc20: tag0 имеет U32 union; значение меняется у hotkey9.
        # Это расширение не определяет ни предмет, ни количество в нашей модели.
        if container != 2 or extra_tag != 0 or own != 1 or definition is None:
            return [], [{'action': 'medical_rejected', 'reason': 'unsupported_variant'}]
        reason = None
        if not self.weapon.medical.get(definition):
            reason = 'no_item'
        elif not 0 < self.world.hp < 1000:
            reason = 'dead_or_full_hp'
        elif self.pending or self.weapon.pending_reload:
            reason = 'action_in_progress'
        if reason:
            # Отказ — ненулевой result, ID остаётся определением выбранного предмета.
            return [(0x3e81, struct.pack('>BIIB', 3, 1, definition, 1))], [
                {'action': 'medical_rejected', 'reason': reason, 'definition': definition}]
        self.pending = {'definition': definition, 'deadline': now + MEDICAL_PROFILES[definition][2]}
        self.completed_at = None
        return [(0x3e81, struct.pack('>BIIB', 3, 0, definition, 1))], [{
            'action': 'medical_started', 'definition': definition,
            'duration_seconds': MEDICAL_PROFILES[definition][2], 'hp': self.world.hp}]

    def poll(self, now):
        if self.pending is None or not math.isfinite(now) or now < self.pending['deadline']:
            return [], []
        definition = self.pending['definition']
        quantity = self.weapon.medical.get(definition, 0)
        if not quantity or not 0 < self.world.hp < 1000:
            return self.cancel('item_or_health_changed')
        self.pending = None
        self.completed_at = now
        before = self.world.hp
        self.world.hp = min(1000, before + MEDICAL_PROFILES[definition][1])
        remaining = quantity - 1
        slot = MEDICAL_SLOTS[definition]
        if remaining:
            self.weapon.medical[definition] = remaining
            delta = self.weapon.item_delta(2, slot, medical_record(definition, remaining))
        else:
            del self.weapon.medical[definition]
            delta = self.weapon.clear_slot(2, slot)
        return [delta, self.weapon.capacity_sync(),
                (0x1069, encode_health(self.weapon.actor_uid, self.world.hp)),
                self.finish_status()], [{
            'action': 'medical_finished', 'definition': definition, 'remaining': remaining,
            'hp_before': before, 'hp': self.world.hp, 'healed_raw': self.world.hp - before}]
