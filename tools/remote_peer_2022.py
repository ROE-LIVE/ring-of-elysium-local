"""Команда SSH для одного Linux peer в частной IPv4 LAN; без паролей/секретов."""
import ipaddress
import re


def ssh_command(peer):
    if not isinstance(peer, str) or peer.count('@') != 1:
        raise ValueError('RemotePeer: LinuxUser@LAN_IPv4')
    user, host = peer.split('@')
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.-]{0,31}', user):
        raise ValueError('RemotePeer: неверное имя Linux пользователя')
    address = ipaddress.IPv4Address(host)
    if not any(address in ipaddress.IPv4Network(network)
               for network in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16')):
        raise ValueError('RemotePeer: требуется частный LAN IPv4')
    return ['ssh', '-N', '-v', '-o', 'ExitOnForwardFailure=yes',
            '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=3',
            '-L', '127.0.0.1:8001:127.0.0.1:8001',
            '-L', '127.0.0.1:19001:127.0.0.1:19001', f'{user}@{address}']
