"""Учебное состояние обратимых дверей2022; не восстановленная физика сервера."""
from dataclasses import dataclass
import json
import math
from pathlib import Path
import struct


def encode_status(entity_id, status):
    # Минимальная ветка native6F55: пустые destruct parts/name, U64хвост0.
    return struct.pack('>IBBBBQ', entity_id, status, 0, 0, 0, 0)


@dataclass(frozen=True)
class DoorFixture:
    doors: dict
    interaction_radius_cm: int = 400
    visibility_radius_cm: int = 6000

    @classmethod
    def load(cls, path):
        path = Path(path)
        if path.stat().st_size > 4 * 1024 * 1024:
            raise ValueError('Каталог дверей превышает4МиБ')
        data = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(data, dict) or set(data) - {'map', 'doors', 'interaction_radius_cm', 'visibility_radius_cm', 'provenance'}:
            raise ValueError('Неизвестные поля каталога дверей')
        if data.get('map') != 16010:
            raise ValueError('Двери проверены только для зимней карты16010')
        rows = data.get('doors')
        if not isinstance(rows, list) or not 1 <= len(rows) <= 16384:
            raise ValueError('Нужно1..16384 дверей')
        radius = data.get('interaction_radius_cm', 400)
        visibility = data.get('visibility_radius_cm', 6000)
        if type(radius) is not int or not 100 <= radius <= 600 or type(visibility) is not int or not radius <= visibility <= 10000:
            raise ValueError('Радиус взаимодействия100..600; видимости до10000см')
        doors = {}
        for row in rows:
            if not isinstance(row, dict) or set(row) - {'id', 'position_cm', 'initial_state', 'source_line', 'name'}:
                raise ValueError('Неверная запись двери')
            identifier, position, status = row.get('id'), row.get('position_cm'), row.get('initial_state', 0)
            if type(identifier) is not int or not 0 < identifier < 2**32 or identifier in doors:
                raise ValueError('Повторный или неверный ID двери')
            if not isinstance(position, list) or len(position) != 3 or any(type(v) not in (int, float) or not math.isfinite(v) for v in position):
                raise ValueError('Нужны конечные XYZ двери')
            if type(status) is not int or status not in (0, 1, 2):
                raise ValueError('Статус двери0/1/2')
            doors[identifier] = (tuple(position), status)
        return cls(doors, radius, visibility)


class DoorState:
    def __init__(self, fixture):
        self.fixture = fixture
        self.status = {identifier: value[1] for identifier, value in fixture.doors.items()}
        self.visible = {}

    @staticmethod
    def valid_position(position):
        return isinstance(position, (tuple, list)) and len(position) == 3 and all(type(v) in (int, float) and math.isfinite(v) for v in position)

    def handle(self, payload, position):
        if len(payload) != 8:
            return [], dict(action='door_rejected', reason='length')
        identifier, requested = struct.unpack('>II', payload)
        event = dict(entity_id=identifier, requested_state=requested, original_server_physics=False)
        if identifier not in self.fixture.doors:
            return [], dict(action='door_rejected', reason='unknown_entity', **event)
        if requested not in (0, 1, 2):
            return [], dict(action='door_rejected', reason='state', **event)
        if not self.valid_position(position):
            return [], dict(action='door_rejected', reason='position', **event)
        distance = math.dist(position, self.fixture.doors[identifier][0])
        if distance > self.fixture.interaction_radius_cm:
            return [], dict(action='door_rejected', reason='distance', distance_cm=distance, **event)
        previous = self.status[identifier]
        self.status[identifier] = requested
        self.visible[identifier] = requested
        return [(0x6f55, encode_status(identifier, requested))], dict(action='door_status', previous_state=previous,
                    state=requested, changed=previous != requested, distance_cm=distance, **event)

    def snapshot(self, position):
        if not self.valid_position(position):
            return []
        nearby = {identifier for identifier, (xyz, _) in self.fixture.doors.items()
                  if math.dist(position, xyz) <= self.fixture.visibility_radius_cm}
        self.visible = {identifier: status for identifier, status in self.visible.items() if identifier in nearby}
        messages = []
        for identifier in sorted(nearby):
            status = self.status[identifier]
            if self.visible.get(identifier) != status:
                messages.append((0x6f55, encode_status(identifier, status)))
                self.visible[identifier] = status
                if len(messages) >= 16:
                    break
        return messages

    def resume(self):
        # Новый native world может сбросить дверные модели; возвратить nearby snapshot.
        self.visible.clear()
