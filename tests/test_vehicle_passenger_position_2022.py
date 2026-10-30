"""Passageiro do carro compartilhado: a posição do mundo segue o MOVE do motorista (cinzas presas no banco 2)."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'server/directory'))
from game_endpoint_probe_2022 import Endpoint

UID, DRIVER, PASSENGER, ROOM = 0x5040000160039, 0x242C, 0x885C, 7


class FakeWorld:
    def __init__(self):
        self.positions = []

    def update_position(self, position, now):
        self.positions.append(position)


class PassengerPosition(unittest.TestCase):
    def test_passenger_follows_driver(self):
        e = Endpoint.__new__(Endpoint)
        e.capture = SimpleNamespace(record=lambda kind, **kw: None)
        driver = dict(actor_uid=DRIVER, room_uid=ROOM, vehicles=SimpleNamespace(seated=UID), world=FakeWorld())
        passenger = dict(actor_uid=PASSENGER, room_uid=ROOM, world=FakeWorld())
        e.shared_vehicles = SimpleNamespace(rooms={ROOM: dict(seats={UID: {1: DRIVER, 2: PASSENGER}})})
        e.peer_avatars = SimpleNamespace(members={(ROOM, DRIVER): dict(state=driver),
                                                  (ROOM, PASSENGER): dict(state=passenger)})
        e.move_vehicle_passengers(driver, (1, 2, 3))
        self.assertEqual(passenger['world'].positions, [(1, 2, 3)])
        self.assertEqual(driver['world'].positions, [])          # o motorista já é atualizado pelo próprio MOVE


if __name__ == '__main__':
    unittest.main()
