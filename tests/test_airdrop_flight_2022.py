"""Серверный полёт аирдропа: зависание, отложенное объявление, спуск, отцепление шара."""
import struct
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'server/directory'))
import airdrop_flight_2022 as flight_module
from airdrop_flight_2022 import AirdropFlight, part_sync, move_bc
from game_endpoint_probe_2022 import Endpoint


class AirdropFlightTests(unittest.TestCase):
    def test_formats(self):
        self.assertEqual(len(part_sync(5, 1, 3)), 37)
        self.assertEqual(struct.unpack('>QQIIIIBI', part_sync(5, 1, 3)), (5, 0, 1, 3, 0, 0, 3, 0))
        body = move_bc(5, (1, 2, 3), -250, 99)
        self.assertEqual((len(body), struct.unpack_from('>QI', body), struct.unpack_from('>3i', body, 13)),
                         (73, (5, 99), (1, 2, 3)))
        self.assertEqual(struct.unpack_from('>3f', body, 26), (0.0, 0.0, -250.0))

    def test_hover_then_notice_then_descent_then_balloon_release(self):
        flight = AirdropFlight(7, 100, 200, 250000, 0)
        flight.notice = (0x4a6, b'notice')
        packets, phase = flight.poll(0, 1)
        self.assertEqual(([c for c, _ in packets], phase), ([0x656d, 0x6575], None))   # dono fantasma, depois posição
        self.assertEqual(struct.unpack_from('>QIQ', packets[0][1]), (7, 0, flight_module.GHOST_OWNER))
        self.assertEqual(struct.unpack_from('>3i', packets[1][1], 13), (100, 200, 250000+flight_module.HOVER_HEIGHT))
        self.assertEqual(flight.poll(0.1, 1), ([], None))          # не чаще HOVER_PERIOD
        flight.next_owner = 10**9
        packets, phase = flight.poll(flight_module.HOVER_SECONDS, 1)
        self.assertEqual((packets, phase), ([(0x4a6, b'notice')], 'descent'))
        landing = flight_module.HOVER_SECONDS + flight_module.HOVER_HEIGHT/flight_module.DESCENT_SPEED
        packets, phase = flight.poll(flight_module.HOVER_SECONDS + 1, 1)
        self.assertEqual(struct.unpack_from('>i', packets[0][1], 21)[0], 250000+flight_module.HOVER_HEIGHT-250)
        packets, phase = flight.poll(landing + 1, 1)
        self.assertEqual(phase, 'landed')
        self.assertEqual([code for code, _ in packets], [0x6575])
        self.assertEqual(struct.unpack_from('>3i', packets[0][1], 13), (100, 200, 250000))
        moment = landing + 1
        for status in flight_module.RELEASE_STATUSES:
            packets, phase = flight.poll(moment, 1)
            self.assertEqual(phase, 'release_status_%d' % status)
            self.assertEqual([code for code, _ in packets], [0x653c, 0x6546])
            self.assertEqual(struct.unpack('>QBIIIIB', packets[0][1]), (7, 3, 1, status, 0, 0, 3))
            moment += flight_module.RELEASE_PERIOD
        self.assertEqual(flight.poll(moment, 1), ([], 'released'))
        self.assertEqual(flight.poll(moment + 5, 1), ([], None))

    def test_endpoint_starts_flight_only_with_ground_notice(self):
        endpoint = Endpoint.__new__(Endpoint)
        endpoint.records = []
        endpoint.capture = SimpleNamespace(record=lambda kind, **kw: endpoint.records.append((kind, kw)))
        entity = bytearray(117)
        struct.pack_into('>QI', entity, 0, 9, 501)
        struct.pack_into('>3i', entity, 20, 100, 200, 301000)
        state = {}
        notice = struct.pack('>iiiBiiiB', 100, 200, 258000, 0, 0, 0, 0, 0)
        patched = endpoint.start_airdrop_flight(state, bytes(entity), [(0x654b, bytes(entity)), (0x4a6, notice)])
        self.assertEqual(struct.unpack_from('>3i', patched, 20), (100, 200, 258000+flight_module.HOVER_HEIGHT))
        self.assertEqual(state['airdrop_flights'][0].ground_z, 258000)
        # Без высоты земли (уведомление в небе) — прежнее нативное падение.
        sky = struct.pack('>iiiBiiiB', 100, 200, 301000, 0, 0, 0, 0, 0)
        other = {}
        self.assertEqual(endpoint.start_airdrop_flight(other, bytes(entity), [(0x4a6, sky)]), bytes(entity))
        self.assertNotIn('airdrop_flights', other)

    def test_live_airdrop_builds_new_entity_and_flight(self):
        endpoint = Endpoint.__new__(Endpoint)
        entity = bytearray(117)
        struct.pack_into('>QI', entity, 0, 9, 501)
        endpoint.scene_rules = [(0x1f49, [(0x654b, bytes(entity))])]
        state = {}
        packets, event = endpoint.live_airdrop(state, [100, 200, 258000])
        self.assertTrue(event['accepted'])
        code, body = packets[0]
        uid = struct.unpack_from('>Q', body)[0]
        self.assertEqual((code, struct.unpack_from('>I', body, 8)[0]), (0x654b, 501))
        self.assertEqual(endpoint.live_airdrop({}, [100, 200, 258000])[0][0][1][:8], body[:8])   # mesmo nome → mesmo UID
        self.assertNotEqual(uid, 9)
        self.assertEqual(struct.unpack_from('>3i', body, 20), (100, 200, 258000+flight_module.HOVER_HEIGHT))
        self.assertEqual(state['airdrop_flights'][0].notice[0], 0x4a6)


if __name__ == '__main__':
    unittest.main()
