"""Обычная очередь (Solo с CREATE): STOP после Match Found без JOIN и опыт --join-any-queue."""
import argparse
import asyncio
import contextlib
import io
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import heartbeat_probe_2022 as probe
import roe_protocol_2022 as protocol
from roe_team_2022 import server_message
from test_roe_protocol_2022 import KEY

UID = 123456
CREATE = struct.pack('>4I', 1, 16010, 1, 0)
# Наблюдённый 6e29 очереди Solo/TPP (26.10): последний U32 = 16007.
SOLO = struct.pack('>5I', 1, 1, 1, 1, 16007)


class MatchQueueTests(unittest.IsolatedAsyncioTestCase):
    async def test_stop_after_found_without_join_is_answered(self):
        codes = await self.exercise(join_any_queue=False)
        self.assertEqual(codes, [0x701e, 0x6e2a, 0x6e2d, 0x6e2c])

    async def test_join_any_queue_sends_join_after_solo_found(self):
        codes = await self.exercise(join_any_queue=True)
        self.assertEqual(codes, [0x701e, 0x6e2a, 0x6e2d, 0xd77])

    async def exercise(self, join_any_queue):
        enter = bytearray(29)
        struct.pack_into('>Q', enter, 12, UID)
        seed = server_message(0x32b, enter, 100, KEY)

        async def backend(reader, writer):
            try:
                writer.write(seed)
                await writer.drain()
                while await reader.read(65536):
                    pass
            finally:
                writer.close()
                await writer.wait_closed()

        def request(code, body):
            plain = struct.pack('>IIHIIIQI', 7, 30 + len(body), code, 0, 0, 0, UID, code) + body
            cipher = protocol.encrypt(plain, KEY)
            return protocol.MAGIC + b'\0\x04' + struct.pack('>II', 12, len(cipher)) + cipher

        async def response(reader):
            header = await asyncio.wait_for(reader.readexactly(12), 2)
            size = struct.unpack_from('>I', header, 8)[0]
            plain = protocol.dt_plain(header + await reader.readexactly(size), KEY)
            return struct.unpack_from('>H', plain, 4)[0]

        server = await asyncio.start_server(backend, '127.0.0.1', 0)
        stop = asyncio.Event()
        task = writer = None
        codes = []
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            keyfile = directory / 'key'; keyfile.write_bytes(KEY)
            config = {'delay_after_found': 0,
                'notification': dict(unknown_00=0, instance_id=1, unknown_0c=0, unknown_14=0, unknown_18=0, unknown_20=0, unknown_28=0, unknown_2c=0),
                'response': dict(result=0, route='0:127.0.0.1:18001', block_88='00'*16, block_98='00'*16, connection_id_a8=1, unknown_ac=0, flag_b0=0)}
            configfile = directory / 'join.json'; configfile.write_text(json.dumps(config))
            args = argparse.Namespace(session_key_file=keyfile, reply=True, team_reply=True,
                match_reply=True, match_found_delay=0, novice_state=1, training_reply=True,
                join_instance_config=configfile, join_any_queue=join_any_queue, port=0, duration=10,
                output=directory, upstream_port=server.sockets[0].getsockname()[1])
            ready = asyncio.get_running_loop().create_future()
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    task = asyncio.create_task(probe.serve(args, ready, stop))
                    address, capture = await asyncio.wait_for(ready, 2)
                    reader, writer = await asyncio.open_connection(*address)
                    self.assertEqual(await reader.readexactly(len(seed)), seed)
                    self.assertEqual(await response(reader), 0x6e35)
                    writer.write(request(0x701d, CREATE)); await writer.drain()
                    codes.append(await response(reader))
                    writer.write(request(0x6e29, SOLO)); await writer.drain()
                    codes.append(await response(reader))
                    codes.append(await response(reader))
                    if join_any_queue:
                        codes.append(await response(reader))
                    else:
                        writer.write(request(0x6e2b, b'\0')); await writer.drain()
                        codes.append(await response(reader))
                    writer.write_eof()
                    await asyncio.wait_for(reader.read(), 2)
                    stop.set(); await task
                    events = [json.loads(line) for line in (capture/'events.jsonl').read_text().splitlines()]
                    self.assertFalse(any(e['kind'] == 'match_skipped' for e in events))
            finally:
                if writer:
                    writer.close(); await writer.wait_closed()
                stop.set()
                if task: await task
                server.close(); await server.wait_closed()
        return codes


if __name__ == '__main__':
    unittest.main()
