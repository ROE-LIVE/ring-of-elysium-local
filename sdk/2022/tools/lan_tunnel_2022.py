"""Собственный loopback UDP↔TCP мост для SSH; не игровой tcp-over-udp2022."""
import argparse
import asyncio
import contextlib
from collections import OrderedDict
import ipaddress
import json
import os
import struct
import time

MAX_DATAGRAM = 65507
QUEUE_SIZE = 64
MAGIC = b'ROEUDPTUN1\0'
NATIVE_DELIVERY_DELAY_SECONDS = .01


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
        self.native_routes = OrderedDict()
        self.peer_last_seen = 0
        self.single_peer = single_peer
        self.received = 0
        self.dropped = 0
        self.queue_full = 0
        self.peer_rejected = 0
        self.peer_switches = 0
        self.discarded = 0
        self.tcp_to_udp = 0
        self.udp_to_tcp = 0
        self.connections = 0
        self.reconnects = 0
        self.header_records = 0
        self.header_trace = os.environ.get("ROE_TUNNEL_HEADER_TRACE") == "1"

    def trace_header(self, data, direction):
        # Опыт ограничен 60000 заголовками; тела и ключи не сохраняются.
        if not self.header_trace or self.header_records >= 60000 or len(data) < 24:
            return
        head = (data[12] >> 4) * 4
        if not 20 <= head <= len(data) - 4:
            return
        source, destination, seq, ack = struct.unpack_from('>HHII', data)
        self.header_records += 1
        print(json.dumps(dict(kind='tunnel_header', timestamp=time.time(),
            direction=direction, source_port=source, destination_port=destination,
            seq=seq, ack=ack, flags=data[13], window=struct.unpack_from('>H', data, 14)[0],
            payload_length=len(data)-head-4,
            echoed_clock=struct.unpack_from('<H', data, 16)[0],
            clock=struct.unpack_from('<H', data, 18)[0])), flush=True)

    def discard_queue(self):
        while not self.queue.empty():
            self.queue.get_nowait()
            self.discarded += 1

    def snapshot(self):
        # Только счётчики: содержимое игровых пакетов в журнал не попадает.
        return {name: getattr(self, name) for name in (
            'received', 'dropped', 'queue_full', 'peer_rejected', 'peer_switches',
            'discarded', 'tcp_to_udp', 'udp_to_tcp', 'connections', 'reconnects')} | {
                'queued': self.queue.qsize(),
                'peer_port': self.peer[1] if self.peer else None}

    def connection_made(self, transport):
        self.transport = transport

    def native_route(self, data):
        # Порты внутреннего RUDP отличны от портов внешнего UDP-сокета.
        from roe_tgcp_2023 import parse_datagram
        try:
            packet = parse_datagram(data)
        except ValueError:
            return None
        return packet

    def reply_peer(self, data):
        packet = self.native_route(data)
        if packet is not None:
            return self.native_routes.get((packet.destination_port, packet.source_port))
        return self.peer

    def datagram_received(self, data, address):
        self.trace_header(data, "udp_received")
        packet = self.native_route(data) if self.single_peer else None
        if packet is not None:
            route = (packet.source_port, packet.destination_port)
            known = self.native_routes.get(route)
            if known != address:
                # Новый маршрут создаётся только корректным SYN без ACK.
                if not packet.flags & 2 or packet.flags & 0x10:
                    self.dropped += 1
                    self.peer_rejected += 1
                    return
                self.native_routes[route] = address
                self.native_routes.move_to_end(route)
                while len(self.native_routes) > 64:
                    self.native_routes.popitem(last=False)
            self.peer = address
            self.peer_last_seen = time.monotonic()
        elif self.single_peer:
            if self.peer is None:
                self.peer = address
            elif address != self.peer:
                if time.monotonic() - self.peer_last_seen < 2:
                    self.dropped += 1
                    self.peer_rejected += 1
                    return
                # Новый match может открыть новый local UDP port. Переключаем
                # только после тишины; очереди прошлого peer не наследуются.
                self.peer = address
                self.peer_switches += 1
                self.discard_queue()
            self.peer_last_seen = time.monotonic()
        if not data or len(data) > MAX_DATAGRAM or self.queue.full():
            self.dropped += 1
            if self.queue.full():
                self.queue_full += 1
            return
        self.received += 1
        self.queue.put_nowait(bytes(data))


async def forward_udp(protocol, writer):
    while True:
        data = await protocol.queue.get()
        writer.write(frame(data))
        await writer.drain()
        protocol.udp_to_tcp += 1


async def forward_tcp(reader, protocol, connected):
    native_bytes = native_packets = 0
    while True:
        data = await read_frame(reader)
        protocol.trace_header(data, "tcp_received")
        if connected:
            protocol.transport.sendto(data)
            protocol.tcp_to_udp += 1
        else:
            address = protocol.reply_peer(data)
            if address is not None:
                protocol.transport.sendto(data, address)
                protocol.tcp_to_udp += 1
                native_bytes += len(data)
                native_packets += 1
                if native_bytes >= 8192 or native_packets >= 16:
                    # TCP может выдать накопленный поток за один оборот цикла.
                    # Игровой UDP-сокет не получает обратное давление TCP:
                    # ограничиваем локальный всплеск, сохраняя порядок/байты.
                    await asyncio.sleep(NATIVE_DELIVERY_DELAY_SECONDS)
                    native_bytes = native_packets = 0
        # readexactly на готовом TCP-буфере не отдаёт управление циклу.
        # На подключённом серверном endpoint сохраняем паузу1мс;
        # доставку в игровой сокет ограничивает отдельный бюджет выше.
        await asyncio.sleep(.001 if connected else 0)


async def telemetry(protocol, connected):
    try:
        while True:
            await asyncio.sleep(5)
            emit_telemetry(protocol, connected, 'periodic')
    finally:
        emit_telemetry(protocol, connected, 'exchange_closed')


def emit_telemetry(protocol, connected, reason):
    print(json.dumps(dict(kind='tunnel_stats', timestamp=time.time(),
                         mode='server' if connected else 'client', reason=reason,
                         **protocol.snapshot())), flush=True)


async def exchange(reader, writer, protocol, connected):
    tasks = [asyncio.create_task(forward_udp(protocol, writer)),
             asyncio.create_task(forward_tcp(reader, protocol, connected))]
    monitor = asyncio.create_task(telemetry(protocol, connected))
    try:
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
    finally:
        tasks.append(monitor)
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
            protocol.connections += 1
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
                protocol.connections += 1
                await exchange(reader, writer, protocol, False)
            except ProfileMismatch:
                raise
            except (asyncio.TimeoutError, asyncio.IncompleteReadError, ConnectionError, OSError, ValueError):
                # После обрыва старые пакеты не переносятся в новый канал.
                protocol.reconnects += 1
                protocol.discard_queue()
                emit_telemetry(protocol, False, 'reconnect')
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
            if args.duration:
                await asyncio.sleep(args.duration)
            else:
                await asyncio.Event().wait()
        finally:
            await server.close()
    else:
        try:
            await asyncio.wait_for(client(args.listen, args.target, ready, args.profile), args.duration or None)
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
    if not 0 <= args.duration <= 7200:
        parser.error('duration0..7200;0 — до остановки родителем')
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
