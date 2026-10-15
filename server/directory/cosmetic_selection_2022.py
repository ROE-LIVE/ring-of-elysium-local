"""Выбранные скины локальной учётки для создания игрового инвентаря2022."""
import json
from pathlib import Path


def load_weapon_skins(catalog_path):
    """Читаются только публичный каталог и локальный выбор; AUTH не нужен."""
    path = Path(catalog_path)
    if path.stat().st_size > 262144:
        raise ValueError('Слишком большой каталог внешности')
    catalog = json.loads(path.read_text())
    owned = catalog.get('owned_gun_skin_ids', [])
    mapping = catalog.get('weapon_skin_to_weapon')
    if (not isinstance(owned, list) or len(owned) > 600
            or any(type(x) is not int or not 0 < x <= 0xffffffff for x in owned)
            or len(set(owned)) != len(owned) or not isinstance(mapping, dict)
            or set(mapping) != {str(x) for x in owned}
            or any(type(x) is not int or not 0 < x <= 0xffffffff for x in mapping.values())):
        raise ValueError('Для игровых скинов нужна полная привязка skin→weapon из2CF')
    if not catalog.get('state_file'):
        return {}
    state = Path(catalog['state_file'])
    if not state.is_absolute():
        state = path.parent / state
    if not state.exists():
        return {}
    if state.stat().st_size > 65536:
        raise ValueError('Слишком большой локальный выбор внешности')
    selected = json.loads(state.read_text()).get('gun_skins', {})
    if not isinstance(selected, dict) or len(selected) > 300:
        raise ValueError('Неверный локальный выбор скинов')
    result = {}
    for weapon, skin in selected.items():
        if (not isinstance(weapon, str) or not weapon.isascii() or not weapon.isdecimal()
                or str(int(weapon)) != weapon or not 0 < int(weapon) <= 0xffffffff
                or type(skin) is not int
                or (mapping.get(str(skin)) != int(weapon) if skin else int(weapon) not in mapping.values())):
            raise ValueError('Выбранный skin не соответствует weapon в2CF')
        result[int(weapon)] = skin
    return result


def load_clothing_records(catalog_path):
    """Новый матч читает сохранённые cosmetic equipment, не весь склад одежды."""
    path = Path(catalog_path)
    if path.stat().st_size > 262144:
        raise ValueError('Слишком большой каталог внешности')
    catalog = json.loads(path.read_text())
    if not catalog.get('clothing_equipment_slots'):
        return {}
    from local_cosmetics_2022 import LocalCosmetics
    from local_clothing_2022 import item_data
    cosmetics = LocalCosmetics(path)
    return {slot:item_data(definition)
            for slot,definition in cosmetics.wardrobe.equipped.items()}
