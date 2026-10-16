"""Wire11EB и атомарность подтверждения принятого попадания2022."""
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'server/directory'))
from actor_probe_2022 import ActorFixture, ActorState
from hit_feedback_2022 import encode_hit_broadcast


class HitFeedbackTests(unittest.TestCase):
    def state(self, hp=1000, armor=0):
        fixture = ActorFixture(900, bytes(23), bytes(1516), bytes(40),
            (900, 0, 0), ((900, 0, 0),), 0, hp, 50,
            armor_definition=201001 if armor else 0,
            armor_durability=armor, armor_absorb_percent=50 if armor else 0)
        actor = ActorState(fixture)
        actor.begin(0)
        fire = struct.pack('>6fIBIIfII', 0, 0, 150, 900, 0, 120,
                           7, 0, 100, 0, 480, 0, 0)
        actor.note_fire(fire, {'action': 'fire', 'gun_definition': 10201})
        hit = bytearray(106)
        struct.pack_into('>IQ', hit, 0, 1, 900)
        struct.pack_into('>3i', hit, 37, 900, 0, 0)
        struct.pack_into('>3f', hit, 50, 890, 12, 75)
        hit[62] = 2
        struct.pack_into('>I', hit, 88, 7)
        struct.pack_into('>I', hit, 96, 100)
        return actor, hit

    def test_wire_fields_relative_position_and_accepted_weapon(self):
        actor, hit = self.state()
        packets, event = actor.hit(hit, shooter_uid=10)
        body = dict(packets)[0x11eb]
        self.assertEqual(len(body), 48)
        self.assertEqual(struct.unpack('>QQ3iBBIBB3I', body),
            (10, 900, -10, 12, 75, 0, 2, 50, 0, 0, 100, 0, 10201))
        self.assertEqual(event['hit_feedback_command'], '0x11eb')
        self.assertEqual(actor.hit(hit, shooter_uid=10)[0], [])

    def test_armor_and_lethal_flags_follow_committed_health(self):
        for hp, armor, expected in [(1000, 100, (25, 0, 1)), (20, 0, (20, 1, 0))]:
            with self.subTest(hp=hp, armor=armor):
                actor, hit = self.state(hp, armor)
                packets, event = actor.hit(hit, shooter_uid=10)
                row = struct.unpack('>QQ3iBBIBB3I', dict(packets)[0x11eb])
                self.assertEqual(row[7:10], expected)
                self.assertEqual(event['damage'], expected[0])

    def test_part_id_reaches_native_feedback_without_damage_multiplier(self):
        for part in (1, 2, 3):
            actor, hit = self.state(); hit[62] = part; hit[83] = 1
            packets, event = actor.hit(hit, shooter_uid=10)
            self.assertEqual(dict(packets)[0x11eb][29], part)
            self.assertEqual(event['damage'], 50)

    def test_invalid_impact_or_part_does_not_consume_hit_or_health(self):
        for malformed in ('nan', 'part'):
            actor, hit = self.state(1000, 100)
            if malformed == 'nan': struct.pack_into('>f', hit, 50, float('nan'))
            else: hit[62] = 255
            packets, event = actor.hit(hit, shooter_uid=10)
            self.assertEqual((packets, event['reason']), ([], 'feedback_fields'))
            self.assertEqual((actor.hp, actor.armor_durability, actor.hits), (1000, 100, set()))

    def test_unaccepted_hit_does_not_emit_marker(self):
        actor, hit = self.state()
        actor.shots.clear()
        self.assertEqual(actor.hit(hit, shooter_uid=10)[0], [])

    def test_codec_rejects_invalid_identity_and_geometry(self):
        arguments = [10, 900, (1, 2, 3), 2, 50, False, False, 100, 10201]
        for index, value in [(0, 0), (1, 2**64), (2, (1, 2)), (2, (1, 2, float('inf'))),
                             (3, -1), (4, -1), (5, 1), (7, 2**32)]:
            with self.subTest(index=index, value=value):
                changed = list(arguments); changed[index] = value
                with self.assertRaises(ValueError): encode_hit_broadcast(*changed)
