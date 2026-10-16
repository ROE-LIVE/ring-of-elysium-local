"""Выдача по близости, частичный pickup и сохранение состояния между секторами."""
import json
from dataclasses import replace
from pathlib import Path
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server/directory'))
from loot_catalog_2022 import LootCatalog, LootCatalogState, record_catalog_summary
from weapon_probe_2022 import LootFixture, WeaponFixture, WeaponState


class CatalogTests(unittest.TestCase):
    def test_summary_uses_validated_snapshot_and_preserves_launch_fields(self):
        import hashlib
        _, state = self.fixture(count=2)
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            snapshot = run / 'catalog.json'
            snapshot.write_bytes(b'{"checked_snapshot":true}')
            record_catalog_summary(run, snapshot, state.catalog)
            self.assertFalse((run / 'launch-summary.json').exists())
            (run / 'launch-summary.json').write_text('{"build":"2022-test","kit":"glider"}')
            record_catalog_summary(run, snapshot, state.catalog)
            summary = json.loads((run / 'launch-summary.json').read_text())
            self.assertEqual((summary['build'], summary['kit']), ('2022-test', 'glider'))
            self.assertEqual(summary['loot_catalog_sha256'], hashlib.sha256(snapshot.read_bytes()).hexdigest())
            self.assertEqual(summary['loot_catalog_items'], 2)
            self.assertEqual(summary['loot_catalog_bounds_cm'], [0, 0, 0, 10, 0, 0])
            self.assertNotIn(str(snapshot), json.dumps(summary))

    def fixture(self, quantity=10, count=1, batch=16):
        template = bytes(100)
        fixed = LootFixture(1, 1, 1, (0, 0, 0), bytes(45), 30004, template)
        weapon = WeaponState(WeaponFixture(bytes(82), bytes(60), loot=fixed), 42)
        rows = [dict(index=100 + n, entity_uid=1000 + n,
                     item_id=30004, quantity=quantity, position=[n * 10, 0, 0])
                for n in range(count)]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'catalog.json'
            path.write_text(json.dumps(dict(radius_cm=100, visible_limit=128,
                                            batch_limit=batch, entities=rows)))
            catalog = LootCatalog.load(path, template)
        return weapon, LootCatalogState(catalog, weapon)

    def request(self, index=100):
        return struct.pack('>IIQBHB3iB', index, 0, 0, 0, 0, 1, 0, 0, 0, 0)

    def test_first_position_outside_catalog_reports_empty_visibility_once(self):
        weapon, state = self.fixture()
        self.assertEqual(state.poll(), ([], []))
        weapon.update_position((1000, 2000, 3000))
        packets, events = state.poll()
        self.assertEqual(packets, [])
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['position'], [1000, 2000, 3000])
        self.assertEqual(events[0]['spawned_indexes'], [])
        self.assertEqual((events[0]['catalog_total'], events[0]['visible']), (1, 0))
        self.assertEqual(state.poll(), ([], []))
        weapon.update_position((0, 0, 0))
        packets, events = state.poll()
        self.assertEqual([code for code, _ in packets], [0x821])
        self.assertEqual(events[0]['spawned_indexes'], [100])
        self.assertEqual(events[0]['position'], [0, 0, 0])

    def test_bounded_batches_and_explicit_position_before_visibility(self):
        weapon, state = self.fixture(count=8, batch=3)
        self.assertEqual(state.poll(), ([], []))
        weapon.update_position((0, 0, 0))
        self.assertEqual(len(state.poll()[0]), 3)
        self.assertEqual(len(state.poll()[0]), 3)
        self.assertEqual(len(state.poll()[0]), 2)
        self.assertEqual(state.poll(), ([], []))
        weapon.update_position((2000, 0, 0))
        responses, _ = state.poll()
        self.assertEqual([code for code, _ in responses], [0x82b] * 3)
        self.assertEqual(len(state.visible), 5)

    def test_collected_item_never_respawns_and_duplicate_does_not_create_ammunition(self):
        weapon, state = self.fixture()
        weapon.update_position((0, 0, 0))
        state.poll()
        _, event = weapon.handle(0x3b63, self.request())
        self.assertEqual((event['action'], weapon.reserve), ('pickup', 16))
        self.assertEqual(weapon.handle(0x3b63,self.request())[1]['action'],'duplicate_pickup')
        self.assertEqual(state.poll()[0], [])
        self.assertNotIn(1000, weapon.available_loot)
        weapon.update_position((1000, 0, 0));state.poll()
        weapon.update_position((0, 0, 0));state.poll()
        self.assertEqual(state.visible, set())
        _, event = weapon.handle(0x3b63, self.request())
        # После удаления из AOI предмет уже недоступен и не возвращается.
        self.assertEqual((event['action'], event['reason']), ('rejected','pickup_fixture_or_distance'))
        self.assertEqual(event['failed_checks'], ['available'])
        self.assertEqual(weapon.reserve, 16)

    def test_partial_stack_survives_unload_and_reentry(self):
        weapon, state = self.fixture(quantity=90)
        weapon.update_position((0, 0, 0));state.poll()
        _, event = weapon.handle(0x3b63, self.request())
        self.assertEqual((event['quantity'], event['remaining'], weapon.reserve), (74, 16, 80))
        weapon.update_position((1000, 0, 0));state.poll()
        self.assertNotIn(1000, weapon.available_loot)
        weapon.update_position((0, 0, 0))
        responses, _ = state.poll()
        self.assertEqual(struct.unpack_from('>I', responses[0][1], 67)[0], 16)
        self.assertEqual(weapon.loot_registry[100].quantity, 16)

    def test_invalid_duplicates_and_unsupported_items_are_rejected(self):
        row = dict(index=100, entity_uid=1000, item_id=30004, quantity=10, position=[0, 0, 0])
        for rows in ([row, row], [dict(row, item_id=999)], [dict(row, index=True)],
                     [dict(row, quantity=101)], [dict(row, position=[0, 0, float('nan')])]):
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'catalog.json';path.write_text(json.dumps(dict(entities=rows)))
                with self.assertRaises(ValueError):
                    LootCatalog.load(path, bytes(100))

    def test_second_ammunition_weapon_and_bounded_armor_durability(self):
        row = dict(index=100, entity_uid=1000, item_id=30001, quantity=100,
                   position=[0, 0, 0])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'catalog.json'
            for definition, quantity, durability in ((30001, 100, None), (10201, 1, None),
                                                      (201004, 1, 500), (200104, 1, 0)):
                entry = dict(row, item_id=definition, quantity=quantity)
                if durability is not None:
                    entry['durability'] = durability
                path.write_text(json.dumps(dict(entities=[entry])))
                item = LootCatalog.load(path, bytes(100)).items[0]
                self.assertEqual((item.definition, item.quantity, item.durability),
                                 (definition, quantity, durability))
            for entry in (dict(row, durability=1), dict(row, item_id=10201, quantity=2),
                          dict(row, item_id=201004, quantity=1, durability=3001),
                          dict(row, item_id=201004, quantity=1, durability=-1),
                          dict(row, item_id=201004, quantity=1, durability=True)):
                path.write_text(json.dumps(dict(entities=[entry])))
                with self.assertRaises(ValueError):
                    LootCatalog.load(path, bytes(100))

    def test_catalog_attachment_pickup_duplicate_and_discard_preserve_instance(self):
        weapon, _ = self.fixture()
        rows = [dict(index=200+n, entity_uid=2000+n, item_id=definition,
                     quantity=1, position=[0, 0, 0])
                for n, definition in enumerate((40103, 40305, 40101, 40403))]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'catalog.json'
            path.write_text(json.dumps(dict(entities=rows)))
            state = LootCatalogState(LootCatalog.load(path, bytes(100)), weapon)
        weapon.update_position((0, 0, 0))
        self.assertEqual([code for code, _ in state.poll()[0]], [0x821]*4)
        for row in rows:
            _, event = weapon.handle(0x3b63, self.request(row['index']))
            self.assertEqual(event['action'], 'pickup')
            _, duplicate = weapon.handle(0x3b63, self.request(row['index']))
            self.assertEqual(duplicate['action'], 'duplicate_pickup')
        self.assertEqual(len(weapon.attachments), 4)
        slot = min(weapon.attachments)
        instance = weapon.attachments[slot]
        discard = struct.pack('>BBHHQB', 2, 2, slot, 1, 0, 1)
        _, event = weapon.handle(0x3e80, discard)
        self.assertEqual(event['action'], 'discard')
        index = event['index']
        _, event = weapon.handle(0x3b63, self.request(index))
        self.assertEqual(event['action'], 'pickup')
        self.assertEqual(weapon.attachments[slot], instance)
        self.assertEqual(len(weapon.attachments), 4)

    def test_registry_conflicts_rejected_and_sessions_do_not_share_pickup(self):
        first, a = self.fixture();second, b = self.fixture()
        first.update_position((0, 0, 0));a.poll();first.handle(0x3b63, self.request())
        second.update_position((0, 0, 0));b.poll()
        self.assertEqual(b.visible, {100})
        self.assertEqual(second.reserve, 6)
        with self.assertRaises(ValueError):
            a.catalog.validate_fixture(WeaponFixture(bytes(82), bytes(60), loot=a.catalog.items[0]))

    def test_visibility_limit_replacement_uses_one_packet_and_nearest_remaining_items(self):
        old_weapon, old_state = self.fixture(count=6, batch=1)
        weapon=WeaponState(old_weapon.fixture,42)
        state=LootCatalogState(replace(old_state.catalog,visible_limit=2),weapon)
        weapon.update_position((0,0,0))
        for _ in range(4):
            packets,events=state.poll()
            self.assertLessEqual(len(packets),1)
            self.assertLessEqual(len(state.visible),2)
        self.assertEqual(state.visible,{100,101})
        weapon.update_position((50,0,0))
        transitions=[]
        for _ in range(4):
            packets,events=state.poll();transitions.extend(code for code,_ in packets)
            self.assertLessEqual(len(packets),1)
            self.assertLessEqual(len(state.visible),2)
        self.assertEqual(transitions,[0x82b,0x82b,0x821,0x821])
        self.assertEqual(state.visible,{104,105})
        self.assertNotIn(1000,weapon.available_loot)
        self.assertNotIn(1001,weapon.available_loot)
        self.assertEqual(weapon.reserve,6)
