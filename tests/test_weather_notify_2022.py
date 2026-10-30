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


class Schedule(unittest.TestCase):
    """Sorteio clima → grupo → sequência (perfil de tools/generate_weather_profile.py) e troca pela duração."""

    PROFILE = {'map_id': 1, 'climates': [
        {'climate': 'SUNNY', 'probability': 1, 'groups': [
            {'probability': 1, 'sequence': [{'weather': 1, 'name': 'SUNNY', 'duration': 900},
                                            {'weather': 8, 'name': 'WINDY', 'duration': 300}]}]}]}

    def test_sequence_and_repeat(self):
        import random
        from environment_probe_2022 import WeatherSchedule
        s = WeatherSchedule(self.PROFILE, random.Random(1), 100)
        self.assertEqual([s.current(t) for t in (100, 999, 1000, 1299, 1300, 2200)], [1, 1, 8, 8, 1, 8])

    def test_weighted_climate(self):
        import random
        from environment_probe_2022 import WeatherSchedule
        profile = {'climates': [dict(self.PROFILE['climates'][0], probability=0),
                                {'climate': 'FOG', 'probability': 5,
                                 'groups': [{'probability': 1, 'sequence': [{'weather': 12, 'name': 'FOG',
                                                                             'duration': 290}]}]}]}
        self.assertEqual(WeatherSchedule(profile, random.Random(7), 0).climate['climate'], 'FOG')
        with self.assertRaises(ValueError):
            WeatherSchedule({'climates': []}, random.Random(), 0)

    def test_message_carries_type_in_second_field(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop('ROE_WEATHER_NOTIFY', None)
            self.assertEqual(weather_messages(12)[0], (0x4817, struct.pack('>IIII', 0, 12, 0, 0)))
            with self.assertRaises(ValueError):
                weather_messages(0)
