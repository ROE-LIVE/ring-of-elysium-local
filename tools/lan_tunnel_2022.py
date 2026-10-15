"""Собственный loopback UDP↔TCP мост для SSH; не игровой tcp-over-udp2022."""
import argparse
import asyncio
import contextlib
import ipaddress
import json
import struct
import time

MAX_DATAGRAM = 65507
QUEUE_SIZE = 64
MAGIC = b'ROEUDPTUN1\0'


class ProfileMismatch(ValueError):
    """Клиент и backend указали разные локальные профили."""


def endpoint(value):
    host, separator, raw_port = value.rpartition(':')
    if not separator or not raw_port.isascii() or not raw_port.isdecimal():
        raise ValueError('Адрес: loopback IPv4:port')
    address = ipaddress.IPv4Address(host)
    port = int(raw_port)
    if not address.is_loopback or not 0 <= port <= 65535:
        raise ValueError('Мост слушает/соединяется только с loopback IPv4')
    return str(address), port


def frame(data):
    if not isinstance(data, bytes) or not 1 <= len(data) <= MAX_DATAGRAM:
        raise ValueError('UDP datagram:1..65507 bytes')
    return struct.pack('>H', len(data)) + data


async def read_frame(reader):
    header = await reader.readexactly(2)
    length = struct.unpack('>H', header)[0]
    if not 1 <= length <= MAX_DATAGRAM:
        raise ValueError('Недопустимая длина датаграммы')
    return await reader.readexactly(length)


class DatagramQueue(asyncio.DatagramProtocol):
    def __init__(self, single_peer=False):
        self.queue = asyncio.Queue(QUEUE_SIZE)
        self.transport = None
        self.peer = None
        self.peer_last_seen = 0
        self.single_peer = single_peer
        self.received = 0
        self.dropped = 0

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data, address):
        if self.single_peer:
            if self.peer is None:
                self.peer = address
            elif address != self.peer:
                if time.monotonic() - self.peer_last_seen < 2:
                    self.dropped += 1
                    return
                # Новый match может открыть новый local UDP port. Переключаем
                # только после тишины; очереди прошлого peer не наследуются.
                self.peer = address
                while not self.queue.empty():
                    self.queue.get_nowait()
            self.peer_last_seen = time.monotonic()
        if not data or len(data) > MAX_DATAGRAM or self.queue.full():
            self.dropped += 1
            return
        self.received += 1
        self.queue.put_nowait(bytes(data))


async def forward_udp(protocol, writer):
    while True:
        data = await protocol.queue.get()
        writer.write(frame(data))
        await writer.drain()


async def forward_tcp(reader, protocol, connected):
    while True:
        data = await read_frame(reader)
        if connected:
            protocol.transport.sendto(data)
        elif protocol.peer is not None:
            protocol.transport.sendto(data, protocol.peer)


async def exchange(reader, writer, protocol, connected):
    tasks = [asyncio.create_task(forward_udp(protocol, writer)),
             asyncio.create_task(forward_tcp(reader, protocol, connected))]
    try:
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        writer.close()
        with contextlib.suppress(OSError, ConnectionError):
            await writer.wait_closed()


class TunnelServer:
    """Один TCP сеанс→один UDP socket; второй активный клиент отклоняется."""
    def __init__(self, target, profile='default'):
        from local_account_2022 import local_account
        self.target = target
        self.profile = local_account('.', profile)['name']
        self.server = None
        self.tasks = set()
        self.active = False

    async def start(self, listen):
        self.server = await asyncio.start_server(self.handle, *listen)
        return self.server.sockets[0].getsockname()

    async def handle(self, reader, writer):
        if self.active:
            writer.close()
            await writer.wait_closed()
            return
        self.active = True
        task = asyncio.current_task()
        self.tasks.add(task)
        transport = None
        try:
            loop = asyncio.get_running_loop()
            writer.write(MAGIC + frame(json.dumps(dict(profile=self.profile),
                                                  separators=(',', ':')).encode('ascii')))
            await writer.drain()
            transport, protocol = await loop.create_datagram_endpoint(
                DatagramQueue, local_addr=('127.0.0.1', 0), remote_addr=self.target)
            await exchange(reader, writer, protocol, True)
        except (asyncio.IncompleteReadError, ConnectionError, OSError, ValueError):
            pass
        finally:
            if transport:
                transport.close()
            writer.close()
            self.active = False
            self.tasks.discard(task)

    async def close(self):
        if self.server:
            self.server.close()
            await self.server.wait_closed()
        tasks = list(self.tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def client(listen, target, ready=None, expected_profile=None):
    loop = asyncio.get_running_loop()
    transport, protocol = await loop.create_datagram_endpoint(
        lambda: DatagramQueue(single_peer=True), local_addr=listen)
    try:
        announced = False
        while True:
            try:
                reader, writer = await asyncio.wait_for(asyncio.open_connection(*target), 5)
                try:
                    async def banner():
                        if await reader.readexactly(len(MAGIC)) != MAGIC:
                            raise ProfileMismatch('TCP target не ROE UDP tunnel')
                        body = await read_frame(reader)
                        if len(body) > 256:
                            raise ProfileMismatch('Слишком большой tunnel banner')
                        try:
                            value = json.loads(body)
                        except ValueError as error:
                            raise ProfileMismatch('Неверный tunnel banner') from error
                        if not isinstance(value, dict) or set(value) != {'profile'}:
                            raise ProfileMismatch('Неверная схема tunnel banner')
                        profile = value['profile']
                        if expected_profile is not None and profile != expected_profile:
                            raise ProfileMismatch('Remote Profile отличается: ' + str(profile))
                    await asyncio.wait_for(banner(), 5)
                except BaseException:
                    writer.close()
                    with contextlib.suppress(OSError, ConnectionError):
                        await writer.wait_closed()
                    raise
                if ready and not announced:
                    ready(transport.get_extra_info('sockname'))
                    announced = True
                await exchange(reader, writer, protocol, False)
            except ProfileMismatch:
                raise
            except (asyncio.TimeoutError, asyncio.IncompleteReadError, ConnectionError, OSError, ValueError):
                # После обрыва старые пакеты не переносятся в новый канал.
                while not protocol.queue.empty():
                    protocol.queue.get_nowait()
                await asyncio.sleep(.5)
    finally:
        transport.close()


async def main_async(args):
    def ready(binding):
        print(json.dumps(dict(kind='ready', mode=args.mode, listen=list(binding),
                              target=list(args.target), synthetic_transport=True)), flush=True)
    if args.mode == 'server':
        server = TunnelServer(args.target, args.profile)
        try:
            ready(await server.start(args.listen))
            await asyncio.sleep(args.duration)
        finally:
            await server.close()
    else:
        try:
            await asyncio.wait_for(client(args.listen, args.target, ready, args.profile), args.duration)
        except asyncio.TimeoutError:
            pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('server', 'client'))
    parser.add_argument('--listen', type=endpoint)
    parser.add_argument('--target', type=endpoint)
    parser.add_argument('--duration', type=int, default=3600)
    parser.add_argument('--profile', default='default')
    args = parser.parse_args()
    from local_account_2022 import local_account
    try:
        args.profile = local_account('.', args.profile)['name']
    except ValueError as error:
        parser.error(str(error))
    if not 1 <= args.duration <= 7200:
        parser.error('duration1..7200')
    args.listen = args.listen or ('127.0.0.1', 19001 if args.mode == 'server' else 18001)
    args.target = args.target or ('127.0.0.1', 18001 if args.mode == 'server' else 19001)
    if args.target[1] == 0:
        parser.error('target port требует1..65535')
    try:
        asyncio.run(main_async(args))
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
