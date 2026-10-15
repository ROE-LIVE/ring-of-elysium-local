"""Локальный наблюдатель TCP/UDP. Полученные блоки TCP не считаются пакетами."""
import argparse
import asyncio
import datetime as dt
import ipaddress
import json
from pathlib import Path
import signal
import uuid

ROOT = Path(__file__).resolve().parents[2]


def hexdump(data):
    return '\n'.join(f'{offset:08x}  {data[offset:offset+16].hex(" "):<47}  '+''.join(chr(v) if 32 <= v < 127 else '.' for v in data[offset:offset+16]) for offset in range(0, len(data), 16))


class Capture:
    def __init__(self, directory):
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=False)
        self.events = (directory/'events.jsonl').open('a', encoding='utf-8', buffering=1)
        self.seq = 0

    def record(self, kind, data=None, **fields):
        self.seq += 1
        event = dict(sequence=self.seq, timestamp=dt.datetime.now(dt.timezone.utc).isoformat(), kind=kind, **fields)
        if data is not None:
            name = f'{self.seq:06d}-{kind}'
            (self.directory/f'{name}.bin').write_bytes(data)
            (self.directory/f'{name}.txt').write_text(hexdump(data)+'\n', encoding='utf-8')
            event.update(length=len(data), raw=f'{name}.bin', hex=f'{name}.txt')
        self.events.write(json.dumps(event, ensure_ascii=False)+'\n')
        print(json.dumps(event, ensure_ascii=False), flush=True)


def load_script(path):
    if not path:
        return []
    rules = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(rules, list):
        raise ValueError('Сценарий должен быть JSON-массивом')
    for rule in rules:
        if rule.get('transport') not in ('tcp', 'udp') or rule.get('event') not in ('connect', 'prefix'):
            raise ValueError('Допустимы transport=tcp/udp, event=connect/prefix')
        if rule['transport'] == 'udp' and rule['event'] == 'connect':
            raise ValueError('UDP не имеет события connect')
        rule['response'] = bytes.fromhex(rule['response_hex'])
        rule['prefix'] = bytes.fromhex(rule.get('prefix_hex', ''))
        if rule['event'] == 'prefix' and not rule['prefix']:
            raise ValueError('Пустой prefix_hex запрещён')
        if len(rule['prefix']) > 65536 or len(rule['response']) > 65507:
            raise ValueError('Слишком большой префикс или ответ')
    return rules


async def serve(args, ready=None, stop=None):
    rules = load_script(args.script)
    run = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S')+'-'+uuid.uuid4().hex[:8]
    capture = Capture(args.output/run)
    tasks, writers = set(), set()
    stop = stop or asyncio.Event()
    loop = asyncio.get_running_loop()
    servers, udp = [], None

    async def handle(reader, writer):
        task = asyncio.current_task()
        tasks.add(task)
        writers.add(writer)
        connection = uuid.uuid4().hex[:12]
        info = dict(transport='tcp', connection=connection, remote=writer.get_extra_info('peername'), local=writer.get_extra_info('sockname'))
        capture.record('connect', **info)
        prefix = bytearray()
        applied = set()
        try:
            for index, rule in enumerate(rules):
                if rule['transport'] == 'tcp' and rule['event'] == 'connect':
                    writer.write(rule['response'])
                    await writer.drain()
                    capture.record('send', rule['response'], **info, rule=index)
                    applied.add(index)
            while True:
                try:
                    data = await asyncio.wait_for(reader.read(65536), args.idle_timeout)
                except asyncio.TimeoutError:
                    capture.record('idle_timeout', **info)
                    break
                if not data:
                    break
                capture.record('recv', data, **info)
                prefix.extend(data[:max(0, 65536-len(prefix))])
                for index, rule in enumerate(rules):
                    if index not in applied and rule['transport'] == 'tcp' and rule['event'] == 'prefix' and prefix.startswith(rule['prefix']):
                        writer.write(rule['response'])
                        await writer.drain()
                        capture.record('send', rule['response'], **info, rule=index)
                        applied.add(index)
        except (ConnectionError, OSError) as exc:
            capture.record('connection_error', **info, error=str(exc))
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionError, OSError):
                pass
            capture.record('disconnect', **info)
            writers.discard(writer)
            tasks.discard(task)

    class UDP(asyncio.DatagramProtocol):
        def connection_made(self, transport):
            self.transport = transport

        def datagram_received(self, data, addr):
            info = dict(transport='udp', remote=addr, local=self.transport.get_extra_info('sockname'))
            capture.record('recv', data, **info)
            for index, rule in enumerate(rules):
                if rule['transport'] == 'udp' and data.startswith(rule['prefix']):
                    self.transport.sendto(rule['response'], addr)
                    capture.record('send', rule['response'], **info, rule=index)

        def error_received(self, exc):
            capture.record('udp_error', error=str(exc))

    try:
        bindings = {}
        if args.transport in ('tcp', 'both'):
            server = await asyncio.start_server(handle, args.host, args.port)
            servers.append(server)
            bindings['tcp'] = server.sockets[0].getsockname()
        if args.transport in ('udp', 'both'):
            udp, _ = await loop.create_datagram_endpoint(UDP, local_addr=(args.host, args.port))
            bindings['udp'] = udp.get_extra_info('sockname')
        capture.record('ready', bindings=bindings, script=str(args.script) if args.script else None, note='TCP recv — блок потока, не граница сообщения')
        if ready:
            ready.set_result((bindings, capture.directory))
        if args.duration:
            try:
                await asyncio.wait_for(stop.wait(), args.duration)
            except asyncio.TimeoutError:
                pass
        else:
            await stop.wait()
    finally:
        for server in servers:
            server.close()
            await server.wait_closed()
        if udp:
            udp.close()
        for task in list(tasks):
            task.cancel()
        if tasks:
            await asyncio.gather(*list(tasks), return_exceptions=True)
        capture.record('stopped')
        capture.events.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8001)
    parser.add_argument('--transport', choices=['tcp', 'udp', 'both'], default='both')
    parser.add_argument('--output', type=Path, default=ROOT/'captures')
    parser.add_argument('--script', type=Path)
    parser.add_argument('--duration', type=float, default=0)
    parser.add_argument('--idle-timeout', type=float, default=120)
    args = parser.parse_args()
    if not ipaddress.ip_address(args.host).is_loopback:
        parser.error('Разрешён только loopback-адрес')
    if args.duration < 0 or args.idle_timeout <= 0 or not 0 <= args.port <= 65535:
        parser.error('Некорректный порт или тайм-аут')
    try:
        asyncio.run(serve(args))
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
