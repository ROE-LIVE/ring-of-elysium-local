"""Выбранный RepX из SFC: только чтение проверенного блока, локальный BVH.

Это явный исследовательский набор объектов. Загрузка одного mesh не означает
восстановления всей коллизии карты, исходного пробития или lag compensation.
"""
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import re
import struct
import sys
import xml.etree.ElementTree as ET

# Используем уже проверенный bounded decoder peer; новой зависимости нет.
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tools'))
from roe_tgcp_2023 import decompress_lz4_block

from collision_triangle_2022 import cross, dot, sub, segment_triangle_entry


def bounds_entry(origin, end, lower, upper):
    enter, leave = 0.0, 1.0
    for start, finish, minimum, maximum in zip(origin, end, lower, upper):
        delta = finish-start
        if abs(delta) < 1e-12:
            if not minimum <= start <= maximum:
                return None
            continue
        a, b = sorted(((minimum-start)/delta, (maximum-start)/delta))
        enter, leave = max(enter, a), min(leave, b)
        if enter > leave:
            return None
    return enter


def vector(value, size, limit):
    if (not isinstance(value, list) or len(value) != size
            or any(type(x) not in (int,float) or not math.isfinite(x) or abs(x) > limit for x in value)):
        raise ValueError('Нужен конечный вектор допустимого размера')
    return tuple(value)


def transform(point, pose, scale):
    point = tuple(x*y for x,y in zip(point,scale))
    t = tuple(2*x for x in cross(pose[:3],point))
    extra = cross(pose[:3],t)
    return tuple(point[i]+pose[3]*t[i]+extra[i]+pose[i+4] for i in range(3))


@dataclass(frozen=True)
class Node:
    lower: tuple
    upper: tuple
    children: tuple
    faces: tuple


@dataclass(frozen=True)
class CollisionMesh:
    identifier: str
    triangles: tuple
    material_id: int
    root: Node
    source_sha256: str
    vertex_count: int

    @classmethod
    def load(cls, descriptor, directory):
        if (not isinstance(descriptor,dict)
                or not {'id','sha256','payload_offset','material_id','pose','archive_file'} <= descriptor.keys()
                or not isinstance(descriptor['archive_file'],str) or not descriptor['archive_file']):
            raise ValueError('Неполный collision descriptor')
        identifier = descriptor['id']
        expected = descriptor['sha256']
        offset = descriptor['payload_offset']
        material = descriptor['material_id']
        if (not isinstance(identifier,str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}',identifier)
                or not isinstance(expected,str) or not re.fullmatch('[0-9a-f]{64}',expected)
                or type(offset) is not int or offset < 4
                or type(material) is not int or not 0 <= material <= 65535):
            raise ValueError('Неверный id/SHA/offset/material выбранного collision mesh')
        pose = vector(descriptor['pose'],7,10000000)
        if abs(dot(pose[:4],pose[:4])-1) > 1e-4:
            raise ValueError('Quaternion collision pose должен быть нормирован')
        scale = vector(descriptor.get('scale',[1,1,1]),3,1000)
        if any(x <= 0 for x in scale):
            raise ValueError('Нужен положительный scale collision mesh')
        path = Path(directory)/descriptor['archive_file']
        # Формат SFC-блока: packed_size, LZ4, raw_size. Offset — начало LZ4.
        with path.open('rb') as source:
            source.seek(0,2)
            if offset+4 > source.tell():
                raise ValueError('Collision offset вне SFC')
            source.seek(offset-4)
            packed_size = struct.unpack('<I',source.read(4))[0]
            if not 1 <= packed_size <= 2*1024*1024:
                raise ValueError('Collision packed block превышает2МиБ')
            packed, tail = source.read(packed_size), source.read(4)
        if len(packed) != packed_size or len(tail) != 4:
            raise ValueError('Оборванный collision SFC block')
        raw_size = struct.unpack('<I',tail)[0]
        if not 1 <= raw_size <= 4*1024*1024:
            raise ValueError('Collision raw block превышает4МиБ')
        try:
            raw = decompress_lz4_block(packed,maximum=raw_size)
        except ValueError as error:
            raise ValueError('Неверный LZ4 collision block') from error
        if len(raw) != raw_size or hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError('SHA collision ресурса не совпала')
        if b'<!DOCTYPE' in raw or b'<!ENTITY' in raw:
            raise ValueError('DTD/ENTITY не поддерживаются в collision ресурсе')
        try:
            document = ET.fromstring(raw)
            meshes = document.findall('./PxTriangleMesh')
            if document.tag != 'PhysX30Collection' or len(meshes) != 1:
                raise ValueError('Нужен один явно выбранный PxTriangleMesh')
            points = [float(x) for x in meshes[0].find('Points').text.split()]
            indices = [int(x) for x in meshes[0].find('Triangles').text.split()]
        except (ET.ParseError,AttributeError,TypeError) as error:
            raise ValueError('Неверный RepX collision ресурс') from error
        if (len(points)%3 or not 3 <= len(points)//3 <= 16384
                or len(indices)%3 or not 1 <= len(indices)//3 <= 8192
                or any(not math.isfinite(x) or abs(x) > 10000000 for x in points)
                or any(x < 0 or x >= len(points)//3 for x in indices)):
            raise ValueError('Неверные размеры/координаты/индексы collision mesh')
        vertices = tuple(transform(points[i:i+3],pose,scale) for i in range(0,len(points),3))
        if any(not math.isfinite(x) or abs(x) > 10000000 for p in vertices for x in p):
            raise ValueError('World collision vertex вне пределов')
        triangles = tuple(tuple(vertices[x] for x in indices[i:i+3]) for i in range(0,len(indices),3))

        def build(faces):
            lower = tuple(min(p[a] for i in faces for p in triangles[i]) for a in range(3))
            upper = tuple(max(p[a] for i in faces for p in triangles[i]) for a in range(3))
            if len(faces) <= 8:
                return Node(lower,upper,(),tuple(faces))
            axis = max(range(3),key=lambda a:upper[a]-lower[a])
            ordered = sorted(faces,key=lambda i:sum(p[axis] for p in triangles[i]))
            middle = len(ordered)//2
            return Node(lower,upper,(build(ordered[:middle]),build(ordered[middle:])),())

        return cls(identifier,triangles,material,build(list(range(len(triangles)))),expected,len(vertices))

    def first_hit(self, origin, end):
        if (len(origin) != 3 or len(end) != 3
                or not all(type(x) in (int,float) and math.isfinite(x) and abs(x) <= 10000000 for x in (*origin,*end))):
            raise ValueError('Неверный collision ray')
        best = None
        stack = [self.root]
        while stack:
            node = stack.pop()
            entry = bounds_entry(origin,end,node.lower,node.upper)
            if entry is None or best is not None and entry > best[0]+1e-9:
                continue
            for face in node.faces:
                hit = segment_triangle_entry(origin,end,self.triangles[face])
                if hit is not None and (best is None or hit < best[0]):
                    best = hit,face
            stack.extend(node.children)
        return best

    def boundary_hits(self, origin, end):
        """Пересечения выбранного mesh; совпавшие рёбра дают одну границу.

        Только опора для ограниченного material-опыта: не классифицирует
        открытые поверхности/вложенные объёмы как полноценный solid solver.
        """
        # Общая проверка конечности/пределов совпадает с solid LOS.
        self.first_hit(origin, end)
        hits, stack = [], [self.root]
        while stack:
            node = stack.pop()
            if bounds_entry(origin, end, node.lower, node.upper) is None:
                continue
            for face in node.faces:
                fraction = segment_triangle_entry(origin, end, self.triangles[face])
                if fraction is not None:
                    hits.append((fraction, face))
            stack.extend(node.children)
        distance = math.dist(origin, end)
        unique = []
        for hit in sorted(hits):
            if unique and (hit[0] - unique[-1][0]) * distance < .001:
                continue
            unique.append(hit)
            if len(unique) > 32:
                raise ValueError('Больше32 границ выбранного mesh')
        return tuple(unique)


def load_collision_meshes(path):
    path = Path(path)
    if path.stat().st_size > 65536:
        raise ValueError('Collision manifest превышает64КиБ')
    config = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(config,dict):
        raise ValueError('Collision manifest должен быть объектом')
    descriptors = config.get('meshes')
    if not isinstance(descriptors,list) or not 1 <= len(descriptors) <= 8:
        raise ValueError('Нужно1..8 явно выбранных collision meshes')
    meshes = tuple(CollisionMesh.load(item,path.parent) for item in descriptors)
    if len({m.identifier for m in meshes}) != len(meshes) or sum(len(m.triangles) for m in meshes) > 16384:
        raise ValueError('Повторный id или больше16384граней collision manifest')
    return meshes
