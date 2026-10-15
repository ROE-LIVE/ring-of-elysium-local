"""Запускает исследовательский сервис с компактным журналом без сырых тел."""
import hashlib
from pathlib import Path
import runpy
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'));sys.path.insert(0,str(ROOT/'server/directory'))
from listener import Capture

record=Capture.record


def compact(self,kind,data=None,**fields):
    if data is not None:
        fields.update(length=len(data),sha256=hashlib.sha256(data).hexdigest())
    return record(self,kind,**fields)


if __name__=='__main__':
    mode=sys.argv.pop(1)
    Capture.record=compact
    script=ROOT/('tools/heartbeat_probe_2022.py' if mode=='proxy' else 'server/directory/game_endpoint_probe_2022.py')
    sys.argv[0]=str(script)
    runpy.run_path(str(script),run_name='__main__')
