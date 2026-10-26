"""Комната: порт хоста всегда первый UID пула, гостевой порт — стабильный гостевой UID."""
import argparse
import asyncio
import contextlib
import io
import json
from pathlib import Path
import socket
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import heartbeat_probe_2022 as probe
from test_roe_protocol_2022 import KEY

POOL = [0x515bb1e1dd242c, 0x515bb18e59c77c, 0x515bb112f7885c]


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


class GuestPortTests(unittest.IsolatedAsyncioTestCase):
    async def test_reconnects_keep_their_accounts(self):
        async def backend(reader, writer):
            await reader.read()
            writer.close()
        server = await asyncio.start_server(backend, '127.0.0.1', 0)
        guest_port = free_port()
        stop = asyncio.Event()
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            keyfile = directory / 'key'; keyfile.write_bytes(KEY)
            args = argparse.Namespace(session_key_file=keyfile, reply=False, port=0, duration=10, output=directory,
                                      upstream_port=server.sockets[0].getsockname()[1],
                                      actor_uid_pool=POOL, guest_port=guest_port)
            ready = asyncio.get_running_loop().create_future()
            with contextlib.redirect_stdout(io.StringIO()):
                task = asyncio.create_task(probe.serve(args, ready, stop))
                (host, port), capture = await asyncio.wait_for(ready, 2)
                for target in (port, port, guest_port, guest_port):
                    _, writer = await asyncio.open_connection('127.0.0.1', target)
                    await asyncio.sleep(0.05)
                    writer.close(); await writer.wait_closed()
                    await asyncio.sleep(0.05)
                stop.set(); await task
            events = [json.loads(l) for l in (capture / 'events.jsonl').read_text().splitlines()]
            assigned = [e['assigned_actor_uid'] for e in events if e['kind'] == 'connect']
            self.assertEqual(assigned, [hex(POOL[0])] * 2 + [hex(POOL[1])] * 2)
        server.close(); await server.wait_closed()


if __name__ == '__main__':
    unittest.main()
