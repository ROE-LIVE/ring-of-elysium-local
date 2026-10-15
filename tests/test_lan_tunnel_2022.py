"""Границы UDP↔TCP, обратная доставка и завершение собственных каналов."""
import asyncio
from pathlib import Path
import struct
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from lan_tunnel_2022 import (DatagramQueue, MAX_DATAGRAM, QUEUE_SIZE, ProfileMismatch,
                             TunnelServer, client, endpoint, frame, read_frame)
from remote_peer_2022 import ssh_command


class FramingTests(unittest.TestCase):
    def test_ssh_forwarding_is_lan_only_and_never_contains_password(self):
        command = ssh_command('jovyan@192.168.1.25')
        self.assertEqual(command[-1], 'jovyan@192.168.1.25')
        self.assertIn('127.0.0.1:8001:127.0.0.1:8001', command)
        self.assertIn('127.0.0.1:19001:127.0.0.1:19001', command)
        for peer in ('-o@192.168.1.25', 'a@8.8.8.8', 'a@192.0.2.1', 'a@127.0.0.1',
                     'a@0.0.0.0', 'a@host', 'a@192.168.1.25;id', 'a b@10.0.0.1'):
            with self.assertRaises(ValueError): ssh_command(peer)

    def test_lengths_and_loopback_only_addresses(self):
        self.assertEqual(frame(b'abc'), b'\0\3abc')
        self.assertEqual(len(frame(b'x' * MAX_DATAGRAM)), MAX_DATAGRAM + 2)
        for value in (b'', b'x' * (MAX_DATAGRAM + 1), 'abc'):
            with self.assertRaises(ValueError):
                frame(value)
        self.assertEqual(endpoint('127.0.0.1:19001'), ('127.0.0.1', 19001))
        for value in ('192.168.1.25:19001', '0.0.0.0:1', '127.0.0.1:65536',
                      'localhost:80', '127.0.0.1:-1', '127.0.0.1:１２'):
            with self.assertRaises(ValueError):
                endpoint(value)

    def test_queue_is_bounded_and_new_peer_requires_quiet_interval(self):
        queue = DatagramQueue(single_peer=True)
        for _ in range(QUEUE_SIZE + 1):
            queue.datagram_received(b'a', ('127.0.0.1', 1))
        self.assertEqual(queue.queue.qsize(), QUEUE_SIZE)
        self.assertEqual(queue.dropped, 1)
        queue.datagram_received(b'b', ('127.0.0.1', 2))
        self.assertEqual(queue.peer[1], 1)
        queue.peer_last_seen = time.monotonic() - 3
        queue.datagram_received(b'b', ('127.0.0.1', 2))
        self.assertEqual(queue.peer[1], 2)
        self.assertEqual(queue.queue.get_nowait(), b'b')
        self.assertTrue(queue.queue.empty())


class TunnelTests(unittest.IsolatedAsyncioTestCase):
    async def test_mismatched_profile_fails_before_native_datagrams(self):
        server = TunnelServer(('127.0.0.1', 18001), profile='Alice')
        binding = await server.start(('127.0.0.1', 0))
        ready = []
        try:
            with self.assertRaises(ProfileMismatch):
                await asyncio.wait_for(client(('127.0.0.1', 0), binding,
                                               ready.append, expected_profile='bob'), 2)
            self.assertEqual(ready, [])
        finally:
            await server.close()

    async def test_partial_tcp_chunks_and_coalesced_datagrams(self):
        reader = asyncio.StreamReader()
        reader.feed_data(b'\0')
        task = asyncio.create_task(read_frame(reader))
        await asyncio.sleep(0)
        self.assertFalse(task.done())
        reader.feed_data(b'\3abc\0\2de')
        self.assertEqual(await task, b'abc')
        self.assertEqual(await read_frame(reader), b'de')
        reader.feed_eof()
        with self.assertRaises(asyncio.IncompleteReadError):
            await read_frame(reader)

    async def test_invalid_and_truncated_lengths_fail_closed(self):
        for data in (b'\0\0', struct.pack('>H', MAX_DATAGRAM + 1)):
            reader = asyncio.StreamReader(); reader.feed_data(data)
            with self.assertRaises(ValueError):
                await read_frame(reader)
        reader = asyncio.StreamReader(); reader.feed_data(b'\0\3ab'); reader.feed_eof()
        with self.assertRaises(asyncio.IncompleteReadError):
            await read_frame(reader)

    async def test_udp_roundtrip_preserves_boundaries_and_restart(self):
        class Echo(asyncio.DatagramProtocol):
            def connection_made(self, transport): self.transport = transport
            def datagram_received(self, data, address): self.transport.sendto(data, address)
        loop = asyncio.get_running_loop()
        echo, _ = await loop.create_datagram_endpoint(Echo, local_addr=('127.0.0.1', 0))
        server = TunnelServer(echo.get_extra_info('sockname'))
        binding = await server.start(('127.0.0.1', 0))
        ready = loop.create_future()
        task = asyncio.create_task(client(('127.0.0.1', 0), binding, ready.set_result))
        source = None
        try:
            udp_binding = await asyncio.wait_for(ready, 2)
            source, received = await loop.create_datagram_endpoint(DatagramQueue,
                local_addr=('127.0.0.1', 0), remote_addr=udp_binding)
            for value in (b'first', b'a' * 1400, b'last'):
                source.sendto(value)
                self.assertEqual(await asyncio.wait_for(received.queue.get(), 2), value)
            # Чистое закрытие server TCP сеанса; client соединяется вновь.
            active = list(server.tasks)
            self.assertEqual(len(active), 1)
            for pending in active: pending.cancel()
            await asyncio.gather(*active, return_exceptions=True)
            await asyncio.sleep(.65)
            source.sendto(b'new-connection')
            self.assertEqual(await asyncio.wait_for(received.queue.get(), 2), b'new-connection')
        finally:
            task.cancel(); await asyncio.gather(task, return_exceptions=True)
            if source: source.close()
            await server.close(); echo.close()
        self.assertFalse(server.tasks)
