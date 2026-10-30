"""Начальный пресет окружения2022: проверенные4816 и10d0.

Случайный выбор исходного сервера и температурный цикл не восстановлены.
Hour8 — исходный допустимый индекс; период зависит от часов/таблицы суток.
ATR_TEMPERATURE=5, единица0.01°C. Второе слово4816 — UNIX-секунды, не ticks.
"""
from dataclasses import dataclass
import json
import os
from pathlib import Path
import struct


@dataclass(frozen=True)
class EnvironmentFixture:
    hour: int
    temperature: int

    @classmethod
    def load(cls,path):
        path=Path(path)
        if path.stat().st_size>4096:
            raise ValueError('Начальный environment-config превышает4КиБ')
        data=json.loads(path.read_text())
        hour,temperature=data['hour'],data['temperature_raw']
        if (data.get('map_id')!=16010 or type(hour) is not int or not 0<=hour<=23
                or type(temperature) is not int or not -5000<=temperature<=500):
            raise ValueError('Нужны map16010, hour0..23 и temperature_raw−5000..500')
        return cls(hour,temperature)

    def messages(self,server_seconds,weather_type=1):
        if type(server_seconds) is not int or not 0<=server_seconds<=0xffffffff:
            raise ValueError('Нужны текущие серверные UNIX-секунды BE32')
        return [(0x4816,struct.pack('>II',self.hour,server_seconds)),
                (0x10d0,struct.pack('>Ii',5,self.temperature))] + weather_messages(weather_type)


# E_ENVR_MSGID (имена из регистрации 140bb7b59): 4813 WEATHER_NOTIFY, 4814 GET_ALL_REQ, 4815 GET_ALL_RSP,
# 4816 TIME_NOTIFY, 4817 EU_WEATHER_NOTIFY, 4818 EU_ALL_WEATHER_DETAIL. 4813/4817 — одна структура
# (pack140c4be10): три U32, U32 n<=2, n×U32. Второе поле 4817 — E_WEATHER_* (опыт вживую 20261030T024046:
# 4 в поле2 сменило иконку HUD на дождь; 1 в поле1 — нет). Поля1/3 неизвестны
# Без серверной погоды пепел KillZone (E_WEATHER_VOLCANO17) не уходил в безопасной области:
# в конфиге клиента есть mSafeRegionUseServerWeather, а иконка погоды HUD пустая.
# ROE_WEATHER_NOTIFY="a,b,c" (опыт) задаёт три поля без правки кода; "off" выключает.
# Без опыта поле2 — тип погоды из расписания (WeatherSchedule) или SUNNY1.
def weather_messages(weather_type=1):
    raw = os.environ.get('ROE_WEATHER_NOTIFY', '').strip()
    if raw.lower() == 'off':
        return []
    if raw:
        fields = [int(v, 0) for v in raw.split(',')]
        if len(fields) != 3 or any(not 0 <= v <= 0xffffffff for v in fields):
            raise ValueError('ROE_WEATHER_NOTIFY ожидает три U32')
    else:
        if type(weather_type) is not int or not 0 < weather_type < 32:
            raise ValueError('E_WEATHER_* вне 1..31')
        fields = [0, weather_type, 0]
    body = struct.pack('>IIII', *fields, 0)
    return [(0x4817, body), (0x4813, body)]


class WeatherSchedule:
    """Погода карты: климат по m_dwAppearProbability, группа по m_iProbility, затем последовательность
    погод по m_dwDuration (секунды); по концу последовательности — новая группа того же климата.

    Профиль — tools/generate_weather_profile.py (EnvrMapWeatherTable #0x8ee + EnvrClimateTable #0x133).
    Повтор группы и отсутствие перехода (m_dwMin/MaxSwitchTime) — наши упрощения.
    """

    def __init__(self, profile, rng, now):
        climates = profile.get('climates') if isinstance(profile, dict) else None
        if not climates or any(not c.get('groups') or any(not g.get('sequence') for g in c['groups'])
                               for c in climates):
            raise ValueError('Профиль погоды без климатов/групп/последовательностей')
        self.rng = rng
        self.climate = self._pick(climates)
        self._start_group(now)

    def _pick(self, rows):
        total = sum(row['probability'] for row in rows)
        point = self.rng.random() * total
        for row in rows:
            point -= row['probability']
            if point < 0:
                return row
        return rows[-1]

    def _start_group(self, at):
        self.group = self._pick(self.climate['groups'])
        self.index, self.until = 0, at + self.group['sequence'][0]['duration']

    def current(self, now):
        while now >= self.until:
            start = self.until
            self.index += 1
            if self.index >= len(self.group['sequence']):
                self._start_group(start)
            else:
                self.until = start + self.group['sequence'][self.index]['duration']
        return self.group['sequence'][self.index]['weather']


def load_weather_profile(path=None):
    """ROE_WEATHER_PROFILE (путь, задаёт jogar-mapa по карте) → профиль или None."""
    path = path or os.environ.get('ROE_WEATHER_PROFILE', '').strip()
    if not path:
        return None
    path = Path(path)
    if path.stat().st_size > 256 * 1024:
        raise ValueError('Профиль погоды больше256КиБ')
    return json.loads(path.read_text(encoding='utf-8'))
