"""Два ограниченных TCP перенаправления для LAN; игровые тела не разбираются."""
import argparse
import asyncio
import contextlib
import ipaddress
import json
from pathlib import Path
import signal


def lan_address(value):
    address = ipaddress.IPv4Address(value)
    if not any(address in ipaddress.IPv4Network(n) for n in
               ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16')):
        raise ValueError('ServerIP: требуется частный LAN IPv4')
    return str(address)


def client_routes(server, lobby_port=32001, tunnel_port=32002):
    server = lan_address(server)
    if any(type(p) is not int or not 1 <= p <= 65535 for p in (lobby_port, tunnel_port)):
        raise ValueError('Порты:1..65535')
    if lobby_port == tunnel_port:
        raise ValueError('Порты лобби и игрового моста должны различаться')
    return [(('127.0.0.1', 8001), (server, lobby_port)),
            (('127.0.0.1', 19001), (server, tunnel_port))]


class Relay:
    def __init__(self, routes, max_connections=16, fault=None):
        self.routes = routes
        self.fault = fault
        self.max_connections = max_connections
        self.servers = []
        self.tasks = set()

    async def start(self):
        try:
            for listen, target in self.routes:
                async def handle(reader, writer, destination=target):
                    await self.handle(reader, writer, destination)
                self.servers.append(await asyncio.start_server(handle, *listen))
        except BaseException:
            await self.close()
            raise
        return [s.sockets[0].getsockname() for s in self.servers]

    async def handle(self, reader, writer, target):
        if len(self.tasks) >= self.max_connections or self.fault and self.fault.blocked(target):
            writer.close()
            await writer.wait_closed()
            return
        task = asyncio.current_task()
        self.tasks.add(task)
        other = None
        children = []
        async def pump(source, destination):
            while True:
                data = await source.read(65536)
                if not data:
                    if destination.can_write_eof():
                        destination.write_eof()
                        await destination.drain()
                    return
                if self.fault:
                    await self.fault.before_write(target)
                destination.write(data)
                await destination.drain()
        try:
            async with asyncio.timeout(10):
                remote, other = await asyncio.open_connection(*target)
            if self.fault:
                self.fault.connections[writer] = target
                self.fault.connections[other] = target
                if self.fault.blocked(target):
                    raise ConnectionResetError('Канал отключён локальным опытом')
            children = [asyncio.create_task(pump(reader, other)),
                        asyncio.create_task(pump(remote, writer))]
            await asyncio.gather(*children)
        except (OSError, ConnectionError, TimeoutError):
            print(json.dumps(dict(kind='relay_connection_closed', target=list(target))), flush=True)
        finally:
            for child in children:
                child.cancel()
            streams = [stream for stream in (writer,other) if stream is not None]
            for stream in streams:
                if self.fault:
                    self.fault.connections.pop(stream, None)
                stream.close()
            try:
                await asyncio.gather(*children, return_exceptions=True)
                for stream in streams:
                    with contextlib.suppress(OSError, ConnectionError, TimeoutError):
                        await asyncio.wait_for(stream.wait_closed(),1)
            finally:
                # Отмена может прийти уже во время cleanup предыдущего EOF.
                for stream in streams:
                    stream.transport.abort()
                self.tasks.discard(task)

    async def close(self):
        for server in self.servers:
            server.close()
        tasks = list(self.tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for server in self.servers:
            await server.wait_closed()


async def run(args):
    if args.pod_export:
        routes = [(('0.0.0.0', 28001), ('127.0.0.1', 8001)),
                  (('0.0.0.0', 29001), ('127.0.0.1', 19001))]
    else:
        routes = client_routes(args.server, args.lobby_port, args.tunnel_port)
    ready_file = Path(args.ready_file) if args.ready_file else None
    if ready_file:
        ready_file.unlink(missing_ok=True)
    fault = None
    monitor = None
    if getattr(args, 'control_file', None):
        if args.pod_export:
            raise ValueError('Локальные сетевые опыты разрешены только на клиентском мосте')
        from network_fault_2022 import NetworkFault
        fault = NetworkFault(args.control_file, routes)
    relay = Relay(routes, fault=fault)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(signum, stop.set)
    try:
        bindings = await relay.start()
        if fault:
            monitor = asyncio.create_task(fault.monitor())
        state = dict(kind='ready', mode='pod-export' if args.pod_export else 'lan-client',
                     bindings=bindings, targets=[t for _, t in routes])
        if ready_file:
            ready_file.write_text(json.dumps(state))
        print(json.dumps(state), flush=True)
        if args.duration:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), args.duration)
        else:
            await stop.wait()
    finally:
        if ready_file:
            ready_file.unlink(missing_ok=True)
        await relay.close()
        if monitor:
            monitor.cancel()
            await asyncio.gather(monitor, return_exceptions=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--server', type=lan_address)
    mode.add_argument('--pod-export', action='store_true')
    parser.add_argument('--lobby-port', type=int, default=32001)
    parser.add_argument('--tunnel-port', type=int, default=32002)
    parser.add_argument('--duration', type=int, default=3600)
    parser.add_argument('--ready-file')
    parser.add_argument('--control-file', help='Локальный конечный сетевой опыт; по умолчанию выключен')
    args = parser.parse_args()
    if not 0 <= args.duration <= 7200:
        parser.error('duration0..7200;0 — до остановки')
    if not args.pod_export:
        try:
            client_routes(args.server, args.lobby_port, args.tunnel_port)
        except ValueError as error:
            parser.error(str(error))
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        pass
