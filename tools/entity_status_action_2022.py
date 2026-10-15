"""Диагностическое открытие/закрытие двери2022 через очередь текущего опыта.

Отправляет wire-снимок клиенту; серверный реестр дверей не изменяет.
"""
import argparse
import json
import os
from pathlib import Path
import struct
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server/directory'))
from live_scene_probe_2022 import LiveSceneCommands


def make_command(entity_id, state, command_id):
    if type(entity_id) is not int or not 0 < entity_id < 2**32:
        raise ValueError('Нужен ненулевой entity_id U32')
    if state not in ('open', 'closed'):
        raise ValueError('Состояние: open или closed')
    return {'id': command_id, 'command': '0x6f55',
            'payload_hex': struct.pack('>IBBBBQ', entity_id, int(state == 'open'), 0, 0, 0, 0).hex()}


def enqueue(path, row):
    path = Path(path)
    if not path.is_file() or path.stat().st_size > 1024 * 1024:
        raise ValueError('Нужен существующий live-commands.json текущего запуска до1МиБ')
    LiveSceneCommands(path).refresh()
    rows = json.loads(path.read_text(encoding='utf-8'))
    if any(item['id'] == row['id'] for item in rows):
        raise ValueError('ID уже использован; выберите новый ID')
    if len(rows) >= 128:
        raise ValueError('Очередь заполнена; нужен новый опыт')
    rows.append(row)
    pending = path.with_name('.commands-' + uuid.uuid4().hex + '.json')
    try:
        pending.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        LiveSceneCommands(pending).refresh()
        os.replace(pending, path)
    finally:
        if pending.exists():
            pending.unlink()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--entity-id', type=int, required=True)
    parser.add_argument('--state', choices=('open', 'closed'), required=True)
    parser.add_argument('--id', default=None)
    args = parser.parse_args(argv)
    try:
        row = make_command(args.entity_id, args.state, args.id or 'door-' + uuid.uuid4().hex[:12])
        enqueue(args.run / 'live-commands.json', row)
    except (ValueError, OSError) as error:
        parser.error(str(error))
    print('Добавлено: ' + row['id'] + '; диагностический 0x6f55; серверный реестр не изменён')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
