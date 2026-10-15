"""Настоящие encrypted11DA/11DD: доставка ACK/ownHP/remoteHP и dead guard."""
import contextlib
import io
from pathlib import Path
import struct
import sys
import time
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server/directory'))
import test_game_endpoint_probe_2022 as replay
import test_shared_combat_2022 as fixtures
from game_endpoint_probe_2022 import Endpoint, encode_datagram
from roe_tgcp_2023 import parse_datagram,parse_frame,parse_applications
from roe_protocol_2022 import decrypt
from peer_avatar_2022 import PeerAvatarRooms
from shared_combat_2022 import SharedCombatRooms
from match_statistics_2022 import MatchStatistics


class SharedCombatEndpointTests(unittest.TestCase):
    setUp = replay.GameplayActionReplayTests.setUp
    request = replay.GameplayActionReplayTests.request

    def test_shared_death_loot_rejects_per_client_target_inventory(self):
        fixture=fixtures.SharedCombatTests();fixture.setUp()
        with self.assertRaisesRegex(ValueError,'отдельную мишень'):
            Endpoint(None,weapon_fixture=self.weapon.fixture,
                     world_fixture=fixture.a['world'].fixture,
                     peer_avatar_fixture=fixture.avatars.fixture,
                     actor_fixture=fixture.avatars.fixture,
                     shared_ground_loot=True,shared_peer_health=True,
                     shared_death_loot=True)

    def test_encrypted_fire_hit_death_own_remote_delivery_and_no_repeat(self):
        fixture=fixtures.SharedCombatTests();fixture.setUp()
        now=time.monotonic()
        self.state.update(fixture.a,actor_uid=42,weapon=self.weapon,peer_avatar_admitted=True)
        self.state['world'].actor_uid=42
        self.weapon.position=(0,0,0)
        self.state['match_statistics']=MatchStatistics();self.state['match_statistics'].begin(now)
        other_remote=('127.0.0.1',23457)
        syn=encode_datagram(5001,18001,100,0,0x22,1,0)
        with contextlib.redirect_stdout(io.StringIO()):self.endpoint.datagram_received(syn,other_remote)
        victim=self.endpoint.sessions[(other_remote,5001,18001)]
        victim.update(fixture.b,actor_uid=43,key_sent=True,peer_avatar_admitted=True)
        victim['world'].actor_uid=43;victim['world'].hp=100
        victim['weapon'].actor_uid=43;victim['weapon'].equipment.clear()
        victim['weapon'].pending_reload={'slot':1}
        victim['peer_avatar_anchor']=(parse_datagram(syn),other_remote,now)
        self.state['peer_avatar_anchor']=(parse_datagram(encode_datagram(5000,18001,101,0,0x18,1,0)),self.remote,now)
        rooms=PeerAvatarRooms(fixture.avatars.fixture,True,False,True)
        for state in (self.state,victim):rooms.admit(state,1,now)
        self.endpoint.peer_avatars=rooms;self.endpoint.peer_combat=SharedCombatRooms(rooms,50)
        target=rooms.members[(1,43)]['avatar']
        fire=struct.pack('>6fIBIIfII',0,0,150,900,0,120,1,0,10,0,480,0,0)
        self.request(1,0x11da,fire)
        self.assertEqual(self.weapon.clip,1)
        def commands(raws,port,state):
            result=[]
            for raw in raws:
                d=parse_datagram(raw)
                if not d.data or d.destination_port!=port:continue
                f=parse_frame(d.data)
                result.extend(parse_applications(f,decrypt(f.body,state['key']),'server'))
            return result
        first,_=self.request(2,0x11dd,fixture.hit(target=target))
        own=commands(first,5001,victim);remote=commands(first,5000,self.state)
        self.assertEqual(victim['world'].hp,50)
        self.assertTrue(any(m.command==0x11ea for m in remote))
        self.assertEqual([struct.unpack_from('>Q',m.payload)[0] for m in own if m.command==0x1069],[43])
        self.assertEqual([struct.unpack_from('>Q',m.payload)[0] for m in remote if m.command==0x1069],[target])
        second,_=self.request(3,0x11dd,fixture.hit(2,target=target))
        self.assertTrue(victim['world'].dead)
        self.assertIsNone(victim['weapon'].pending_reload)
        self.assertEqual(self.state['match_statistics'].kills,1)
        self.assertEqual([m.command for m in commands(second,5001,victim)].count(0x533),1)
        self.request(4,0x11dd,fixture.hit(3,target=target))
        self.assertEqual((self.state['match_statistics'].kills,self.weapon.clip,self.state['world'].hp),(1,1,1000))
