"""Ограниченный опыт: один однородный Rock305, M4/AK; не server HP-формула.

Native012/017:140FC4898–4966; P/D MATERIALTABLE, gun power/count/distance
BULLETCONFIGTABLE.XML. Значения действуют только для подтверждённой ветки.
Не усредняем разные материалы и не доверяем присланной клиентом толщине.
"""
import math
from collision_triangle_2022 import cross, dot, sub

# Базовая энергия подтверждена исходным A89 и выполненным client constructor.
GUN_PENETRATION = {10201: (40.0, 1.5), 10202: (47.0, 2.5)}
ROCK_MODIFIER = .45
ROCK_DAMAGE_LOST = .16


def energy_after(energy, power, thickness_cm):
    if (any(type(v) not in (int, float) or not math.isfinite(v)
            for v in (energy, power, thickness_cm))
            or energy < 0 or power <= 0 or thickness_cm < 0):
        raise ValueError('Нужны конечные энергия>=0, power>0 и толщина>=0')
    inverse = 1 / ROCK_MODIFIER
    loss = max(0, energy * ROCK_DAMAGE_LOST + inverse * 3 * max(0, 3 / power * 1.25)
                  + thickness_cm * thickness_cm * inverse / 154.83839416503906)
    return energy - loss


def evaluate_rock(mesh, origin, end, gun_definition):
    hits = mesh.boundary_hits(origin, end)
    if not hits:
        return None, {}
    details = dict(mesh_id=mesh.identifier, material_id=mesh.material_id,
                   source_faces=[face for _, face in hits], original_server_policy=False)
    if mesh.material_id != 305:
        return 'penetration_material_unsupported', details
    if gun_definition not in GUN_PENETRATION:
        return 'penetration_weapon_unsupported', details
    # Один вход/выход. Непарные/сложные пересечения не превращаем в выдуманную толщину.
    if len(hits) != 2:
        return 'penetration_boundaries_unverified', details
    direction = sub(end, origin)
    signs = [dot(cross(sub(mesh.triangles[face][1], mesh.triangles[face][0]),
                       sub(mesh.triangles[face][2], mesh.triangles[face][0])), direction)
             for _, face in hits]
    if not (signs[0] < 0 < signs[1]):
        return 'penetration_winding_unverified', details
    length = math.dist(origin, end)
    if length * hits[0][0] > 50000:
        return 'penetration_distance', details
    points = [tuple(a + fraction * (b - a) for a, b in zip(origin, end))
              for fraction, _ in hits]
    thickness = math.dist(*points)
    energy, power = GUN_PENETRATION[gun_definition]
    remaining = energy_after(energy, power, thickness)
    details.update(energy_initial=energy, energy_after=remaining,
                   penetration_power=power, thickness_cm=thickness,
                   entry=points[0], exit=points[1])
    return ('penetration_energy' if remaining < 1 else None), details
