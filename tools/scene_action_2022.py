"""Добавить typed action в live-commands.json текущего одиночного опыта2022."""
import argparse
import json
import os
from pathlib import Path
import sys
import uuid

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server/directory'))
from live_scene_probe_2022 import LiveSceneCommands
from state_scene_actions_2022 import validate_state_action


def enqueue(path,row):
    path=Path(path)
    if not path.is_file() or path.stat().st_size>1024*1024:
        raise ValueError('Нужен существующий live-commands.json текущего запуска до1МиБ')
    # Проверяем прежнюю очередь полностью; неверный файл не перезаписываем.
    LiveSceneCommands(path).refresh()
    validate_state_action(row)
    rows=json.loads(path.read_text())
    previous=next((item for item in rows if item['id']==row['id']),None)
    if previous is not None:
        if previous!=row:raise ValueError('ID уже занят другим действием; выберите новый ID')
        return False
    if len(rows)>=128:raise ValueError('Очередь заполнена; для нового опыта нужен новый run')
    rows.append(row)
    pending=path.with_name('.commands-'+uuid.uuid4().hex+'.json')
    try:
        pending.write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        # Валидатор проверяет ID/получателя до atomic replace.
        LiveSceneCommands(pending).refresh()
        os.replace(pending,path)
    finally:
        if pending.exists():pending.unlink()
    return True


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',type=Path,required=True)
    parser.add_argument('--id',default=None)
    parser.add_argument('--recipient',default=None)
    parser.add_argument('--action',choices=('set_own_health','give_ammo','damage_npc'),required=True)
    parser.add_argument('--hp',type=int);parser.add_argument('--quantity',type=int)
    parser.add_argument('--definition',type=int);parser.add_argument('--damage',type=int)
    parser.add_argument('--npc-uid',help='UID конкретной пассивной мишени; только damage_npc')
    args=parser.parse_args(argv)
    row=dict(id=args.id or ('admin-'+uuid.uuid4().hex[:12]),action=args.action)
    for name in ('hp','quantity','definition','damage'):
        if getattr(args,name) is not None:row[name]=getattr(args,name)
    if args.recipient is not None:row['recipient_actor_uid']=args.recipient
    if args.npc_uid is not None:row['npc_uid']=args.npc_uid
    try:added=enqueue(args.run/'live-commands.json',row)
    except (ValueError,OSError) as error:parser.error(str(error))
    print(('Добавлено' if added else 'Уже в очереди')+': '+row['id']+' '+row['action'])
    print('Применение/отказ проверяется по live_state_action в game-endpoint/events.jsonl')
    return 0


if __name__=='__main__':raise SystemExit(main())
