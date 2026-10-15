"""Согласованный темп диагностического матча; не исходный календарь ROE."""
from copy import deepcopy


def paced_match(world, scene, factor=1, diagnostic_hazard=False):
    """Растягивает стадии/предупреждения и дроп/эвакуацию вместе.

    Выбор клетки, spawn, выдача inventory, скорость транспорта и reload
    сохраняют реальное время. Урон зоны тоже не масштабируется.
    """
    if type(factor) is not int or not 1 <= factor <= 10:
        raise ValueError('CycleScale: целое1..10')
    if type(diagnostic_hazard) is not bool:
        raise ValueError('DiagnosticHazard требует bool')
    world, scene = deepcopy(world), deepcopy(scene)
    world['hazard']['enabled'] = diagnostic_hazard
    for stage in world['stages']:
        for key in ('at_seconds', 'duration', 'elapsed_seconds'):
            if key in stage:
                stage[key] *= factor
    for warning in world.get('warnings', []):
        warning['at_seconds'] *= factor
        warning['duration'] *= factor
    for rule in scene:
        delay = rule.get('after_selection_delay_seconds', 0)
        # Первые3с — выдача собственного inventory. Поздние события
        # относятся к матчу, включая удаление дропа и сообщения вертолёта.
        if rule.get('after_selection') and delay > 3:
            rule['after_selection_delay_seconds'] = delay * factor
    return world, scene
