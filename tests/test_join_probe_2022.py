"""JOIN_INSTANCE: согласование уведомления и ответа на реальных TCP-потоках."""
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
from roe_join_instance_2022 import decode_join_instance_notification, decode_join_instance_response
from test_roe_protocol_2022 import KEY


class JoinProbeTests(unittest.IsolatedAsyncioTestCase):
    async def test_notify_request_guard_fragmentation_and_single_reply(self):
        await self.exercise(1)

    async def test_second_match_on_same_tcp_connection_gets_new_join_and_duplicate_guard(self):
        await self.exercise(2)

    async def exercise(self, cycles):
        uid = 123456
        enter = bytearray(29)
        struct.pack_into('>Q', enter, 12, uid)
        seed = server_message(0x32b, enter, 100, KEY)
        forwarded = bytearray()

        async def backend(reader, writer):
            try:
                writer.write(seed)
                await writer.drain()
                while data := await reader.read(65536):
                    forwarded.extend(data)
            finally:
                writer.close()
                await writer.wait_closed()

        def request(code, body, identifier=uid):
            plain = struct.pack('>IIHIIIQI', 7, 30 + len(body), code, 0, 0, 0, identifier, code) + body
            cipher = protocol.encrypt(plain, KEY)
            return protocol.MAGIC + b'\0\x04' + struct.pack('>II', 12, len(cipher)) + cipher

        async def response(reader):
            header = await asyncio.wait_for(reader.readexactly(12), 2)
            size = struct.unpack_from('>I', header, 8)[0]
            plain = protocol.dt_plain(header + await reader.readexactly(size), KEY)
            return struct.unpack_from('>H', plain, 4)[0], plain[10:]

        server = await asyncio.start_server(backend, '127.0.0.1', 0)
        stop = asyncio.Event()
        task = writer = None
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            keyfile = directory / 'key'; keyfile.write_bytes(KEY)
            config = {'delay_after_found':0,
                'notification':dict(unknown_00=0,instance_id=1,unknown_0c=0,unknown_14=0,unknown_18=0,unknown_20=0,unknown_28=0,unknown_2c=0),
                'response':dict(result=0,route='0:127.0.0.1:18001',block_88='00'*16,block_98='00'*16,connection_id_a8=1,unknown_ac=0,flag_b0=0)}
            config['delay_after_found'] = 0
            configfile = directory / 'join.json'; configfile.write_text(json.dumps(config))
            args = argparse.Namespace(session_key_file=keyfile, reply=True, team_reply=True,
                match_reply=True, match_found_delay=0, novice_state=1, training_reply=True,
                join_instance_config=configfile, port=0, duration=10, output=directory,
                upstream_port=server.sockets[0].getsockname()[1])
            ready = asyncio.get_running_loop().create_future()
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    task = asyncio.create_task(probe.serve(args, ready, stop))
                    address, capture = await asyncio.wait_for(ready, 2)
                    reader, writer = await asyncio.open_connection(*address)
                    self.assertEqual(await reader.readexactly(len(seed)), seed)
                    self.assertEqual((await response(reader))[0], 0x6e35)
                    early = request(0xd75, struct.pack('>Q', 1))
                    start = request(0x6e29, struct.pack('>5I', 1, 1, 1, 2, 16023))
                    writer.write(early + start); await writer.drain()
                    self.assertEqual((await response(reader))[0], 0x6e2a)
                    self.assertEqual((await response(reader))[0], 0x6e2d)
                    code, body = await response(reader)
                    self.assertEqual(code, 0xd77)
                    self.assertEqual(decode_join_instance_notification(body).instance_id, 1)
                    wrong_uid = request(0xd75, struct.pack('>Q', 1), uid+1)
                    wrong_id = request(0xd75, struct.pack('>Q', 2))
                    wire = wrong_uid + wrong_id + early
                    for offset in range(0, len(wire), 3):
                        writer.write(wire[offset:offset+3]); await writer.drain()
                    code, body = await response(reader)
                    self.assertEqual(code, 0xd76)
                    self.assertEqual(decode_join_instance_response(body).route, b'0:127.0.0.1:18001')
                    writer.write(early); await writer.drain()
                    additional = b''
                    if cycles == 2:
                        writer.write(start); await writer.drain()
                        self.assertEqual((await response(reader))[0], 0x6e2a)
                        self.assertEqual((await response(reader))[0], 0x6e2d)
                        self.assertEqual((await response(reader))[0], 0xd77)
                        writer.write(early); await writer.drain()
                        code, body = await response(reader)
                        self.assertEqual(code, 0xd76)
                        self.assertEqual(decode_join_instance_response(body).route, b'0:127.0.0.1:18001')
                        writer.write(early); await writer.drain()
                        additional = start + early + early
                    writer.write_eof()
                    self.assertEqual(await asyncio.wait_for(reader.read(), 2), b'')
                    stop.set(); await task
                    state = json.loads((capture / 'status.json').read_text())
                    self.assertEqual((state['join_notifications'], state['join_requests'], state['join_responses']), (cycles, 5+2*(cycles-1), cycles))
                    self.assertEqual(state['inspection_errors'], 0)
                    self.assertEqual(bytes(forwarded), early + start + wire + early + additional)
                    events = [json.loads(line) for line in (capture/'events.jsonl').read_text().splitlines()]
                    self.assertEqual(sum(e['kind']=='join_skipped' for e in events), 4+cycles-1)
            finally:
                if writer:
                    writer.close(); await writer.wait_closed()
                stop.set()
                if task: await task
                server.close(); await server.wait_closed()
