"""Разные ITEM_DATA union и три несовместимых формата ссылки2022."""
from pathlib import Path
import struct
import sys
import unittest
import tempfile
import json
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server/directory'))
from inventory_codec_2022 import (decode_item, decode_snapshot, decode_delta,
    decode_discard, encode_snapshot, encode_delta)
from weapon_probe_2022 import WeaponFixture, WeaponState, LootFixture, medical_record, equipment_record
from attachment_probe_2022 import AttachmentInstance, attachment_record, gun_attachment_record

class InventoryCodecTests(unittest.TestCase):
    def records(self):
        gun = bytearray(82); gun[:4] = bytes((1,1,1,0))
        struct.pack_into('>IQ',gun,4,10402,101); struct.pack_into('>H',gun,80,1)
        ammo = bytearray(60); ammo[:4] = bytes((2,1,2,0))
        struct.pack_into('>IQ',ammo,4,30004,102); struct.pack_into('>H',ammo,58,17)
        part = AttachmentInstance(40403,103)
        return [bytes(ammo),medical_record(70001,5),bytes(gun),
                attachment_record(bytes(gun),20,part),equipment_record(bytes(gun),201001,1800),
                gun_attachment_record(bytes(gun),{3:part})]

    def test_mixed_snapshot_keeps_variable_union_boundaries_and_fields(self):
        records=self.records(); records[-1]=bytes((1,2))+records[-1][2:]
        message=decode_snapshot(encode_snapshot(records,42))
        self.assertEqual((message.actor_uid,message.own),(42,1))
        self.assertEqual([(e.container,e.slot,e.item.definition,e.item.quantity) for e in message.entries],
            [(2,1,30004,17),(2,3,70001,5),(1,1,10402,1),(2,20,40403,1),(1,12,201001,1),(1,2,10402,1)])
        self.assertEqual([len(e.item.raw) for e in message.entries],[58,78,80,80,80,92])
        self.assertEqual(message.entries[-1].item.part_count,1)
        self.assertEqual([e.item.raw for e in message.entries],[r[2:] for r in records])

    def test_delta_and_discard_use_full_be16_slot_with_different_order(self):
        item=self.records()[1][2:]
        for slot in (1,255,256,0x1234,65535):
            message=decode_delta(encode_delta(2,slot,item,42,False))
            self.assertEqual((message.entries[0].container,message.entries[0].slot),(2,slot))
            self.assertEqual((message.actor_uid,message.own),(42,0))
            request=decode_discard(struct.pack('>BBHHQB',2,2,slot,12,0x123456789,1))
            self.assertEqual((request.slot,request.quantity,request.extension),(slot,12,0x123456789))

    def test_native_optional_name_and_parts_bounds(self):
        item=bytearray(self.records()[2][2:]);item[22]=1
        named=bytes(item[:23])+struct.pack('>I',4)+b'abc\0'+bytes(item[23:])
        self.assertEqual(decode_item(named).quantity,1)
        for name in (b'abcX',b'a\0b\0'):
            with self.assertRaises(ValueError):decode_item(bytes(item[:23])+struct.pack('>I',4)+name+bytes(item[23:]))
        malformed=bytearray(self.records()[-1][2:]);struct.pack_into('>I',malformed,62,9)
        with self.assertRaises(ValueError):decode_item(malformed)
        with self.assertRaises(ValueError):decode_snapshot(struct.pack('>I',398))

    def test_all_snapshot_truncations_and_trailing_bytes_fail(self):
        data=encode_snapshot(self.records(),42)
        for length in range(len(data)):
            with self.subTest(length=length),self.assertRaises(ValueError):decode_snapshot(data[:length])
        with self.assertRaises(ValueError):decode_snapshot(data+b'\0')
        with self.assertRaises(ValueError):decode_delta(encode_delta(2,3,self.records()[1][2:],42)+b'\0')

    def test_empty_delta_and_unknown_union_have_explicit_boundaries(self):
        message=decode_delta(encode_delta(2,256,bytes(37),42))
        self.assertEqual((message.entries[0].item.item_type,message.entries[0].item.quantity),(0,0))
        unknown=bytearray(self.records()[0][2:]);unknown[0]=3
        with self.assertRaises(ValueError):decode_item(unknown)
        unknown[0]=2;unknown[30]=5
        with self.assertRaises(ValueError):decode_item(unknown)

    def test_category5_native_string_extension_and_mixed_boundaries(self):
        base=bytearray(self.records()[0][2:]);base[30]=5
        struct.pack_into('>I',base,2,50001)
        def item(name,length=None):
            return bytes(base[:52])+struct.pack('>QI',0,len(name) if length is None else length)+name+bytes(base[52:])
        for name in (b'\0',b'test\0',b'a'*127+b'\0'):
            raw=item(name);parsed=decode_item(raw)
            self.assertEqual((parsed.definition,parsed.category,parsed.quantity),(50001,5,17))
            self.assertEqual(len(parsed.raw),70+len(name))
            message=decode_snapshot(encode_snapshot([bytes((2,11))+raw,self.records()[1]],42))
            self.assertEqual([e.item.definition for e in message.entries],[50001,70001])
            for length in range(len(raw)):
                with self.subTest(length=length),self.assertRaises(ValueError):decode_item(raw[:length])
        for name,length in ((b'',0),(b'a'*128+b'\0',129),(b'x',1),(b'a\0b\0',4)):
            with self.assertRaises(ValueError):decode_item(item(name,length))

    def test_loot_fixture_loads_explicit_durability_and_rejects_invalid_presets(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);body=bytearray(100)
            struct.pack_into('>IQI',body,0,30201002,999,13)
            struct.pack_into('>I',body,46,1);body[62]=2
            struct.pack_into('>III',body,63,200102,1,15510)
            ack=bytearray(45);ack[12]=1
            (root/'entity.bin').write_bytes(body);(root/'ack.bin').write_bytes(ack)
            config=dict(entity_file='entity.bin',acknowledgement_file='ack.bin',durability=370)
            self.assertEqual(LootFixture.load(root,config).durability,370)
            self.assertIsNone(LootFixture.load(root,{k:v for k,v in config.items() if k!='durability'}).durability)
            for invalid in (-1,1501,True,1.5,'370'):
                with self.assertRaises(ValueError):LootFixture.load(root,{**config,'durability':invalid})
            struct.pack_into('>I',body,63,30004);(root/'entity.bin').write_bytes(body)
            with self.assertRaises(ValueError):LootFixture.load(root,config)

    def test_unmapped_high_discard_slot_does_not_alias_low_byte_or_mutate(self):
        body=bytearray(100)
        struct.pack_into('>IQI',body,0,30201002,999,13)
        struct.pack_into('>3i',body,29,100,200,300)
        struct.pack_into('>I',body,46,1);body[62]=2
        struct.pack_into('>III',body,63,30004,20,15510)
        loot=LootFixture(999,15510,20,(100,200,300),bytes(45),30004,bytes(body))
        state=WeaponState(WeaponFixture(bytes(82),bytes(60),loot=loot),42)
        state.update_position((100,200,300));state.reserve=17
        before=(state.reserve,state.drop_counter,dict(state.guns),dict(state.equipment))
        for slot in (256,257,0x1201,65535):
            replies,event=state.handle(0x3e80,struct.pack('>BBHHQB',2,2,slot,1,0,1))
            self.assertEqual(replies,[]);self.assertEqual(event['action'],'rejected')
            self.assertEqual((state.reserve,state.drop_counter,dict(state.guns),dict(state.equipment)),before)
        replies,event=state.handle(0x3e80,struct.pack('>BBHHQB',9,2,1,1,0,1))
        self.assertEqual(event['action'],'rejected')

if __name__=='__main__':unittest.main()
