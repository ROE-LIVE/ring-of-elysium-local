"""Манифест одного подтверждённого камня; клиент/SFC только читаются."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'server/directory'))
from collision_mesh_2022 import CollisionMesh

EXE_SHA256 = '2dca9b1e122e21363e14eeeb2372598c773205a907ed8d2b2d54a7229ad6ba18'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--client',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True,help='Новый JSON; существующий файл не перезаписывается')
    args = parser.parse_args()
    client = args.client.resolve()
    with (client/'Europa_Client.exe').open('rb') as source:
        if hashlib.file_digest(source,'sha256').hexdigest() != EXE_SHA256:
            parser.error('Нужен корневой Europa_Client.exe2022 указанного SHA')
    descriptor = {
        'id':'iceland-demo-rock',
        'archive_file':str(client/'SFC/Scene_General_Stone.sfc'),
        'payload_offset':353907258,
        'sha256':'6c56d299625354e8c49f144e20e395325710bb7eaa96e6e621cd18d93b08934f',
        'material_id':305,
        'pose':[0.020469781011343002,-0.0725526437163353,-0.6781055331230164,
                0.7310882210731506,371766.71875,545514.5625,258530.28125],
    }
    mesh = CollisionMesh.load(descriptor,args.output.parent)
    config = {
        'scope':'Один подтверждённый объект16010; исходное пробитие/полная карта не восстановлены',
        'resource':'DATA/SCENE/GENERAL/STONE/EU_SNOWSTONE_005_SCALE40.REPX',
        'meshes':[descriptor],
    }
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x',encoding='utf-8') as output:
        output.write(json.dumps(config,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'manifest':str(args.output),'vertices':mesh.vertex_count,
                      'triangles':len(mesh.triangles),'resource_sha256':mesh.source_sha256},ensure_ascii=False))


if __name__ == '__main__':
    main()
