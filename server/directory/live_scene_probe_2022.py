"""Явные одноразовые команды локального опыта; файл обновляется атомарно."""
import json
from pathlib import Path
import re
import struct
from state_scene_actions_2022 import validate_state_action


class LiveSceneCommands:
    def __init__(self, path, sent=None):
        self.path = Path(path)
        self.sent = set() if sent is None else sent
        self.signature = None
        self.commands = []

    def refresh(self):
        if not self.path.exists():
            return
        stat = self.path.stat()
        signature = (stat.st_mtime_ns, stat.st_size)
        if signature == self.signature:
            return
        if stat.st_size > 1024 * 1024:
            raise ValueError('Команды опыта превышают 1МиБ')
        source = json.loads(self.path.read_text())
        if not isinstance(source, list) or len(source) > 128:
            raise ValueError('Нужен список не более128 команд')
        commands = []
        ids = set()
        for row in source:
            if not isinstance(row, dict) or 'id' not in row or ('command' not in row and 'action' not in row):
                raise ValueError('Нужен объект с id и command')
            name = row['id']
            if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', name) or name in ids:
                raise ValueError('Неверный или повторный id команды')
            ids.add(name)
            if 'action' in row:
                payload = validate_state_action(row)
                recipient = row.get('recipient_actor_uid')
                if isinstance(recipient,str) and re.fullmatch(r'(?:0x[0-9a-fA-F]+|[0-9]+)',recipient):
                    recipient = int(recipient,16 if recipient.startswith('0x') else 10)
                if 'recipient_actor_uid' in row and (type(recipient) is not int or not 0 < recipient < 2**64):
                    raise ValueError('recipient_actor_uid требует ненулевой AccountUID U64')
                commands.append((name,None,payload,[],recipient))
                continue
            code = int(str(row['command']), 0)
            if not 0 <= code <= 65535:
                raise ValueError('Opcode вне диапазона')
            if ('payload_file' in row) == ('payload_hex' in row):
                raise ValueError('Нужен один источник payload')
            if 'payload_file' in row:
                path = (self.path.parent / row['payload_file']).resolve()
                if not path.is_relative_to(self.path.parent.resolve()) or path.stat().st_size > 16384:
                    raise ValueError('Файл payload вне каталога опыта или слишком велик')
                payload = path.read_bytes()
            else:
                payload = bytes.fromhex(row['payload_hex'])
            if len(payload) > 16384:
                raise ValueError('Payload превышает16384 байта')
            recipient = row.get('recipient_actor_uid')
            if 'recipient_actor_uid' in row:
                if type(recipient) is str and re.fullmatch(r'(?:0x[0-9a-fA-F]+|[0-9]+)', recipient):
                    recipient = int(recipient, 16 if recipient.startswith('0x') else 10)
                if type(recipient) is not int or not 0 < recipient < 2**64:
                    raise ValueError('recipient_actor_uid требует ненулевой AccountUID U64')
            patches = []
            for key, size, fmt in (('actor_uid_offsets', 8, '>Q'),
                                   ('clock_tick_offsets', 4, '>I'),
                                   ('clock_seconds_offsets', 4, '>f')):
                offsets = row.get(key, [])
                if not isinstance(offsets, list):
                    raise ValueError('Неверные смещения ' + key)
                if any(type(at) is not int or at < 0 or at + size > len(payload) for at in offsets):
                    raise ValueError('Смещение вне payload: ' + key)
                if len(set(offsets)) != len(offsets):
                    raise ValueError('Повторное смещение ' + key)
                patches.append((key, fmt, offsets))
            commands.append((name, code, payload, patches, recipient))
        self.commands, self.signature = commands, signature

    def poll(self, actor_uid, tick, seconds):
        self.refresh()
        values = {'actor_uid_offsets': actor_uid, 'clock_tick_offsets': tick,
                  'clock_seconds_offsets': seconds}
        result = []
        for name, code, payload, patches, recipient in self.commands:
            # Фильтр сессии отделён от actor_uid_offsets внутри wire-payload:
            # цель камеры — чужой UnitUID, получатель — свой AccountUID.
            if name in self.sent or recipient is not None and recipient != actor_uid:
                continue
            if code is None:
                result.append((name,None,dict(payload)))
                continue
            patched = bytearray(payload)
            for key, fmt, offsets in patches:
                for at in offsets:
                    struct.pack_into(fmt, patched, at, values[key])
            result.append((name, code, bytes(patched)))
        return result

    def acknowledge(self, name):
        # Только после успешной отправки; читатель файла сам состояние не меняет.
        self.sent.add(name)
