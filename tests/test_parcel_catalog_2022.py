"""Независимые контейнеры, conservation и отсутствие виртуальных ground-entity."""
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server/directory'))
from parcel_catalog_2022 import ParcelCatalog, ParcelCatalogState, load_parcel_fixture
from weapon_probe_2022 import LootFixture, WeaponFixture, WeaponState


class ParcelCatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        template = bytearray(100)
        struct.pack_into('>Q', template, 4, 999)
        ground = LootFixture(999, 15510, 1, (100,200,300), bytes(45), 30004, bytes(template))
        self.weapon_fixture = WeaponFixture(bytes(82), bytes(60), loot=ground,
                                            starting_equipment=(201001,200101))
        self.weapon = WeaponState(self.weapon_fixture, 42)
        self.config = {'parcels': []}
        for uid,index,x,items in [(456,200000,100,[(200001,30004,20),(200002,201004,1)]),
                                  (457,200010,2000,[(200011,200104,1)])]:
            body = bytearray(117)
            struct.pack_into('>QI',body,0,uid,501)
            struct.pack_into('>3i',body,20,x,200,300)
            name = f'{uid}.bin'
            (self.root/name).write_bytes(body)
            self.config['parcels'].append(dict(entity_file=name,parcel_id=index,
                items=[dict(item_index=i,definition=d,quantity=q) for i,d,q in items]))
        self.path = self.root/'parcels.json'
        self.save()
        self.fixture = load_parcel_fixture(self.path,self.weapon_fixture)
        self.state = ParcelCatalogState(self.fixture)

    def save(self):
        self.path.write_text(json.dumps(self.config))

    def spawn(self, n=0):
        row = self.config['parcels'][n]
        body = (self.root/row['entity_file']).read_bytes()
        self.state.register(0x654b,body)
        self.state.register(0x6571,struct.pack('>QI',struct.unpack_from('>Q',body)[0],row['parcel_id']))

    def open(self, uid=456):
        return self.state.handle(0x656f,struct.pack('>Q',uid),self.weapon)

    def pick(self, index=200001, parcel=200000, x=100):
        return self.state.handle(0x3b63,struct.pack('>IIQBHB3iB',
                                parcel,index,0,0,0,1,x,200,300,0),self.weapon)

    def test_contents_and_two_containers_are_independent(self):
        self.assertEqual(self.open()[0],[])
        self.spawn()
        packets,event = self.open()
        self.assertEqual(event['item_count'],2)
        self.assertEqual(len(packets[0][1]),92)
        self.assertEqual(struct.unpack_from('>6I',packets[0][1]),(200000,2,200001,1,30004,20))
        self.pick()
        self.assertEqual(self.weapon.reserve,26)
        self.assertEqual(self.state.containers[1].remaining,{200011:1})
        self.spawn(1); self.open(457)
        self.pick(200011,200010,2000)
        self.assertEqual(self.weapon.equipment[10],200104)
        self.assertEqual(self.open(457)[0][0][1],struct.pack('>III',200010,0,0))

    def test_equipment_transaction_preserves_discard_and_duplicate(self):
        self.spawn(); self.open()
        packets,event = self.pick(200002)
        self.assertEqual((event['definition'],self.weapon.equipment[12],self.weapon.reserve),(201004,201004,6))
        self.assertEqual(struct.unpack_from('>II',dict(packets)[0x3b64]),(200000,200002))
        dropped = [b for c,b in packets if c == 0x821]
        self.assertEqual(len(dropped),1)
        self.assertEqual(struct.unpack_from('>I',dropped[0],63)[0],201001)
        again,event = self.pick(200002)
        self.assertEqual(event['action'],'parcel_duplicate_pickup')
        self.assertNotIn(0x821,dict(again))

    def test_partial_ammunition_stays_inside_box_and_conserves_quantity(self):
        self.spawn(); self.open(); self.weapon.reserve=75
        packets,event = self.pick()
        self.assertEqual((self.weapon.reserve,event['quantity'],event['remaining']),(80,5,15))
        self.assertNotIn(0x821,dict(packets))
        self.assertNotIn(0x82b,dict(packets))
        self.assertEqual(struct.unpack_from('>I',dict(packets)[0x3b61],20)[0],15)
        self.assertEqual(self.pick()[1]['quantity'],0)
        self.weapon.reserve=60
        self.pick()
        self.assertEqual((self.weapon.reserve,self.state.containers[0].remaining[200001]),(75,0))
        self.pick()
        self.assertEqual(self.weapon.reserve,75)

    def test_two_partial_boxes_keep_remainders_and_equipment_independent(self):
        # A заполняет bag; расход двух патронов позволяет взять ровно2 изB.
        self.config['parcels'][0]['items'][0]['quantity'] = 100
        self.config['parcels'][1]['items'].insert(0, dict(
            item_index=200013, definition=30004, quantity=100))
        self.save()
        fixture = load_parcel_fixture(self.path, self.weapon_fixture)
        self.state = ParcelCatalogState(fixture)
        self.weapon.reserve = 60
        self.spawn(); self.spawn(1); self.open()
        self.assertEqual(self.pick()[1]['quantity'], 20)
        self.assertEqual(self.state.containers[0].remaining[200001], 80)
        self.pick(200002)
        self.open(457)
        blocked = self.pick(200013, 200010, 2000)[1]
        self.assertEqual((blocked['quantity'], blocked['remaining']), (0, 100))
        self.weapon.reserve -= 2
        picked = self.pick(200013, 200010, 2000)[1]
        self.assertEqual((picked['quantity'], picked['remaining']), (2, 98))
        self.pick(200011, 200010, 2000)
        self.assertEqual(self.weapon.equipment[10], 200104)
        self.assertEqual(self.weapon.equipment[12], 201004)
        for uid, index, quantity in [(456, 200001, 80), (457, 200013, 98)]:
            body = self.open(uid)[0][0][1]
            self.assertEqual(struct.unpack_from('>4I', body, 8),
                             (index, 1, 30004, quantity))
        for _ in range(2):
            event = self.pick(200013, 200010, 2000)[1]
            self.assertEqual((event['quantity'], event['remaining']), (0, 98))
        duplicate, event = self.pick(200011, 200010, 2000)
        self.assertEqual(event['action'], 'parcel_duplicate_pickup')
        self.assertNotIn(0x821, dict(duplicate))
        self.assertEqual(self.weapon.reserve, 80)
        fresh = ParcelCatalogState(fixture)
        self.assertEqual(fresh.containers[0].remaining[200001], 100)
        self.assertEqual(fresh.containers[1].remaining[200013], 100)

    def test_gate_distance_unknown_and_removal_do_not_mutate_inventory(self):
        self.spawn()
        self.assertEqual(self.pick()[0],[])
        self.open()
        for args in [(200001,200000,850),(200011,200000,100),(200001,200010,100)]:
            self.assertEqual(self.pick(*args)[0],[])
        self.assertEqual(self.open(999)[1]['action'],'parcel_unknown_container')
        self.state.register(0x654c,struct.pack('>Q',456))
        self.assertEqual(self.pick()[0],[])
        self.assertEqual(self.weapon.reserve,6)
        self.assertFalse(ParcelCatalogState(self.fixture).containers[0].opened)

    def test_loader_rejects_collisions_unsupported_and_bool_values(self):
        item = self.config['parcels'][0]['items'][0]
        for key,value in [('item_index',15510),('item_index',True),('definition',10402),('quantity',True)]:
            old=item[key];item[key]=value;self.save()
            with self.assertRaises(ValueError):
                ParcelCatalog.load(self.path,self.weapon_fixture)
            item[key]=old
        self.config['parcels'][1]['parcel_id']=200001;self.save()
        with self.assertRaises(ValueError):
            ParcelCatalog.load(self.path,self.weapon_fixture)



class NativeParcelMotionTests(unittest.TestCase):
    setUp = ParcelCatalogTests.setUp
    save = ParcelCatalogTests.save
    spawn = ParcelCatalogTests.spawn
    open = ParcelCatalogTests.open
    pick = ParcelCatalogTests.pick
    def enable_motion(self):
        self.config['parcels'][0]['native_motion'] = True
        self.save()
        self.fixture = load_parcel_fixture(self.path, self.weapon_fixture)
        self.state = ParcelCatalogState(self.fixture)

    def motion(self, uid=456, tick=100, position=(2000, 200, 300)):
        body = bytearray(73)
        struct.pack_into('>QI', body, 0, uid, tick)
        struct.pack_into('>3i', body, 13, *position)
        return self.state.observe_motion(bytes(body), self.weapon)

    def test_motion_is_opt_in_known_uid_and_spawned(self):
        self.spawn()
        self.assertIsNone(self.motion())
        self.enable_motion()
        self.assertEqual(self.motion()['reason'], 'not_spawned')
        self.spawn()
        self.assertIsNone(self.motion(uid=9999))
        self.assertEqual(self.motion()['action'], 'parcel_native_motion')

    def test_pickup_uses_current_native_position(self):
        self.enable_motion(); self.spawn(); self.motion()
        self.open()
        self.assertEqual(self.pick(x=100)[1]['action'], 'parcel_pick_rejected')
        self.assertEqual(self.pick(x=2000)[1]['action'], 'parcel_pickup')
        self.assertEqual(self.weapon.loot_registry[200001].position, (2000,200,300))

    def test_stale_ticks_speed_and_envelope_leave_position_unchanged(self):
        self.enable_motion(); self.spawn(); self.motion()
        for tick, position, reason in [(100,(2100,200,300),'stale_tick'),
                                      (99,(2100,200,300),'stale_tick'),
                                      (101,(10000,200,300),'speed'),
                                      (102,(60000,200,300),'outside_envelope')]:
            self.assertEqual(self.motion(tick=tick, position=position)['reason'], reason)
            self.assertEqual(self.state.containers[0].position, (2000,200,300))

    def test_tick_wrap_and_registered_partial_stack_follow_motion(self):
        self.enable_motion(); self.spawn(); self.motion(tick=0xfffffffe)
        self.open(); self.weapon.reserve=75; self.pick(x=2000)
        self.assertEqual(self.motion(tick=1,position=(2100,200,300))['action'], 'parcel_native_motion')
        self.assertEqual(self.weapon.loot_registry[200001].quantity,15)
        self.assertEqual(self.weapon.loot_registry[200001].position,(2100,200,300))

    def test_native_motion_setting_is_strict_bool(self):
        self.config['parcels'][0]['native_motion']=1; self.save()
        with self.assertRaises(ValueError):load_parcel_fixture(self.path,self.weapon_fixture)

if __name__ == '__main__':
    unittest.main()
