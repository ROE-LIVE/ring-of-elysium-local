"""Точный зимний region lookup2022 по AREAINDEX.BIN.

Native1411BFAA0: originTiles*6400, cell50, Y выбирает строку;
X ищет первый включительный run end. REGIONMASKTEXTURE — отдельный UI ресурс.
"""
from dataclasses import dataclass
import hashlib
import math
from pathlib import Path
import struct

ICELAND_INDEX_SIZE = 374732
ICELAND_INDEX_SHA256 = '9dfca77d76f801485ffb31f7c3154bdc094e0d60807d1626f350e7634a853535'


def _float32(value):
    return struct.unpack('<f', struct.pack('<f', value))[0]


@dataclass(frozen=True)
class FastRegionIndex:
    rows: tuple
    origin_x: int = 204800
    origin_y: int = 204800
    cell: int = 50
    width: int = 8192

    @classmethod
    def from_bytes(cls, data, row_count=8192):
        if type(row_count) is not int or not 1 <= row_count <= 8192:
            raise ValueError('Неверное число строк индексов')
        data = bytes(data)
        if len(data) > 16 * 1024 * 1024:
            raise ValueError('Слишком большой ресурс индексов')
        rows, offset = [], 0
        for _ in range(row_count):
            if offset+2 > len(data):
                raise ValueError('Укороченный count строки')
            count = struct.unpack_from('<H', data, offset)[0]
            offset += 2
            if not 1 <= count <= 8192 or offset+4*count > len(data):
                raise ValueError('Неверная длина строки индексов')
            row = data[offset:offset+4*count]
            last = -1
            for region, end in struct.iter_unpack('<HH', row):
                if region > 64 or not last < end < 8192:
                    raise ValueError('Неверный регион/порядок run ends')
                last = end
            rows.append(row)
            offset += 4*count
        if offset != len(data):
            raise ValueError('Лишние bytes после индексов')
        return cls(tuple(rows))

    @classmethod
    def load(cls, path):
        path = Path(path)
        if path.stat().st_size != ICELAND_INDEX_SIZE:
            raise ValueError('Нужен winter AREAINDEX.BIN374732байт')
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != ICELAND_INDEX_SHA256:
            raise ValueError('Не совпал SHA winter AREAINDEX.BIN')
        return cls.from_bytes(data)

    def region_id(self, position):
        """Индекс0 сохраняется; None означает отказ lookup вне сетки.

        Native area state трактует индекс0 как Frozen; callers regions()
        прежней диагностики по-прежнему получают только регионы1..64.
        """
        if len(position) != 3 or any(type(n) not in (int, float) or not math.isfinite(n)
                                    or abs(n) > 2147483647 for n in position):
            raise ValueError('Неверная мировая позиция')
        # Wire позиция целочисленная; native также получает int32.
        x, y = int(position[0]), int(position[1])
        col = int(_float32(_float32(_float32(x)-_float32(self.origin_x))/self.cell))
        row_index = int(_float32(_float32(_float32(y)-_float32(self.origin_y))/self.cell))
        # Native отклоняет row0. За пределами мира fail-closed, без uint16 wrap.
        if not 0 < row_index < len(self.rows) or not 0 <= col < self.width:
            return None
        row = self.rows[row_index]
        low, high = 0, len(row)//4
        while low < high:
            mid = (low+high)//2
            end = struct.unpack_from('<H', row, mid*4+2)[0]
            if col <= end:
                high = mid
            else:
                low = mid+1
        if low == len(row)//4:
            return None
        region = struct.unpack_from('<H', row, low*4)[0]
        return region

    def regions(self, position):
        region = self.region_id(position)
        return frozenset((region,)) if region else frozenset()
