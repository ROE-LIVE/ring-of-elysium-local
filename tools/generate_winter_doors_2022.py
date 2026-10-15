"""Извлечь обратимые двери из первичной EntityStatusInPxScene2022, без запуска игры."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET


def generate(source, bounds=None):
    source = Path(source)
    raw = source.read_bytes()
    text = raw.decode('utf-8-sig')
    # Редакторский атрибут [XlsProp] нарушает XMLsyntax, содержимое сохраняем.
    cleaned = re.sub(r'\s+\[XlsProp\]="[^"]*"', '', text)
    tree = ET.fromstring(cleaned)
    if tree.get('ObjName') != 'data.world.EU_IceLand_4096.ClientTable.EntityStatusInPxScene':
        raise ValueError('Нужна EntityStatusInPxScene зимней карты4096')
    lines = {int(m.group(1)): number
             for number, line in enumerate(text.splitlines(), 1)
             for m in re.finditer(r'<mTable mID="(\d+)"', line)}
    doors = []
    for row in tree.iter('mTable'):
        switch = row.find('mSwitcherStatus')
        if switch is None or switch.get('mType') != 'EStatus_REVERSIBLE' or switch.get('mSwitcherType') != 'ESwitcher_DOOR':
            continue
        identifier = int(row.attrib['mID'])
        xyz = [float(row.attrib['mPos' + axis]) for axis in 'XYZ']
        if bounds and not (bounds[0] <= xyz[0] <= bounds[2] and bounds[1] <= xyz[1] <= bounds[3]):
            continue
        status = int(switch.attrib['mStatus'])
        if status not in (0, 1, 2):
            continue
        doors.append(dict(id=identifier, position_cm=xyz, initial_state=status,
                          source_line=lines[identifier], name=row.attrib['mEntityFullName']))
    return dict(map=16010, interaction_radius_cm=400, visibility_radius_cm=6000,
                provenance=dict(source=str(source), sha256=hashlib.sha256(raw).hexdigest(),
                                filter='EStatus_REVERSIBLE/ESwitcher_DOOR; status0/1/2', bounds_cm=bounds), doors=doors)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--bounds-cm', type=float, nargs=4)
    args = parser.parse_args()
    if args.bounds_cm and (args.bounds_cm[0] > args.bounds_cm[2] or args.bounds_cm[1] > args.bounds_cm[3]):
        parser.error('Неверные границы XY')
    data = generate(args.source, args.bounds_cm)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('Дверей:', len(data['doors']))


if __name__ == '__main__':
    main()
