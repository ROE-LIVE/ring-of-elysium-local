"""Урон оружия по EquipmentTableEuropa клиента2022 (config/gun-damage-2022.json).

Поля таблицы: nDamage, nDamageMin, nDropOffStart, nDropOffEnd, nRange (см), nHitHeadRatio (%).
Шкала HP та же, что у сервера (1000 = полное здоровье): M4 400 → 3 попадания, TAC-50 2000.
Собственная интерпретация, исходная серверная формула не восстановлена:
  - линейное падение nDamage → nDamageMin между nDropOffStart и nDropOffEnd;
  - дальше nRange урона нет;
  - part1 (голова, подтверждено head-feedback16.10) × nHitHeadRatio/100;
  - part3 (руки/ноги по QSPHYSXCONFIG.XML: Head→1, Pelvis/Spine/Spine1/Neck→2, конечности→3)
    × LIMB_PERCENT/100 — выбор пользователя27/10 (20%), в таблицах клиента множителя нет;
  - part2 (туловище) ×1.
"""
import json
from pathlib import Path

HEAD_PART = 1
LIMB_PART = 3
LIMB_PERCENT = 20
DEFAULT_PATH = Path(__file__).resolve().parents[2] / 'config' / 'gun-damage-2022.json'


class GunDamageTable:
    def __init__(self, guns):
        self.guns = {}
        for definition, values in guns.items():
            damage, minimum, start, end, reach, head = (int(v) for v in values)
            if not (0 <= minimum <= damage <= 5000 and 0 <= start <= end and 0 < reach and 0 < head <= 500):
                raise ValueError(f'Неверная строка урона оружия {definition}')
            self.guns[int(definition)] = (damage, minimum, start, end, reach, head)

    @classmethod
    def load(cls, path=DEFAULT_PATH):
        return cls(json.loads(Path(path).read_text(encoding='utf-8'))['guns'])

    def damage(self, gun_definition, distance_cm, part_id):
        """Урон одного попадания или None для неизвестного оружия."""
        row = self.guns.get(gun_definition)
        if row is None:
            return None
        damage, minimum, start, end, reach, head = row
        if distance_cm > reach:
            return 0
        if distance_cm > start:
            fraction = 1.0 if end == start else min(1.0, (distance_cm-start)/(end-start))
            damage = damage - (damage-minimum)*fraction
        if part_id == HEAD_PART:
            damage = damage*head/100
        elif part_id == LIMB_PART:
            damage = damage*LIMB_PERCENT/100
        return max(0, round(damage))

    def reach(self, gun_definition):
        row = self.guns.get(gun_definition)
        return None if row is None else row[4]
