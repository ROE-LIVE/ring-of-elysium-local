"""Каталог однокомпонентных threshold1/status1 из первичного XML2022.

Стекло7690 подтверждено native380; остальные записи — ресурсные кандидаты.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET


def generate(source):
    source=Path(source);raw=source.read_bytes();text=raw.decode('utf-8-sig')
    tree=ET.fromstring(re.sub(r'\s+\[XlsProp\]="[^"]*"','',text))
    if tree.get('ObjName')!='data.world.EU_IceLand_4096.ClientTable.EntityStatusInPxScene':
        raise ValueError('Нужна EntityStatusInPxScene зимней карты4096')
    lines={int(m.group(1)):n for n,line in enumerate(text.splitlines(),1)
           for m in re.finditer(r'<mTable mID="(\d+)"',line)}
    entities=[]
    for row in tree.iter('mTable'):
        destruct=row.find('mDestructStatus');switch=row.find('mSwitcherStatus')
        if destruct is None or destruct.get('mType')!='EStatus_IRREVERSIBLE' or switch is None or switch.get('mType')!='EStatus_NONE':
            continue
        parts=[p for p in destruct.iter('mPartStatus') if p.get('mDamageThreshold') is not None]
        if len(parts)!=1 or parts[0].get('mDamageThreshold')!='1' or parts[0].get('mPartStatus')!='1':
            continue
        identifier=int(row.get('mID'))
        entities.append(dict(id=identifier,position_cm=[float(row.get('mPos'+a)) for a in 'XYZ'],
                             parts=[1],source_line=lines[identifier]))
    return dict(map=16010,interaction_radius_cm=750,
                provenance=dict(source=str(source),sha256=hashlib.sha256(raw).hexdigest(),
                                filter='IRREVERSIBLE/NONE; one part threshold1/status1',
                                validation='native380 window7690; other entities resource candidates'),
                entities=entities)


def write_catalog(path,data):
    # Одна запись на строку облегчает адресную проверку и Git diff.
    header={k:v for k,v in data.items() if k!='entities'}
    text=json.dumps(header,ensure_ascii=False,indent=2)[:-2]+',\n  "entities": [\n'
    text+=',\n'.join('    '+json.dumps(x,ensure_ascii=False,separators=(',',':')) for x in data['entities'])
    Path(path).write_text(text+'\n  ]\n}\n',encoding='utf-8')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();data=generate(args.source)
    args.output.parent.mkdir(parents=True,exist_ok=True);write_catalog(args.output,data)
    print('Ресурсных кандидатов:',len(data['entities']))


if __name__=='__main__':
    main()
