"""Воспроизведение выбранного native integrator2022, не исходный сервер.

140FC2430, update140FC2370, step140FC5830, gate140FC57E0.
Единицы: см/сек; float32 после каждой SSE-операции. Столкновения,
разброс, вода/материалы карты, источник range и original hurt не восстановлены.
Параметры передаёт вызывающий код: nZ_plus не считается гравитацией.
"""
from dataclasses import dataclass, replace
import math
import struct


def f32(value):
    return struct.unpack('<f', struct.pack('<f', value))[0]


def _add(a, b): return f32(a+b)
def _mul(a, b): return f32(a*b)
def _div(a, b): return f32(a/b)


def _length(vector):
    x, y, z = vector
    return f32(math.sqrt(_add(_add(_mul(y,y), _mul(x,x)), _mul(z,z))))


@dataclass(frozen=True)
class BallisticState:
    position: tuple
    velocity: tuple
    gravity: float
    air_drag: float
    range_cm: float
    min_speed: float = 0.0
    grace_seconds: float = 0.0
    local: bool = True
    water: bool = False
    water_drag: float = 0.05
    water_linear: float = 480.0
    time: float = 0.0
    distance: float = 0.0

    def __post_init__(self):
        for name in ('position', 'velocity'):
            value = getattr(self, name)
            if (not isinstance(value, tuple) or len(value) != 3
                    or any(type(x) not in (int,float) or not math.isfinite(x)
                           or abs(x)>10000000 for x in value)):
                raise ValueError('Нужен конечный XYZ/velocity в допустимом диапазоне')
            object.__setattr__(self,name,tuple(f32(x) for x in value))
        for name in ('gravity','air_drag','range_cm','min_speed','grace_seconds',
                     'water_drag','water_linear','time','distance'):
            value=getattr(self,name)
            if (type(value) not in (int,float) or not math.isfinite(value)
                    or abs(value)>10000000 or (name!='gravity' and value<0)):
                raise ValueError('Неверный баллистический параметр')
            object.__setattr__(self,name,f32(value))
        if self.range_cm <= 0 or type(self.local) is not bool or type(self.water) is not bool:
            raise ValueError('Нужна положительная range и логические local/water')

    @property
    def alive(self):
        x,y,z=self.velocity
        square=_add(_add(_mul(x,x),_mul(y,y)),_mul(z,z))
        return self.range_cm > self.distance and square > _mul(self.min_speed,self.min_speed)


def step(state, dt=0.02):
    """Один шаг без collision. Range проверяется до шага, как native gate.

    Возвращает новое состояние; последняя точка может пересечь range.
    Переход через поверхность воды должен определить внешний geometry provider.
    """
    if type(dt) not in (int,float) or not math.isfinite(dt) or not 0 < dt <= 0.02:
        raise ValueError('dt должен быть0..20мс')
    if not isinstance(state,BallisticState):
        raise TypeError('Нужно BallisticState')
    if not state.alive:
        return state
    dt=f32(dt)
    time=_add(state.time,dt)
    velocity=state.velocity
    if state.grace_seconds <= time:
        if state.local:
            speed=_length(velocity)
            direction=tuple(_div(v,speed) for v in velocity) if speed>0 else (0.,0.,0.)
            quadratic=state.water_drag if state.water else state.air_drag
            linear=state.water_linear if state.water else 0.
            drag=_add(_mul(_mul(_div(quadratic,100.),speed),speed),
                      _mul(_div(linear,100.),speed))
            speed=max(0.,f32(speed-_mul(drag,dt)))
            velocity=tuple(_mul(v,speed) for v in direction)
        displacement=tuple(_mul(v,dt) for v in velocity)
        if not state.water:
            correction=_mul(_mul(_mul(state.gravity,0.5),dt),dt)
            displacement=(*displacement[:2],_add(displacement[2],correction))
            velocity=(*velocity[:2],_add(velocity[2],_mul(state.gravity,dt)))
    else:
        displacement=tuple(_mul(v,dt) for v in velocity)
    position=tuple(_add(a,b) for a,b in zip(state.position,displacement))
    return replace(state,position=position,velocity=velocity,time=time,
                   distance=_add(state.distance,_length(displacement)))


def trajectory(state, max_steps=10000):
    """Ограниченный генератор для проверки полёта, без заявлений о collision."""
    if type(max_steps) is not int or not 1 <= max_steps <= 10000:
        raise ValueError('Нужно1..10000 шагов')
    yield state
    for _ in range(max_steps):
        if not state.alive:
            break
        state=step(state)
        yield state
