"""Ограниченные диагностические преграды; не исходный PhysX/server mesh."""
import math


def sub(a, b):
    return tuple(x-y for x, y in zip(a, b))


def dot(a, b):
    return sum(x*y for x, y in zip(a, b))


def cross(a, b):
    return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2],
            a[0]*b[1]-a[1]*b[0])


def load_triangles(value):
    """До64 невырожденных треугольников, только конечные world XYZ в см."""
    if not isinstance(value, list) or len(value) > 64:
        raise ValueError('collision_triangles: список0..64 граней')
    result = []
    for triangle in value:
        if (not isinstance(triangle, list) or len(triangle) != 3
                or any(not isinstance(point, list) or len(point) != 3
                       or any(type(x) not in (int, float) or not math.isfinite(x)
                              or abs(x) > 10000000 for x in point) for point in triangle)):
            raise ValueError('Грань: три конечных XYZ')
        normal = cross(sub(triangle[1], triangle[0]), sub(triangle[2], triangle[0]))
        if dot(normal, normal) < 1e-8:
            raise ValueError('Вырожденная грань')
        result.append(tuple(tuple(point) for point in triangle))
    return tuple(result)


def segment_triangle_entry(origin, end, triangle):
    """Двустороннее пересечение отрезка с гранью, включая ребро и конец.

    Параллельный/лежащий в плоскости луч не блокируем: для толстой стены
    нужна её замкнутая геометрия. Пробитие материалов здесь не моделируется.
    """
    a, b, c = triangle
    direction = sub(end, origin)
    edge1, edge2 = sub(b, a), sub(c, a)
    p = cross(direction, edge2)
    determinant = dot(edge1, p)
    scale = math.sqrt(dot(edge1, edge1)*dot(p, p))
    if scale == 0 or abs(determinant) <= 1e-12*scale:
        return None
    tvec = sub(origin, a)
    u = dot(tvec, p)/determinant
    q = cross(tvec, edge1)
    v = dot(direction, q)/determinant
    t = dot(edge2, q)/determinant
    epsilon = 1e-9
    if u < -epsilon or v < -epsilon or u+v > 1+epsilon or t < -epsilon or t > 1+epsilon:
        return None
    return max(0.0, min(1.0, t))
