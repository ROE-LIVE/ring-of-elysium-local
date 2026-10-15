"""Начальный пресет окружения2022: проверенные4816 и10d0.

Случайный выбор исходного сервера и температурный цикл не восстановлены.
Hour8 — исходный допустимый индекс; период зависит от часов/таблицы суток.
ATR_TEMPERATURE=5, единица0.01°C. Второе слово4816 — UNIX-секунды, не ticks.
"""
from dataclasses import dataclass
import json
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

    def messages(self,server_seconds):
        if type(server_seconds) is not int or not 0<=server_seconds<=0xffffffff:
            raise ValueError('Нужны текущие серверные UNIX-секунды BE32')
        return [(0x4816,struct.pack('>II',self.hour,server_seconds)),
                (0x10d0,struct.pack('>Ii',5,self.temperature))]
