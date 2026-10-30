"""Experiência de clima: EU_WEATHER_NOTIFY 0x4817 e WEATHER_NOTIFY 0x4813 na abertura do mundo (SUNNY 1 no 2º campo, confirmado ao vivo)."""
import os
import struct
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'server/directory'))
from environment_probe_2022 import weather_messages


class WeatherNotify(unittest.TestCase):
    def test_default_sunny(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop('ROE_WEATHER_NOTIFY', None)
            self.assertEqual(weather_messages(), [(0x4817, struct.pack('>IIII', 0, 1, 0, 0)),
                                                  (0x4813, struct.pack('>IIII', 0, 1, 0, 0))])

    def test_override_and_off(self):
        with patch.dict(os.environ, {'ROE_WEATHER_NOTIFY': '0,1,0'}):
            self.assertEqual(weather_messages()[0][1], struct.pack('>IIII', 0, 1, 0, 0))
        with patch.dict(os.environ, {'ROE_WEATHER_NOTIFY': 'off'}):
            self.assertEqual(weather_messages(), [])
        with patch.dict(os.environ, {'ROE_WEATHER_NOTIFY': '1,2'}):
            with self.assertRaises(ValueError):
                weather_messages()


if __name__ == '__main__':
    unittest.main()
