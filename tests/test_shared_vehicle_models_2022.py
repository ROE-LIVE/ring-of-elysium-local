"""Sala compartilhada aceita os modelos originais de carro (CAR_MODELS) com os lugares da tabela."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'server/directory'))
from shared_vehicle_2022 import SharedVehicleRooms
from vehicle_probe_2022 import CAR_MODELS


class SharedVehicleModelTests(unittest.TestCase):
    def test_all_car_models_and_boat(self):
        caps = SharedVehicleRooms.capacities
        for model, (_hp, seats) in CAR_MODELS.items():
            self.assertEqual(caps[model], seats, model)
        self.assertEqual(caps[203], 1)
        self.assertEqual((caps[102], caps[109]), (2, 2))         # os já verificados não mudam


if __name__ == '__main__':
    unittest.main()
