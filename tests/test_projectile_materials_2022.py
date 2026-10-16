"""Контроли энергии по native-данным и консервативный отказ геометрии/hit."""
from dataclasses import replace
from pathlib import Path
import struct
import sys
import tempfile
import json
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server/directory'))
from actor_probe_2022 import ActorFixture, ActorState
from collision_mesh_2022 import CollisionMesh, Node
from projectile_materials_2022 import energy_after, evaluate_rock


def slab(thickness=10, material=305, duplicate=False):
    triangles = (((20, -100, -100), (20, 0, 100), (20, 100, -100)),
                 ((20+thickness, -100, -100), (20+thickness, 100, -100),
                  (20+thickness, 0, 100)))
    if duplicate:
        triangles += (triangles[0],)
    node = Node((20, -100, -100), (20+thickness, 100, 100), (), tuple(range(len(triangles))))
    return CollisionMesh('own-slab', triangles, material, node, '0'*64, 6)


class MaterialTests(unittest.TestCase):
    def test_loader_restricts_policy_to_boolean_and_one_known_mesh(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'listing.bin').write_bytes(b'\1' + bytes(22))
            (root / 'profile.bin').write_bytes(struct.pack('>II', 3, 1) + bytes(1508))
            (root / 'movement.bin').write_bytes(bytes(40))
            config = dict(uid='900', listing_file='listing.bin', profile_file='profile.bin',
                          movement_file='movement.bin', waypoints=[[100, 0, 0]],
                          speed_cm_seconds=0, hp=1000, pellet_damage=100,
                          collision_mesh_file='selected.json', material_penetration=True)
            path = root / 'actor.json'
            path.write_text(json.dumps(config))
            with patch('actor_probe_2022.load_collision_meshes', return_value=(slab(),)):
                self.assertTrue(ActorFixture.load(path).material_penetration)
            for value, meshes in ((1, (slab(),)), (True, ()),
                                  (True, (slab(), slab())), (True, (slab(material=999),))):
                path.write_text(json.dumps(dict(config, material_penetration=value)))
                with patch('actor_probe_2022.load_collision_meshes', return_value=meshes):
                    with self.assertRaises(ValueError):
                        ActorFixture.load(path)

    def test_known_native_energy_cases(self):
        # Native012/017, а не ожидаемые значения, посчитанные этой функцией.
        for energy, power, thickness, expected in ((40, 1.5, 90.16392, -99.740753),
                (47, 2.5, 70.25916, -41.365906),
                (47, 2.5, 12.452458420052043, 27.254543918095294)):
            self.assertAlmostEqual(energy_after(energy, power, thickness), expected, delta=.001)

    def test_thin_rock_passes_thick_stops_and_unknown_profiles_fail(self):
        reason, event = evaluate_rock(slab(10), (0, 0, 0), (100, 0, 0), 10202)
        self.assertIsNone(reason)
        self.assertEqual(event['thickness_cm'], 10)
        self.assertGreater(event['energy_after'], 1)
        self.assertEqual(evaluate_rock(slab(70), (0, 0, 0), (100, 0, 0), 10202)[0], 'penetration_energy')
        self.assertEqual(evaluate_rock(slab(), (0, 0, 0), (100, 0, 0), 20002)[0], 'penetration_weapon_unsupported')
        self.assertEqual(evaluate_rock(slab(material=999), (0, 0, 0), (100, 0, 0), 10202)[0], 'penetration_material_unsupported')

    def test_same_boundary_is_deduplicated_and_inside_open_or_flipped_rejected(self):
        mesh = slab(10, duplicate=True)
        self.assertEqual(len(mesh.boundary_hits((0, 0, 0), (100, 0, 0))), 2)
        self.assertIsNone(evaluate_rock(mesh, (0, 0, 0), (100, 0, 0), 10202)[0])
        self.assertEqual(evaluate_rock(mesh, (25, 0, 0), (100, 0, 0), 10202)[0], 'penetration_boundaries_unverified')
        flipped = replace(mesh, triangles=tuple(tuple(reversed(t)) for t in mesh.triangles))
        self.assertEqual(evaluate_rock(flipped, (0, 0, 0), (100, 0, 0), 10202)[0], 'penetration_winding_unverified')
        self.assertEqual(evaluate_rock(mesh, (0, 500, 0), (100, 500, 0), 20002), (None, {}))

    def test_nonfinite_or_invalid_energy_inputs_rejected(self):
        for values in ((float('nan'), 1, 1), (1, 0, 1), (-1, 1, 1), (1, 1, -1), (True, 1, 1)):
            with self.assertRaises(ValueError):
                energy_after(*values)

    def test_material_guard_is_opt_in_and_rejection_does_not_consume_hit_identity(self):
        mesh = slab(10)
        fixture = ActorFixture(900, bytes(23), bytes(1516), bytes(40), (100, 0, 0),
            ((100, 0, 0),), 0, 1000, 100, collision_meshes=(mesh,))
        actor = ActorState(fixture)
        actor.begin(0)
        fire = struct.pack('>6fIBIIfII', 0, 0, 0, 100, 0, 0, 7, 0, 100, 0, 480, 0, 0)
        actor.note_fire(fire, dict(action='fire', gun_definition=10202))
        hit = bytearray(106)
        struct.pack_into('>IQ', hit, 0, 1, 900)
        struct.pack_into('>3i', hit, 37, 100, 0, 0)
        struct.pack_into('>3f', hit, 50, 100, 0, 0)
        hit[62] = 2
        struct.pack_into('>I', hit, 88, 7)
        struct.pack_into('>I', hit, 96, 100)
        packets, event = actor.hit(hit, 10)
        self.assertEqual((packets, event['reason'], actor.hp, actor.hits), ([], 'line_of_sight', 1000, set()))
        actor.fixture = replace(fixture, material_penetration=True)
        packets, event = actor.hit(hit, 10)
        self.assertEqual((event['action'], actor.hp), ('hit_damage', 900))
        self.assertEqual(event['validation'], 'diagnostic_ray_material')
        self.assertIn(0x11eb, [command for command, _ in packets])
        self.assertEqual(actor.hit(hit, 10)[1]['reason'], 'duplicate_hit')


if __name__ == '__main__':
    unittest.main()
