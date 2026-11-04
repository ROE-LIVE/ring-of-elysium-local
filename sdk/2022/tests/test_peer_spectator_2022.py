"""Комнаты, смена цели и переподключение диагностического наблюдателя."""
import struct
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server/directory'))
from peer_spectator_2022 import PeerSpectators


class PeerSpectatorTests(unittest.TestCase):
    def state(self, dead=False, at=100):
        return dict(world=SimpleNamespace(dead=dead), auth_sent=True,
                    room_sent=True, peer_avatar_anchor=(None, None, at))

    def test_stable_target_changes_on_death_and_leave_and_excludes_other_room(self):
        observer, a, b = self.state(True), self.state(), self.state()
        rooms = SimpleNamespace(members={(1,10):dict(state=observer,avatar=500),
                  (1,20):dict(state=a,avatar=700), (1,30):dict(state=b,avatar=600),
                  (2,40):dict(state=self.state(),avatar=1)})
        control = PeerSpectators()
        outputs, _ = control.poll(rooms, 100)
        self.assertEqual(outputs, [(b, [(0x6fbe, struct.pack('>Q',10))]),
                                   (observer, [(0x6fbb, struct.pack('>Q',600))])])
        self.assertEqual(control.poll(rooms,100), ([],[]))
        rooms.members[(1,50)] = dict(state=self.state(),avatar=550)
        self.assertEqual(control.poll(rooms,100), ([],[]))
        b['world'].dead = True
        outputs, _ = control.poll(rooms,100)
        self.assertEqual(struct.unpack('>Q',outputs[-1][1][0][1])[0],550)
        rooms.members[(1,50)]['state']['transport_retired'] = True
        outputs, _ = control.poll(rooms,100)
        self.assertEqual(struct.unpack('>Q',outputs[-1][1][0][1])[0],700)
        del rooms.members[(1,20)]
        outputs, _ = control.poll(rooms,100)
        self.assertEqual(outputs[0][1],[(0x6fbb,struct.pack('>Q',0))])

    def test_late_join_rebind_and_stale_transport(self):
        observer = self.state(True)
        rooms = SimpleNamespace(members={(1,10):dict(state=observer,avatar=500)})
        control = PeerSpectators()
        self.assertEqual(control.poll(rooms,100),([],[]))
        rooms.members[(1,20)] = dict(state=self.state(),avatar=600)
        self.assertEqual(len(control.poll(rooms,100)[0]),2)
        replacement = self.state(True)
        rooms.members[(1,10)]['state'] = replacement
        outputs, _ = control.poll(rooms,100)
        self.assertIs(outputs[-1][0],replacement)
        self.assertEqual(control.poll(rooms,106),([],[]))
        for member in rooms.members.values():
            member['state']['peer_avatar_anchor']=(None,None,107)
        self.assertEqual(control.poll(rooms,107),([],[]))
        del rooms.members[(1,10)]
        control.poll(rooms,107)
        self.assertNotIn((1,10),control.receipts)

    def test_late_model_is_not_selected_before_explicit_ready_delay(self):
        observer = self.state(True)
        rooms = SimpleNamespace(members={(1,10):dict(state=observer,avatar=500),
                  (1,20):dict(state=self.state(),avatar=600,spectator_ready_at=102)})
        control = PeerSpectators()
        self.assertEqual(control.poll(rooms,101.99),([],[]))
        self.assertEqual(len(control.poll(rooms,102)[0]),2)

    def camera_fixture(self):
        observer, sender = self.state(True), self.state()
        observer.update(room_uid=1,actor_uid=10)
        sender.update(room_uid=1,actor_uid=20)
        rooms = SimpleNamespace(members={(1,10):dict(state=observer,avatar=500),
                                        (1,20):dict(state=sender,avatar=600)})
        control = PeerSpectators()
        control.poll(rooms,100)
        return control,rooms,observer,sender

    def camera_body(self, tick=1):
        return struct.pack('>IB',62,1)+struct.pack('<QQII9fB',20,20,tick,0,*range(9),0)

    def test_camera_translates_account_uids_to_unit_and_preserves_other_bytes(self):
        control,rooms,observer,sender = self.camera_fixture()
        body = self.camera_body()
        outputs,events = control.relay_camera(rooms,sender,body,100)
        self.assertEqual(events,[])
        self.assertIs(outputs[0][0],observer)
        command,translated = outputs[0][1][0]
        self.assertEqual(command,0x6fbd)
        self.assertEqual(struct.unpack_from('<QQ',translated,5),(600,600))
        self.assertEqual(translated[:5],body[:5])
        self.assertEqual(translated[21:],body[21:])
        self.assertEqual(control.relay_camera(rooms,sender,body,100),([],[]))

    def test_camera_rejects_invalid_size_selector_uid_and_nonfinite_float(self):
        for variant in ('short','count','selector','uid','nan'):
            with self.subTest(variant=variant):
                control,rooms,observer,sender = self.camera_fixture()
                body = bytearray(self.camera_body())
                if variant == 'short': body.pop()
                if variant == 'count': struct.pack_into('>I',body,0,61)
                if variant == 'selector': body[4]=2
                if variant == 'uid': struct.pack_into('<Q',body,13,500)
                if variant == 'nan': struct.pack_into('<f',body,29,float('nan'))
                self.assertEqual(control.relay_camera(rooms,sender,body,100),([],[]))
                self.assertFalse(control.camera_ticks)

    def test_camera_tick_wrap_reordering_and_new_transport_epoch(self):
        control,rooms,observer,sender = self.camera_fixture()
        self.assertTrue(control.relay_camera(rooms,sender,self.camera_body(0xfffffffe),100)[0])
        self.assertTrue(control.relay_camera(rooms,sender,self.camera_body(1),100)[0])
        self.assertEqual(control.relay_camera(rooms,sender,self.camera_body(0xffffffff),100),([],[]))
        replacement = dict(sender)
        rooms.members[(1,20)]['state']=replacement
        self.assertEqual(control.relay_camera(rooms,sender,self.camera_body(2),100),([],[]))
        self.assertTrue(control.relay_camera(rooms,replacement,self.camera_body(0),100)[0])
        self.assertEqual(len(control.camera_ticks),1)

    def test_camera_requires_current_dead_observer_alive_sender_and_same_room(self):
        for variant in ('alive_observer','dead_sender','stale_sender','retired','rebound','other_room'):
            with self.subTest(variant=variant):
                control,rooms,observer,sender = self.camera_fixture()
                if variant == 'alive_observer': observer['world'].dead=False
                if variant == 'dead_sender': sender['world'].dead=True
                if variant == 'stale_sender': sender['peer_avatar_anchor']=(None,None,94)
                if variant == 'retired': sender['transport_retired']=True
                if variant == 'rebound': rooms.members[(1,10)]['state']=dict(observer)
                if variant == 'other_room': rooms.members[(2,10)]=rooms.members.pop((1,10))
                self.assertEqual(control.relay_camera(rooms,sender,self.camera_body(),100),([],[]))

    def test_camera_fanout_only_selected_observers(self):
        control,rooms,observer,sender = self.camera_fixture()
        second=self.state(True); second.update(room_uid=1,actor_uid=30)
        rooms.members[(1,30)]=dict(state=second,avatar=700)
        control.poll(rooms,100)
        outputs,_=control.relay_camera(rooms,sender,self.camera_body(),100)
        self.assertEqual([state for state,_ in outputs],[observer,second])
        observer['world'].dead = False
        control.poll(rooms,102)
        observer['world'].dead = True
        self.assertEqual(len(control.poll(rooms,102)[0]),2)
