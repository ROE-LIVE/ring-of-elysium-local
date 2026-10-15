"""Полный wire-разбор ENTER_ROOM_RSP по EXE 2022, проверяемый захватами 2023.

Имена неизвестных полей обозначают смещение в нативной структуре, не смысл.
Результат содержит личные идентификаторы и строки: не отправлять наружу.
"""
import struct
from contextlib import contextmanager


class Reader:
    def __init__(self, data):
        self.data = bytes(data)
        self.offset = 0
        self.fields = []
        self.sections = []
        self.prefix = ''

    def take(self, name, size, fmt=None):
        at = self.offset
        if size < 0 or at + size > len(self.data):
            raise ValueError(f'{self.prefix}{name}: недостаточно данных при {at}')
        raw = self.data[at:at + size]
        value = struct.unpack('>' + fmt, raw)[0] if fmt else raw
        self.offset += size
        self.fields.append({'name': self.prefix + name, 'offset': at,
                            'length': size, 'type': fmt or 'raw', 'value': value})
        return value

    def u32(self, name):
        return self.take(name, 4, 'I')

    def u64(self, name):
        return self.take(name, 8, 'Q')

    def u8(self, name):
        return self.take(name, 1, 'B')

    def f32(self, name):
        return self.take(name, 4, 'f')

    def count(self, name, maximum):
        n = self.take(name, 4, 'i')
        if not 0 <= n <= maximum:
            raise ValueError(f'{self.prefix}{name}: счётчик {n} вне 0..{maximum}')
        return n

    def string(self, name, maximum=128):
        n = self.u32(name + '.length')
        if not 1 <= n <= maximum:
            raise ValueError(f'{self.prefix}{name}: недопустимая длина строки {n}')
        raw = self.take(name, n)
        if raw[-1:] != b'\0' or b'\0' in raw[:-1]:
            raise ValueError(f'{self.prefix}{name}: требуется единственный конечный NUL')
        return raw[:-1]

    def words(self, name, n):
        return [self.u32(f'{name}[{i}]') for i in range(n)]

    @contextmanager
    def section(self, name, native):
        old, start = self.prefix, self.offset
        self.prefix += name + '.'
        try:
            yield
        finally:
            self.sections.append({'name': self.prefix[:-1], 'native': native,
                                  'offset': start, 'length': self.offset - start})
            self.prefix = old

    def finish(self):
        if self.offset != len(self.data):
            raise ValueError(f'Лишние данные: {len(self.data) - self.offset} байт')
        return {'length': self.offset, 'fields': self.fields, 'sections': self.sections}


def _profile_aux(r):
    with r.section('m094', '0x140bd0da0'):
        with r.section('fixed', '0x140bd0450'):
            r.words('m000', 3)
            r.u64('m00c')
            r.words('m014', 3)
            r.f32('m020')
            r.words('m024', 3)
        with r.section('extended', '0x140bd09a0'):
            r.words('m000', 5)
            r.f32('m014')
            r.f32('m018')
            r.words('m01c', 2)
            for at in range(0x24, 0x58, 4):
                r.f32(f'm{at:03x}')
            n = r.count('m058.count', 30)
            for i in range(n):
                with r.section(f'm05c[{i}]', '0x140bd02a0'):
                    r.u32('m000')
                    for at in range(4, 0x24, 4):
                        r.f32(f'm{at:03x}')
                    r.u32('m024')


def _profile(r):
    with r.section('profile', '0x140bd26c0'):
        with r.section('base', '0x140bd1ae0'):
            r.u64('m000')
            r.u32('m008')
            r.u64('m00c')
            r.string('m014')
            _profile_aux(r)
            r.words('m5d0', 7)
            r.words('m5ec', 19)
            r.u32('m638')
            r.u64('m63c')
            r.u32('m644')
            with r.section('m648', '0x140bd1040'):
                r.words('m000', 2)
                n = r.count('m008.count', 2)
                r.words('m00c', n)
            r.words('m65c', 3)
            r.f32('m668')
            r.words('m66c', 2)
            r.u64('m674')
            r.u32('m67c')
            r.u8('m680')
            r.string('m681')
            for i in range(5):
                r.u64(f'm701[{i}]')
            r.u64('m729')
            for i in range(5):
                r.u64(f'm731[{i}]')
            r.u32('m759')
            with r.section('m75d', '0x140bd1380'):
                r.u32('m000')
                n = r.count('m004.count', 2)
                for i in range(n):
                    r.string(f'm008[{i}]')
                r.string('m108')
            r.u32('m8e5')
            r.u64('m8e9')
            r.u64('m8f1')
            r.u8('m8f9')
            r.u32('m8fa')
        with r.section('m8fe', '0x140bd25d0'):
            r.words('values', 105)


def decode_enter_room_response(payload):
    """Разобрать вариант, жёстко заданный корневым decoder version=0x5c."""
    r = Reader(payload)
    r.u32('result')
    for at in (4, 12, 20, 28):
        r.u64(f'm{at:03x}')
    _profile(r)
    r.words('mac6', 2)
    r.u32('mace')
    with r.section('mad2', '0x140c25cf0'):
        r.words('m000', 11)
        for name, maximum, native in [('m02c', 10, '0x140c25930'),
                                     ('m058', 5, '0x140c257c0'),
                                     ('m070', 10, '0x140c25930'),
                                     ('m09c', 80, '0x140c25aa0'),
                                     ('m1e0', 10, '0x140c25930')]:
            with r.section(name, native):
                n = r.count('count', maximum)
                r.words('values', n)
        r.words('m20c', 2)
    with r.section('mce6', '0x140be86f0'):
        r.words('values', 5)
    r.u8('mcfa')
    with r.section('mcfb', '0x140be91a0'):
        n = r.count('count', 400)
        for i in range(n):
            with r.section(f'entries[{i}]', '0x140be8f70'):
                r.u32('m000')
                n = r.count('m004.count', 6)
                for j in range(n):
                    with r.section(f'm008[{j}]', '0x140be8d70'):
                        r.words('m000', 2)
                        r.u8('m008')
    return r.finish()


def decode_jump_routing(payload, code):
    """Статические схемы 0x360/0x368; в захватах пока не подтверждены."""
    if code not in (0x360, 0x368):
        raise ValueError('Ожидался код 0x360 или 0x368')
    r = Reader(payload)
    r.u64('m000')
    r.take('m008', 16)
    r.take('m018', 16)
    r.words('m028', 3)
    if code == 0x368:
        r.u8('m034')
        r.words('m035', 2)
    n = r.count('routes.count', 4)
    for i in range(n):
        with r.section(f'routes[{i}]', '0x140bd6850'):
            r.string('m000', 16)
            r.take('m010', 2, 'H')
            r.string('m012', 128)
            r.u32('m092')
    return r.finish()
