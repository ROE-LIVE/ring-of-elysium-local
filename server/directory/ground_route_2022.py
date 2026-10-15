"""Проверенный вручную граф земли2022; не исходный navmesh или collision engine.

Рёбра задаёт исследователь по genuine walk. Алгоритм не создаёт shortcuts
через невидимую геометрию: путь содержит только явно разрешённые рёбра.
"""
from dataclasses import dataclass
import heapq
import json
import math
from pathlib import Path


def crosses_xy_box(a, b, lower, upper):
    """Замкнутый XY-прямоугольник запрещён независимо от высоты: не перелезать."""
    enter, leave = 0.0, 1.0
    for i in (0, 1):
        delta = b[i]-a[i]
        if abs(delta) < 1e-9:
            if not lower[i] <= a[i] <= upper[i]:
                return False
            continue
        first,last = sorted(((lower[i]-a[i])/delta,(upper[i]-a[i])/delta))
        enter,leave = max(enter,first),min(leave,last)
        if enter > leave:
            return False
    return True


@dataclass(frozen=True)
class GroundRoute:
    nodes: tuple
    edges: tuple
    targets: tuple
    clearance_boxes: tuple
    source: str

    @classmethod
    def load(cls, path):
        path=Path(path)
        if path.stat().st_size > 65536:
            raise ValueError('Граф земли превышает64КиБ')
        config=json.loads(path.read_text())
        if (not isinstance(config,dict) or type(config.get('version')) is not int
                or config.get('version') != 1 or config.get('build') != '2022-0.2.989.0-x64'
                or config.get('map_id') != 16010 or config.get('original_navmesh') is not False):
            raise ValueError('Нужен явный диагностический граф2022/map16010/version1')
        if not isinstance(config.get('source'),str) or not config['source'].strip():
            raise ValueError('Нужен источник проверенных рёбер')
        raw=config.get('nodes')
        if not isinstance(raw,list) or not 2 <= len(raw) <= 128:
            raise ValueError('Граф требует2..128узлов')
        nodes=[];ids=set()
        for node in raw:
            if not isinstance(node,dict):
                raise ValueError('Узел должен содержать id/position')
            ident,position=node.get('id'),node.get('position')
            if (not isinstance(ident,str) or not ident or len(ident)>32 or ident in ids
                    or not isinstance(position,list) or len(position)!=3
                    or any(type(x) not in (int,float) or not math.isfinite(x)
                           or abs(x)>10000000 for x in position)):
                raise ValueError('Неверный/повторный узел земли')
            ids.add(ident);nodes.append((ident,tuple(position)))
        boxes=config.get('clearance_boxes',[])
        if not isinstance(boxes,list) or len(boxes)>64:
            raise ValueError('Нужно0..64преграды маршрута')
        for box in boxes:
            if (not isinstance(box,list) or len(box)!=2
                    or any(not isinstance(p,list) or len(p)!=3
                           or any(type(v) not in (int,float) or not math.isfinite(v)
                                  or abs(v)>10000000 for v in p) for p in box)
                    or any(a>=b for a,b in zip(*box))):
                raise ValueError('Неверная преграда маршрута')
        points=dict(nodes)
        raw_edges=config.get('edges')
        if not isinstance(raw_edges,list) or not 1 <= len(raw_edges)<=256:
            raise ValueError('Нужно1..256рёбер')
        edges=[];seen=set()
        for edge in raw_edges:
            if (not isinstance(edge,list) or len(edge)!=2
                    or any(not isinstance(x,str) or x not in ids for x in edge)
                    or edge[0]==edge[1] or tuple(sorted(edge)) in seen):
                raise ValueError('Неверное/повторное ребро')
            a,b=(points[x] for x in edge)
            horizontal=math.hypot(b[0]-a[0],b[1]-a[1])
            if not 1 <= horizontal <= 1000 or abs(b[2]-a[2]) > horizontal:
                raise ValueError('Ребро вне диагностических пределов длины/уклона')
            if any(crosses_xy_box(a,b,*box) for box in boxes):
                raise ValueError('Ребро пересекает запрещённую преграду')
            seen.add(tuple(sorted(edge)));edges.append(tuple(edge))
        targets=config.get('patrol_targets')
        if (not isinstance(targets,list) or not 2 <= len(targets)<=16
                or any(not isinstance(x,str) or x not in ids for x in targets)
                or any(a==b for a,b in zip(targets,targets[1:]+targets[:1]))):
            raise ValueError('Неверные цели патруля')
        result=cls(tuple(nodes),tuple(edges),tuple(targets),
                   tuple((tuple(a),tuple(b)) for a,b in boxes),config['source'])
        result.patrol_waypoints()
        return result

    def path(self, start, goal):
        points=dict(self.nodes)
        if start not in points or goal not in points:
            raise ValueError('Цель отсутствует в графе')
        adjacent={key:[] for key in points}
        for a,b in self.edges:
            cost=math.dist(points[a],points[b])
            adjacent[a].append((b,cost));adjacent[b].append((a,cost))
        distance={start:0.0};parent={};queue=[(0.0,start)]
        while queue:
            cost,node=heapq.heappop(queue)
            if cost != distance[node]:
                continue
            if node==goal:
                path=[node]
                while node!=start:
                    node=parent[node];path.append(node)
                return tuple(reversed(path))
            for neighbour,weight in adjacent[node]:
                candidate=cost+weight
                if candidate < distance.get(neighbour,float('inf')):
                    distance[neighbour]=candidate;parent[neighbour]=node
                    heapq.heappush(queue,(candidate,neighbour))
        raise ValueError('Цели не соединены проверенными рёбрами')

    def patrol_waypoints(self):
        points=dict(self.nodes);route=[]
        for a,b in zip(self.targets,self.targets[1:]+self.targets[:1]):
            route.extend(self.path(a,b)[:-1])
        if len(route)>512:
            raise ValueError('Патруль превышает512точек')
        return tuple(points[x] for x in route)
