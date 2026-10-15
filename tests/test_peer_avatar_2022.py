"""Изоляция комнат и UID экспериментальных отображаемых игроков2022."""
import struct
import sys
import tempfile
import json
import contextlib
import io
import unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server/directory'))
from peer_avatar_2022 import PeerAvatarRooms
from game_endpoint_probe_2022 import Endpoint
from listener import Capture

class PeerAvatarTests(unittest.TestCase):
    def test_idle_trajectory_settles_once_and_new_motion_reschedules(self):
        rooms=self.fixture();rooms.replicate_trajectories=True
        a,b,c=self.state(10),self.state(20),self.state(30,2)
        for state in (a,b,c):rooms.admit(state,1)
        movement=dict(points=[dict(position=(100,200,300),bytes=(0,2,0),value=100)],
                      word_1=330,bytes=(1,1,0),floats=(1.,0.,0.))
        rooms.move(a,(100,200,300),100,10,movement)
        self.assertEqual(rooms.settle_motion(10.3,108),([],[]))
        rooms.move(a,(100,200,300),100,10.3,movement)
        self.assertEqual(rooms.settle_motion(10.4,110),([],[]))
        outputs,events=rooms.settle_motion(10.7,117)
        self.assertEqual(len(outputs),1);self.assertIs(outputs[0][0],b)
        code,body=outputs[0][1][0]
        self.assertEqual((code,len(body)),(0x25,50))
        self.assertEqual(struct.unpack_from('>H',body,8)[0],0)
        self.assertEqual((body[22],body[28],body[41]),(2,1,0))
        self.assertEqual(struct.unpack_from('>I',body,24)[0],117)
        self.assertEqual(rooms.members[(1,10)]['pose'],1)
        self.assertEqual(events[0]['action'],'peer_avatar_motion_settle')
        # Настоящий Capture резервирует sequence: fake record пропускал конфликт,
        # который останавливал asyncio timer после первой остановки native254.
        with tempfile.TemporaryDirectory() as directory:
            capture=Capture(Path(directory)/'capture')
            endpoint=Endpoint.__new__(Endpoint);endpoint.capture=capture
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    endpoint.emit_peer_avatars(outputs,events)
                record=json.loads((capture.directory/'events.jsonl').read_text())
                self.assertEqual(record['sequence'],1)
                self.assertEqual(record['motion_sequence'],member_sequence := rooms.members[(1,10)]['motion_sequence'])
                self.assertGreater(member_sequence,0)
            finally:
                capture.events.close()
        self.assertEqual(rooms.settle_motion(20,350),([],[]))
        rooms.move(a,(100,200,300),100,20,movement)
        a['world']=SimpleNamespace(hp=0,dead=True)
        self.assertEqual(rooms.settle_motion(21,125),([],[]))

    def test_trajectory_is_opt_in_keeps_room_isolation_and_has_safe_fallback(self):
        rooms=self.fixture();rooms.replicate_trajectories=True
        a,b,c=self.state(10),self.state(20),self.state(30,2)
        for state in (a,b,c):rooms.admit(state,1)
        movement=dict(points=[dict(position=(100,200,300),bytes=(0,0,0),value=100),
                              dict(position=(90,200,300),bytes=(0,0,0),value=101)],
                      word_1=500,bytes=(1,1,0),floats=(-1.,0.,0.))
        outputs,events=rooms.move(a,(90,200,300),101,10,movement)
        self.assertEqual(len(outputs),1);self.assertIs(outputs[0][0],b)
        self.assertEqual(outputs[0][1][0][0],0x25)
        self.assertTrue(events[0]['trajectory_replicated'])
        uid=rooms.members[(1,10)]['avatar']
        self.assertEqual(struct.unpack_from('>Q',outputs[0][1][0][1])[0],uid)
        sequence=struct.unpack_from('>I',outputs[0][1][0][1],46)[0]
        self.assertEqual(struct.unpack_from('>I',rooms.movement_packet(rooms.members[(1,10)],102)[1],23)[0],sequence)
        movement['bytes']=(255,1,0)
        outputs,events=rooms.move(a,(90,200,300),102,10.3,movement)
        self.assertEqual(outputs[0][1][0][0],0x27)
        self.assertFalse(events[0]['trajectory_replicated'])
        self.assertIsNotNone(events[0]['trajectory_fallback'])

    def test_pose_transition_precedes_trajectory_and_jump_uses_discrete_path(self):
        rooms=self.fixture();rooms.replicate_trajectories=True
        a,b=self.state(10),self.state(20)
        rooms.admit(a,1);rooms.admit(b,1)
        movement=dict(points=[dict(position=(100,200,300),bytes=(0,2,0),value=100)],
                      word_1=0,bytes=(0,1,0),floats=(1.,0.,0.))
        outputs,_=rooms.move(a,(100,200,300),100,10,movement)
        self.assertEqual([code for code,_ in outputs[0][1]],[0x27,0x25])
        self.assertEqual(struct.unpack_from('>I',outputs[0][1][0][1],27)[0],1)
        movement['points'][0]['bytes']=(0,22,0)
        outputs,_=rooms.move(a,(100,200,300),100,10.01,movement)
        self.assertEqual([code for code,_ in outputs[0][1]],[0x27])
    def test_health_tracks_one_authoritative_world_and_snapshot_uses_unit_uid(self):
        rooms = self.fixture(); rooms.replicate_health = True
        a, b, c = self.state(10), self.state(20), self.state(30, 2)
        a['world'] = SimpleNamespace(hp=700, dead=False)
        b['world'] = SimpleNamespace(hp=1000, dead=False)
        for state in (a, b, c): rooms.admit(state, 1)
        uid = rooms.members[(1,10)]['avatar']
        packets = rooms.packets(rooms.members[(1,10)], 3)
        self.assertEqual(struct.unpack('>QBBBII', packets[-1][1]), (uid,0,1,0,700,1000))
        outputs, events = rooms.health(a)
        self.assertEqual(len(outputs), 1); self.assertIs(outputs[0][0], b)
        self.assertEqual(events[0]['hp'], 700)
        self.assertEqual(rooms.health(a), ([], []))
        a['world'].hp = 0; a['world'].dead = True
        outputs, events = rooms.health(a)
        self.assertEqual([code for code, _ in outputs[0][1]], [0x1069, 0x533])
        self.assertEqual(outputs[0][1][-1][1], struct.pack('>IQ', 0, uid))
        self.assertEqual(b['world'].hp, 1000)
        old = dict(a); old['world'] = SimpleNamespace(hp=1, dead=False)
        self.assertEqual(rooms.health(old), ([], []))
        self.assertEqual(rooms.health(a), ([], []))

    def test_stale_observer_receives_current_hp_on_heartbeat_without_new_damage(self):
        rooms = self.fixture(); rooms.replicate_health = True
        a, b = self.state(10), self.state(20)
        a['world'] = SimpleNamespace(hp=1000, dead=False)
        b.update(auth_sent=True, room_sent=True, peer_avatar_anchor=(None,None,100))
        for state in (a,b): rooms.admit(state,1)
        self.assertEqual(len(rooms.health(a, 100)[0]), 1)
        a['world'].hp = 700
        self.assertEqual(rooms.health(a, 110)[0], [])
        b['peer_avatar_anchor'] = (None,None,111)
        outputs, _ = rooms.health(a, 111)
        self.assertEqual(struct.unpack('>QBBBII',outputs[0][1][0][1])[-2:], (700,1000))
        self.assertEqual(rooms.health(a, 112), ([],[]))

    def test_pose_transition_bypasses_position_throttle_and_zero_event_preserves_pose(self):
        rooms=self.fixture();a,b=self.state(10),self.state(20)
        rooms.admit(a,1);rooms.admit(b,1)
        def movement(events):
            return dict(points=[dict(position=(100,200,300),bytes=(0,event,0)) for event in events])
        rooms.move(a,(100,200,300),10,10)
        outputs,events=rooms.move(a,(100,200,300),11,10.01,movement([2,0]))
        self.assertEqual(struct.unpack_from('>I',outputs[0][1][-1][1],27)[0],1)
        self.assertEqual(events[0]['transitions'],[dict(client_event=2,server_status=1)])
        outputs,_=rooms.move(a,(101,200,300),12,10.3,movement([0]))
        self.assertEqual(struct.unpack_from('>I',outputs[0][1][-1][1],27)[0],1)
        outputs,events=rooms.move(a,(101,200,300),13,10.31,movement([22,4,1]))
        self.assertEqual([struct.unpack_from('>I',p,27)[0] for _,p in outputs[0][1]],[3,9,0,0])
        outputs,events=rooms.move(a,(101,200,300),14,10.32,movement([255]))
        self.assertEqual(outputs,[]);self.assertEqual(events[0]['unknown_pose_events'],[255])
        self.assertEqual(rooms.members[(1,10)]['pose'],0)

    def test_deferred_pose_snapshot_uses_current_pose_and_stops_after_two_attempts(self):
        rooms=self.fixture();a,b=self.state(10),self.state(20)
        rooms.admit(a,1,10)
        rooms.move(a,(100,200,300),2,10.1,dict(points=[dict(position=(100,200,300),bytes=(0,3,0))]))
        rooms.admit(b,3,11)
        self.assertEqual(rooms.pose_snapshots(11.99,4),([],[]))
        outputs,_=rooms.pose_snapshots(12,4)
        for state,packets in outputs:
            if state is b:self.assertEqual(struct.unpack_from('>I',packets[0][1],27)[0],2)
        rooms.detach(a,'leave')
        self.assertEqual(rooms.pose_snapshots(14,5),([],[]))
        c=self.state(30);rooms.admit(c,6,15)
        self.assertEqual(len(rooms.pose_snapshots(16,7)[0]),2)
        self.assertEqual(len(rooms.pose_snapshots(18,8)[0]),2)
        self.assertEqual(rooms.pose_snapshots(20,9),([],[]))

    def fixture(self):
        return PeerAvatarRooms(SimpleNamespace(listing=bytes([1])+bytes(22),profile=bytes(1516),movement=bytes(40)))
    def state(self,account,room=1):
        return dict(actor_uid=account,room_uid=room,scene_position=(100,200,300))
    def test_two_members_get_distinct_unit_uids_and_same_room_only(self):
        rooms=self.fixture();a,b,c=self.state(10),self.state(20),self.state(30,2)
        self.assertEqual(rooms.admit(a,1)[0],[])
        self.assertEqual(rooms.admit(c,1)[0],[])
        out,events=rooms.admit(b,2)
        self.assertEqual(len(out),2)
        self.assertIs(out[0][0],a);self.assertIs(out[1][0],b)
        ua=rooms.members[(1,10)]['avatar'];ub=rooms.members[(1,20)]['avatar']
        self.assertNotEqual(ua,ub);self.assertNotEqual(ua,10)
        self.assertEqual(struct.unpack_from('>Q',out[0][1][0][1],14)[0],ub)
        self.assertEqual(struct.unpack_from('>Q',out[1][1][1][1],8)[0],ua)
        out,_=rooms.move(b,(101,202,303),3,10)
        self.assertEqual(len(out),1);self.assertIs(out[0][0],a)
        self.assertEqual(struct.unpack_from('>Q3i',out[0][1][0][1]),(ub,101,202,303))
        self.assertEqual(rooms.move(b,(102,202,303),4,10.1)[0],[])
        self.assertEqual(rooms.members[(1,20)]['position'],(102,202,303))
        with self.assertRaises(ValueError):rooms.move(b,(float('nan'),0,0),4,11)
    def test_duplicate_account_cannot_replace_state_but_resume_preserves_unit_uid(self):
        rooms=self.fixture();a,b=self.state(10),self.state(10)
        rooms.admit(a,1);uid=rooms.members[(1,10)]['avatar']
        self.assertEqual(rooms.admit(b,2)[1][0]['action'],'peer_avatar_duplicate_account')
        self.assertIs(rooms.members[(1,10)]['state'],a)
        self.assertEqual(rooms.move(b,(1,2,3),3,10)[0],[])
        b['gameplay_resumed']=True;rooms.admit(b,3)
        self.assertEqual(rooms.members[(1,10)]['avatar'],uid)
        self.assertIs(rooms.members[(1,10)]['state'],b)
    def test_room_capacity_does_not_leak_members(self):
        rooms=self.fixture()
        for account in range(1,9):rooms.admit(self.state(account),1)
        out,event=rooms.admit(self.state(9),2)
        self.assertEqual(out,[]);self.assertEqual(event[0]['action'],'peer_avatar_room_limit')
        self.assertNotIn((1,9),rooms.members)

    def test_leave_sends_native583_once_and_keeps_other_room(self):
        rooms = self.fixture()
        a,b,c = self.state(10),self.state(20),self.state(30,2)
        for state in (a,b,c):rooms.admit(state,1)
        uid = rooms.members[(1,10)]['avatar']
        outputs,events = rooms.detach(a,'peer_idle_timeout')
        self.assertEqual(outputs,[(b,[(0x583,struct.pack('>Q',uid))])])
        self.assertEqual(events[0]['avatar_uid'],hex(uid))
        self.assertEqual(rooms.detach(a,'repeat'),([],[]))
        self.assertIn((2,30),rooms.members)
        newcomer = self.state(10);rooms.admit(newcomer,2)
        self.assertNotEqual(rooms.members[(1,10)]['avatar'],uid)

    def test_old_transport_leave_cannot_remove_rebound_avatar(self):
        rooms=self.fixture();a,b=self.state(10),self.state(10)
        rooms.admit(a,1);uid=rooms.members[(1,10)]['avatar']
        b['gameplay_resumed']=True;rooms.admit(b,2)
        self.assertEqual(rooms.detach(a,'transport_retired'),([],[]))
        self.assertEqual(rooms.members[(1,10)]['avatar'],uid)
