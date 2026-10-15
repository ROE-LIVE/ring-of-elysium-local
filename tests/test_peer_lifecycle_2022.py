"""Timeout45с, RELAY30с, общий reset и чужой UID при одинаковом lobby identity."""
import asyncio
import contextlib
import io
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import test_weapon_probe_2022 as weapon_tests
from peer_avatar_2022 import PeerAvatarRooms
from shared_loot_2022 import SharedLootRooms
from peer_lifecycle_2022 import expired_members
from game_endpoint_probe_2022 import Endpoint
from listener import Capture


class PeerLifecycleTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.capture=Capture(Path(self.temp.name)/'capture');self.addCleanup(self.capture.events.close)
        self.fixture=SimpleNamespace(listing=bytes(23),profile=bytes(1516),movement=bytes(40))
        self.weapon=weapon_tests.WeaponStateTests().recycling_state()
        self.endpoint=Endpoint(self.capture,weapon_fixture=self.weapon.fixture,
                               peer_avatar_fixture=self.fixture,shared_ground_loot=True)
        self.addCleanup(self.endpoint.stop_peer_timer)
        self.a=dict(actor_uid=100,room_uid=1,scene_position=(100,200,300),weapon=self.weapon,
                    auth_sent=True,room_sent=True,identity=b'LOCAL',
                    peer_avatar_anchor=(None,('127.0.0.1',1),100),last_application_at=100)
        self.endpoint.shared_loot.attach(self.a);self.endpoint.peer_avatars.admit(self.a,1)

    async def test_grace_exceeds_relay_window_and_includes_last_seen_boundary(self):
        rooms,loot=self.endpoint.peer_avatars,self.endpoint.shared_loot
        self.assertEqual(expired_members(rooms,loot,130),[])
        self.assertEqual(expired_members(rooms,loot,144.999),[])
        self.assertEqual(expired_members(rooms,loot,145),[(self.a,'peer_idle_timeout')])
        self.a['peer_avatar_anchor']=(None,None,140)
        self.assertEqual(expired_members(rooms,loot,145),[])

    async def test_finished_and_retired_members_expire_without_idle_wait(self):
        for flag,reason in [('match_finished','match_finished'),('transport_retired','transport_retired')]:
            self.a[flag]=True
            self.assertEqual(expired_members(self.endpoint.peer_avatars,self.endpoint.shared_loot,101),[(self.a,reason)])
            self.a[flag]=False

    async def test_poll_removes_last_member_retires_transport_and_resets_room(self):
        with patch('game_endpoint_probe_2022.time.monotonic',return_value=145),contextlib.redirect_stdout(io.StringIO()):
            self.endpoint.poll_peer_rooms()
        self.assertTrue(self.a['transport_retired']);self.assertFalse(self.a['room_sent'])
        self.assertFalse(self.endpoint.peer_avatars.members)
        self.assertFalse(self.endpoint.shared_loot.rooms)
        self.assertEqual(self.endpoint.shared_loot.epochs[1],2)
        self.endpoint.stop_peer_timer();self.assertIsNone(self.endpoint.peer_timer)

    async def test_relay_preserves_avatar_and_epoch_but_other_account_cannot_take_inventory(self):
        old_identity=(('127.0.0.1',1),5000,18001)
        new_identity=(('127.0.0.1',2),5001,18001)
        self.a['handoff_at']=100
        self.endpoint.sessions[old_identity]=self.a
        new=dict(auth_sent=True,identity=b'LOCAL',room_sent=False,frame_seq=3)
        self.assertFalse(self.endpoint.resume_gameplay(new_identity,new,110))
        self.assertFalse(self.endpoint.resume_gameplay(new_identity,new,110,104))
        uid=self.endpoint.peer_avatars.members[(1,100)]['avatar']
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(self.endpoint.resume_gameplay(new_identity,new,110,100))
        self.assertIs(new['weapon'],self.weapon)
        self.assertIs(self.endpoint.peer_avatars.members[(1,100)]['state'],new)
        self.assertEqual(self.endpoint.peer_avatars.members[(1,100)]['avatar'],uid)
        self.assertEqual(new['shared_loot_epoch'],1)
        self.assertIs(self.endpoint.shared_loot.rooms[1]['members'][100],new)
        self.assertFalse(self.endpoint.shared_loot.detach(self.a))

    async def test_finished_member_leaves_world_without_retiring_frozen_result_transport(self):
        self.a['match_finished'] = True
        self.a['match_terminal_packets'] = ((0x106e, bytes(4)),)
        with patch('game_endpoint_probe_2022.time.monotonic', return_value=101), contextlib.redirect_stdout(io.StringIO()):
            self.endpoint.poll_peer_rooms()
        self.assertFalse(self.endpoint.shared_loot.rooms)
        self.assertFalse(self.endpoint.peer_avatars.members)
        self.assertTrue(self.a['room_sent'])
        self.assertFalse(self.a.get('transport_retired', False))
        self.assertEqual(self.a['match_terminal_packets'], ((0x106e, bytes(4)),))
