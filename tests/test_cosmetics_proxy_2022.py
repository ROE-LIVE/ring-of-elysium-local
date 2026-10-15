"""Выдача локального владения после ENTER_GAME и изоляция UID на TCP-потоке."""
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

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tools'),str(ROOT/'server/directory')]
import heartbeat_probe_2022 as probe
import roe_protocol_2022 as protocol
from roe_team_2022 import server_message
from test_roe_protocol_2022 import KEY


class CosmeticsProxyTests(unittest.IsolatedAsyncioTestCase):
    async def test_login_catalog_and_selection_require_logged_in_uid(self):
        uid=42
        enter=bytearray(29);struct.pack_into('>Q',enter,12,uid)
        seed=server_message(0x32b,enter,100,KEY)
        backend_writers=[]
        async def backend(reader,writer):
            backend_writers.append(writer)
            writer.write(seed);await writer.drain()
            while await reader.read(65536):pass
            writer.close();await writer.wait_closed()
        async def packet(reader):
            header=await asyncio.wait_for(reader.readexactly(12),2)
            n=struct.unpack_from('>I',header,8)[0]
            plain=protocol.dt_plain(header+await asyncio.wait_for(reader.readexactly(n),2),KEY)
            return struct.unpack_from('>H',plain,4)[0],plain[10:]
        def request(identifier):
            body=struct.pack('>II',10201,7200016);code=0x54e2
            plain=struct.pack('>IIHIIIQI',7,30+len(body),code,0,0,0,identifier,code)+body
            cipher=protocol.encrypt(plain,KEY)
            return protocol.MAGIC+b'\0\x04'+struct.pack('>II',12,len(cipher))+cipher
        server=await asyncio.start_server(backend,'127.0.0.1',0)
        stop=asyncio.Event()
        (ROOT/'captures').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT/'captures') as temporary:
            folder=Path(temporary);key=folder/'key';key.write_bytes(KEY)
            catalog=folder/'catalog.json';catalog.write_text(json.dumps(dict(
                owned_gun_skin_ids=[7200016],owned_character_ids=[407],
                owned_accessory_ids=[200000],owned_clothing_ids=[1030004])))
            args=argparse.Namespace(session_key_file=key,reply=True,team_reply=True,
                local_cosmetics_config=catalog,port=0,duration=10,output=folder,
                upstream_port=server.sockets[0].getsockname()[1])
            ready=asyncio.get_running_loop().create_future()
            with contextlib.redirect_stdout(io.StringIO()):
                task=asyncio.create_task(probe.serve(args,ready,stop));writer=None
                try:
                    address,output=await asyncio.wait_for(ready,2)
                    reader,writer=await asyncio.open_connection(*address)
                    self.assertEqual(await reader.readexactly(len(seed)),seed)
                    packets=[await packet(reader) for _ in range(4)]
                    self.assertEqual([x[0] for x in packets],[0x54e1,0x73aa,0x73b0,0x5fb])
                    self.assertEqual(struct.unpack('>QB',packets[-1][1][-9:]),(uid,0))
                    # Повтор ENTER_GAME в том же TCP-сеансе не создаёт второй
                    # wardrobe snapshot и не удваивает количество вещей.
                    backend_writers[-1].write(seed+seed)
                    await backend_writers[-1].drain()
                    self.assertEqual(await reader.readexactly(2*len(seed)),seed+seed)
                    with self.assertRaises(asyncio.TimeoutError):
                        await asyncio.wait_for(reader.readexactly(1),.05)
                    writer.close();await writer.wait_closed();writer=None
                    # Новый TCP-вход получает новый полный каталог ровно один раз.
                    reader,writer=await asyncio.open_connection(*address)
                    self.assertEqual(await reader.readexactly(len(seed)),seed)
                    packets=[await packet(reader) for _ in range(4)]
                    self.assertEqual([x[0] for x in packets],[0x54e1,0x73aa,0x73b0,0x5fb])
                    writer.write(request(uid+1));await writer.drain()
                    with self.assertRaises(asyncio.TimeoutError):
                        await asyncio.wait_for(reader.readexactly(1),.05)
                    wire=request(uid)
                    for n in range(0,len(wire),3):writer.write(wire[n:n+3]);await writer.drain()
                    self.assertEqual(await packet(reader),(0x54e3,struct.pack('>III',0,10201,7200016)))
                    with self.assertRaises(asyncio.TimeoutError):
                        await asyncio.wait_for(reader.readexactly(1),.05)
                    writer.close();await writer.wait_closed();writer=None
                    stop.set();await task
                    events=[json.loads(x) for x in (output/'events.jsonl').read_text().splitlines()]
                    issued=[x for x in events if x['kind']=='cosmetics_issued']
                    self.assertEqual(len(issued),2)
                    self.assertEqual(len({x['connection'] for x in issued}),2)
                    self.assertEqual(sum(x['kind']=='cosmetic_action' for x in events),1)
                    upstream=[x for x in events if x['kind']=='cosmetic_upstream_order']
                    self.assertEqual(len(upstream),4)
                    for row in upstream:
                        self.assertEqual((row['code'],row['body_length']),('0x32b',29))
                        self.assertNotIn('fields_hex',row)
                        self.assertNotIn('raw',row)
                finally:
                    if writer:writer.close();await writer.wait_closed()
                    stop.set();await task
        server.close();await server.wait_closed()
