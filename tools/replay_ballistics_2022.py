"""Проверка native integrator2022 по явному JSON, без клиента и сетевых служб."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server/directory'))
from ballistics_2022 import BallisticState, trajectory

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--input',type=Path,required=True)
p.add_argument('--steps',type=int,default=100)
p.add_argument('--output',type=Path,required=True)
a=p.parse_args()
if a.output.exists():p.error('Выход уже существует; выберите новое имя')
values=json.loads(a.input.read_text(encoding='utf-8-sig'))
for name in ('position','velocity'):values[name]=tuple(values[name])
state=BallisticState(**values)
rows=[asdict(row) for row in trajectory(state,a.steps)]
a.output.write_text(json.dumps({'build':'2022-0.2.989.0-x64','source':'native140FC2430',
 'limitations':'Без разброса/collision/перехода воды/lag compensation/original hurt; не меняет обработку попаданий',
 'states':rows},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(f'Сохранено{len(rows)} точек: {a.output}')
