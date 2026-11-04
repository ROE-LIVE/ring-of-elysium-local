"""Базовая модель2022: границы пакета, отмена, сохранение и изоляция профиля."""
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from base_character_2022 import validate_head,login_head_span,patch_login_head,appearance_record
from local_cosmetics_2022 import LocalCosmetics


def head(gender=0,count=0):
    return struct.pack('>I',gender)+bytes(132)+struct.pack('>I',count)+bytes(40*count)


def login(h,name=b'Lab\0'):
    b=bytearray(41+len(name));struct.pack_into('>I',b,16,1)
    struct.pack_into('>I',b,32,len(name));b[36:36+len(name)]=name
    return bytes(b)+h+b'opaque-profile-tail'


class BaseCharacterTests(unittest.TestCase):
    def test_head_bounds_and_finite_shapes(self):
        for gender in (0,1):
            for n in (0,26,30):self.assertEqual(validate_head(head(gender,n)),head(gender,n))
        for h in (head(2),head(count=31),head()[:-1],head()+b'\0'):
            with self.assertRaises(ValueError):validate_head(h)
        bad=bytearray(head(0,1));struct.pack_into('>f',bad,144,float('nan'))
        with self.assertRaises(ValueError):validate_head(bad)

    def test_login_replaces_variable_head_without_changing_tail_or_identity(self):
        before=login(head(1,26));after=patch_login_head(before,head(0,1))
        start,end=login_head_span(after)
        self.assertEqual(after[:start],before[:start]);self.assertEqual(after[start:end],head(0,1))
        self.assertEqual(after[end:],b'opaque-profile-tail')
        bad=bytearray(before[:41]);struct.pack_into('>I',bad,32,128)
        with self.assertRaises(ValueError):login_head_span(bad)

    def test_editor_save_cancel_restore_and_profile_isolation(self):
        with tempfile.TemporaryDirectory()as d:
            root=Path(d);p=root/'catalog.json';state=root/'state.json'
            p.write_text(json.dumps(dict(owned_gun_skin_ids=[],owned_character_ids=[407],state_file=str(state))))
            a=LocalCosmetics(p);a.apply_login_profile(login(head(1,26)))
            self.assertEqual(a.handle(0x30d,b'\x77\xc0')[0],[(0x30e,bytes(4))])
            a.handle(0x73a2,struct.pack('>5I',407,0,0,0,0));a.handle(0x73ab,b'\1')
            before=state.read_bytes()
            replies,action=a.handle(0x30f,b'\0'+head(0,3),42)
            self.assertEqual(action,'base_editor_cancelled');self.assertEqual(state.read_bytes(),before)
            self.assertEqual(replies[0][1],b'\0'+bytes(4)+head(0,3)+bytes(12))
            replies,action=a.handle(0x30f,b'\1'+head(0,3),42)
            self.assertEqual(action,'base_editor_saved');self.assertEqual(replies[0],(0x73b3,bytes(17)))
            b=LocalCosmetics(p);self.assertEqual(b.base_head,head(0,3));self.assertFalse(b.avatar_applied)
            self.assertEqual(struct.unpack_from('>QIQI',dict(replies)[0x703f]),(1,3,42,1))
            self.assertTrue(b.apply_login_profile(login(head(1,26))).endswith(head(0,3)+b'opaque-profile-tail'))
            before=state.read_bytes()
            for invalid in (b'\2'+head(),b'\1'+head()[:-1],b'\1'+head()+b'\0'):
                self.assertEqual(b.handle(0x30f,invalid),([],'base_editor_invalid'))
            self.assertEqual(state.read_bytes(),before)
            p2=root/'other.json';p2.write_text(json.dumps(dict(owned_gun_skin_ids=[])))
            self.assertIsNone(LocalCosmetics(p2).base_head)

    def test_gender_switch_keeps_separate_saved_faces_and_clothes(self):
        defaults=json.loads((Path(__file__).resolve().parents[1]/'config/cosmetics.json').read_text())['base_character_defaults']
        with tempfile.TemporaryDirectory()as d:
            p=Path(d)/'catalog.json';p.write_text(json.dumps(dict(owned_gun_skin_ids=[],base_character_defaults=defaults,state_file=str(Path(d)/'state.json'))))
            a=LocalCosmetics(p);a.choose_base_gender(0)
            self.assertEqual(struct.unpack_from('>III',a.base_head),(0,1,3))
            a.handle(0x30f,b'\1'+head(0,2))
            a.choose_base_gender(1);self.assertEqual(struct.unpack_from('>II',a.base_head),(1,101))
            b=LocalCosmetics(p);b.choose_base_gender(0);self.assertEqual(b.base_head,head(0,2))
            before=(Path(d)/'state.json').read_bytes()
            for invalid in (True,2,-1,'0'):
                with self.assertRaises(ValueError):b.choose_base_gender(invalid)
            self.assertEqual((Path(d)/'state.json').read_bytes(),before)

    def test_room_head_splice_preserves_tail_and_avatar_with_variable_morph_count(self):
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server/directory'))
        from room_cosmetics_2022 import apply_room_cosmetics
        from roe_room_2023 import decode_enter_room_response
        from test_roe_room_2023 import room_fixture
        with tempfile.TemporaryDirectory()as d:
            p=Path(d)/'catalog.json';p.write_text(json.dumps(dict(owned_gun_skin_ids=[],state_file=str(Path(d)/'state.json'))))
            a=LocalCosmetics(p);a.handle(0x30f,b'\1'+head(1,26))
            raw=room_fixture(points=1);result,meta=apply_room_cosmetics(raw,p)
            section=next(x for x in decode_enter_room_response(result)['sections']if x['name']=='profile.base.m094')
            self.assertEqual(result[section['offset']:section['offset']+section['length']],head(1,26))
            self.assertEqual(meta['base_gender'],1);self.assertEqual(len(result)-len(raw),25*40)

    def test_encrypted_login_stream_handles_fragmented_profile_and_preserves_uid(self):
        from lobby_actor_uid_2022 import LobbyActorUIDStream
        from roe_team_2022 import server_message
        from roe_protocol_2022 import dt_plain
        from test_roe_protocol_2022 import KEY
        with tempfile.TemporaryDirectory()as d:
            p=Path(d)/'catalog.json';p.write_text(json.dumps(dict(owned_gun_skin_ids=[],state_file=str(Path(d)/'state.json'))))
            a=LocalCosmetics(p);a.handle(0x30f,b'\1'+head(0,2))
            stream=LobbyActorUIDStream(KEY,42,'Tester',cosmetics=a)
            wire=server_message(0x2ef,login(head(1,26)),100,KEY);result=b''
            for byte in wire:
                chunk,_=stream.feed(bytes([byte]));result+=chunk
            stream.finish();body=dt_plain(result,KEY)[10:]
            self.assertEqual(struct.unpack_from('>Q',body,4)[0],42)
            self.assertEqual(struct.unpack_from('>Q',body,20)[0],42)
            start,end=login_head_span(body);self.assertEqual(body[start:end],head(0,2))
            self.assertEqual(body[end:],b'opaque-profile-tail')

    def test_created_and_skin_appearance_use_different_record_kinds(self):
        avatar=struct.pack('>5I',407,0,0,0,0)
        created=appearance_record(42,avatar,False,head(1),{22:1000023})
        skin=appearance_record(42,avatar,True,head(1),{22:1000023})
        self.assertEqual(struct.unpack_from('>QI',created),(42,1))
        self.assertEqual(struct.unpack_from('>QI',skin),(42,2))
        self.assertEqual(created[12:152],head(1));self.assertEqual(skin[12:32],avatar)
