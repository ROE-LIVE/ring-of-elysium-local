"""Офлайн проверка ENTER_ROOM_RSP по локальному каталогу игровых сообщений.

Отчёт исключает идентификаторы, ключи и содержимое строк. Исходный plaintext
остаётся локально. Для построения каталога см. analyze_tgcp_captures.py.
"""
import argparse
import json
import struct
from pathlib import Path

from roe_room_2023 import decode_enter_room_response


def analyze(catalog, plaintext, output):
    base = plaintext.resolve()
    rows = []
    with catalog.open(encoding='utf-8') as source:
        for line_number, line in enumerate(source, 1):
            message = json.loads(line)
            if message['code'] != '0xdcf':
                continue
            if message['direction'] != 'server':
                raise ValueError(f'Строка {line_number}: ответ получен от клиента')
            path = (base / message['plaintext_file']).resolve()
            if not path.is_relative_to(base):
                raise ValueError(f'Строка {line_number}: plaintext вне каталога')
            raw = path.read_bytes()
            start = message['plaintext_offset']
            size = message['decoded_length']
            if start < 0 or size < 10 or start + size > len(raw):
                raise ValueError(f'Строка {line_number}: неверные границы сообщения')
            payload = raw[start + 10:start + size]
            decoded = decode_enter_room_response(payload)
            rebuilt = b''.join(
                field['value'] if field['type'] == 'raw'
                else struct.pack('>' + field['type'], field['value'])
                for field in decoded['fields'])
            if rebuilt != payload:
                raise ValueError(f'Строка {line_number}: побайтовая сверка не совпала')
            safe_fields = []
            for field in decoded['fields']:
                safe = {key: field[key] for key in ('name', 'offset', 'length', 'type')}
                if field['name'] == 'result' or field['name'].endswith(('.count', '.length')):
                    safe['value'] = field['value']
                safe_fields.append(safe)
            rows.append({'file': message['file'], 'record': message['record'],
                         'length': len(payload), 'roundtrip': True,
                         'sections': decoded['sections'], 'fields': safe_fields})
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({'responses': len(rows), 'messages': rows},
                                 ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return len(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog', required=True, type=Path)
    parser.add_argument('--plaintext', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    count = analyze(args.catalog, args.plaintext, args.output)
    print(f'Проверено ответов: {count}; отчёт: {args.output}')


if __name__ == '__main__':
    main()
