"""Диагностический LOS: выбранные публичные поля геометрии, без игровых бинарников.

XYZ взяты из подтверждённого hit-own-9091; остальные поля fixture синтетические.
"""
import struct
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server/directory'))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from actor_probe_2022 import ActorFixture, ActorState

class RaycastTests(unittest.TestCase):
    def setUp(self):
        from dataclasses import replace
        self.fixture = ActorFixture(0x2040000123460, b'\x01'+bytes(22), struct.pack('>II',3,1)+bytes(1508), bytes(40), (366000,544000,259060), ((366000,544000,259060),), 0, 1000, 50, collision_boxes=())
        self.hit = bytearray(106)
        struct.pack_into('>Q', self.hit, 4, self.fixture.uid)
        struct.pack_into('>3f', self.hit, 25, 365073.03125,543901.125,259244.765625)
        struct.pack_into('>3i', self.hit, 37, *self.fixture.position)
        struct.pack_into('>3f', self.hit, 50, 366009.375,543997.375,259143.109375)
        struct.pack_into('>I', self.hit, 88, 4)
        struct.pack_into('>I', self.hit, 96, 14275)
        self.fire = struct.pack('>6fIBIIfII', 365073, 543901, 259245,
                                366062, 544013, 259155, 4, 0, 14275, 7, 480, 64, 0)

    def actor(self, boxes=()):
        from dataclasses import replace
        actor = ActorState(replace(self.fixture, collision_boxes=boxes))
        actor.begin(100)
        actor.note_fire(self.fire, {'action': 'fire'})
        return actor

    def test_weapon_telemetry_uses_accepted_fire_not_next_selected_weapon(self):
        actor = self.actor()
        actor.note_fire(self.fire, {'action':'fire','gun_definition':10201})
        other = bytearray(self.fire);struct.pack_into('>I',other,24,5)
        actor.note_fire(other, {'action':'fire','gun_definition':10402})
        data = bytearray(self.hit)
        struct.pack_into('>I',data,78,164);data[83]=1
        _, event = actor.hit(data)
        self.assertEqual((event['gun_definition'],event['hit_field78'],event['hit_flag83']),(10201,164,1))

    def test_primary_open_hit_and_wall_rejection_preserve_hp_armor_and_identity(self):
        actor = self.actor()
        self.assertEqual(actor.hit(self.hit)[1]['damage'], 50)
        wall = (((365500, 543000, 258000), (365600, 545000, 260000)),)
        actor = self.actor(wall)
        actor.armor_durability = 20
        packets, event = actor.hit(self.hit)
        self.assertEqual((packets, event['reason'], event['blocking_box']), ([], 'line_of_sight', 0))
        self.assertEqual((actor.hp, actor.armor_durability, actor.hits), (1000, 20, set()))
        # Отказ не помечает hit принятым и не отнимает HP/прочность.
        self.assertEqual(actor.hit(self.hit)[1]['reason'], 'line_of_sight')

    def test_box_behind_target_and_parallel_side_do_not_block(self):
        boxes = (((366500, 543000, 258000), (366600, 545000, 260000)),
                 ((365500, 545000, 258000), (365600, 546000, 260000)))
        self.assertEqual(self.actor(boxes).hit(self.hit)[1]['action'], 'hit_damage')

    def test_origin_impact_nonfinite_and_direction_rejected_before_damage(self):
        cases = [(25, (0,0,0), 'shot_origin'), (50, (0,0,0), 'impact_position'),
                 (50, (float('nan'), 0, 0), 'ray_nonfinite')]
        for offset, vector, reason in cases:
            with self.subTest(reason=reason):
                data = bytearray(self.hit)
                struct.pack_into('>3f', data, offset, *vector)
                actor = self.actor()
                self.assertEqual(actor.hit(data)[1]['reason'], reason)
                self.assertEqual((actor.hp, actor.hits), (1000, set()))
        for aim in [(364000,543901,259245), (365073,544901,259245),
                    (365073,543901,259245)]:
            with self.subTest(aim=aim):
                data = bytearray(self.fire)
                struct.pack_into('>3f', data, 12, *aim)
                actor = self.actor()
                actor.note_fire(data, {'action': 'fire'})
                self.assertEqual(actor.hit(self.hit)[1]['reason'], 'shot_direction')

    def test_range_rejects_even_if_ray_points_to_target(self):
        data = bytearray(self.fire)
        struct.pack_into('>3f', data, 0, 350000,543901,259245)
        actor = self.actor()
        actor.note_fire(data, {'action': 'fire'})
        self.assertEqual(actor.hit(self.hit)[1]['reason'], 'range')
        self.assertEqual(actor.hp,1000)

    def test_segment_boundaries_parallel_start_inside_and_endpoint(self):
        from actor_probe_2022 import segment_box_entry
        lower, upper = (2,-1,-1), (3,1,1)
        self.assertAlmostEqual(segment_box_entry((0,0,0),(4,0,0),lower,upper), .5)
        self.assertIsNone(segment_box_entry((0,2,0),(4,2,0),lower,upper))
        self.assertEqual(segment_box_entry((2.5,0,0),(4,0,0),lower,upper), 0)
        self.assertEqual(segment_box_entry((0,1,0),(2,1,0),lower,upper), 1)
        self.assertIsNone(segment_box_entry((0,0,0),(1,0,0),lower,upper))

    def test_fixture_rejects_invalid_collision_boxes_and_enables_empty_list(self):
        import json
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            config = {'uid':hex(self.fixture.uid), 'waypoints':[list(self.fixture.position)],
                      'speed_cm_seconds':0, 'hp':1000, 'pellet_damage':50}
            for field, data in [('listing_file',self.fixture.listing),
                                ('profile_file',self.fixture.profile),
                                ('movement_file',self.fixture.movement)]:
                file = folder/(field+'.bin');file.write_bytes(data)
                config[field] = str(file)
            path = folder/'actor.json'
            for boxes in [None, {}, [[[0,0,0],[0,1,1]]],
                          [[[0,0,0],[float('inf'),1,1]]], [[True,[1,2,3]]],
                          [[[0,0],[1,2,3]]], [[[0,0,0],[1,1,1]]]*65]:
                config['collision_boxes'] = boxes
                path.write_text(json.dumps(config))
                with self.subTest(boxes=repr(boxes)[:50]), self.assertRaises(ValueError):
                    ActorFixture.load(path)
            config['collision_boxes'] = []
            path.write_text(json.dumps(config))
            self.assertEqual(ActorFixture.load(path).collision_boxes, ())


    def test_opt_in_terrain_blocks_forged_below_surface_hit_without_mutation(self):
        from dataclasses import replace
        import tempfile
        from probe_iceland_heightfield_2022 import HeightField
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'analytic-plane'
            path.write_bytes(struct.pack('<hBB',0,2,2)*4)
            # Аналитическая преграда между originZ245 и impactZ155;
            # это тестовая поверхность, не извлечённая карта игры.
            terrain=HeightField(path,2,2,0,365000,543000,259200,2000,1)
            actor=ActorState(replace(self.fixture,collision_heightfield=terrain,
                                    armor_definition=201001,armor_durability=30))
            actor.begin(100);actor.note_fire(self.fire,{'action':'fire'})
            packets,event=actor.hit(self.hit)
            self.assertEqual((packets,event['reason']),([], 'line_of_sight'))
            self.assertTrue(event['terrain_checked'])
            self.assertEqual(event['blocking_terrain']['position'][2],259200)
            self.assertEqual((actor.hp,actor.armor_durability,actor.hits),(1000,30,set()))
            # Исходный профиль без опции принимает тот же packet.
            self.assertEqual(self.actor().hit(self.hit)[1]['action'],'hit_damage')

    def test_terrain_clear_and_missing_resource_do_not_silently_share_a_result(self):
        from dataclasses import replace
        import tempfile
        from probe_iceland_heightfield_2022 import HeightField
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'analytic-plane';path.write_bytes(struct.pack('<hBB',0,2,2)*4)
            terrain=HeightField(path,2,2,0,365000,543000,258000,2000,1)
            actor=ActorState(replace(self.fixture,collision_heightfield=terrain))
            actor.begin(100);actor.note_fire(self.fire,{'action':'fire'})
            self.assertEqual(actor.hit(self.hit)[1]['action'],'hit_damage')
            path.unlink()
            other=ActorState(replace(self.fixture,collision_heightfield=terrain))
            other.begin(100);other.note_fire(self.fire,{'action':'fire'})
            packets,event=other.hit(self.hit)
            self.assertEqual((packets,event['reason'],other.hp),([], 'terrain_geometry_unavailable',1000))


    def test_segment_wholly_below_terrain_does_not_count_as_clear_los(self):
        from dataclasses import replace
        import tempfile
        from probe_iceland_heightfield_2022 import HeightField
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'analytic-plane';path.write_bytes(struct.pack('<hBB',0,2,2)*4)
            terrain=HeightField(path,2,2,0,365000,543000,260000,2000,1)
            actor=ActorState(replace(self.fixture,collision_heightfield=terrain))
            actor.begin(100);actor.note_fire(self.fire,{'action':'fire'})
            packets,event=actor.hit(self.hit)
            self.assertEqual((packets,event['reason'],actor.hp,actor.hits),
                             ([], 'terrain_origin_below_surface',1000,set()))


if __name__ == '__main__': unittest.main()
