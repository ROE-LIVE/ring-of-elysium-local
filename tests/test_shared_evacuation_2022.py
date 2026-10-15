"""Общие места и исход комнаты; modeled участники не native-клиенты."""
import struct
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'server/directory'))
from shared_evacuation_2022 import SharedEvacuationRooms
from vehicle_probe_2022 import VehicleState
from game_endpoint_probe_2022 import Endpoint
from match_statistics_2022 import MatchStatistics


class SharedEvacuationTests(unittest.TestCase):
    def state(self, uid, room=1):
        vehicles = VehicleState(uid)
        vehicles.vehicles[900] = dict(configuration=6, position=(100,200,300),
                                     hp=1000,status=1,flight_phase=2)
        return dict(actor_uid=uid,room_uid=room,world=SimpleNamespace(dead=False),
                    vehicles=vehicles)

    def setup_room(self, count=2):
        states = [self.state(uid) for uid in range(1,count+1)]
        avatars = SimpleNamespace(members={(1,s['actor_uid']):dict(state=s,avatar=500+s['actor_uid']) for s in states})
        control = SharedEvacuationRooms(2)
        control.sync(avatars)
        return control,avatars,states

    def board(self, control, state, seat=1):
        return control.geton(state,struct.pack('>QI',900,seat),100)

    def test_same_seat_requests_assign_distinct_places_and_no_fifth_or_duplicate(self):
        control, avatars, states = self.setup_room(5)
        for index,state in enumerate(states[:4],1):
            packets,event = self.board(control,state)
            self.assertEqual(event['seat'],index)
            self.assertEqual(struct.unpack_from('>I',packets[0][1],24)[0],index)
        self.assertEqual(self.board(control,states[0])[0],[])
        self.assertEqual(self.board(control,states[4])[0],[])
        self.assertIsNone(states[4]['vehicles'].seated)
        decisions,_ = control.poll(100)
        self.assertEqual(decisions,[])
        decisions,_ = control.poll(102)
        self.assertEqual(decisions[0]['reason'],'four_seats')
        self.assertEqual(len(decisions[0]['seats']),4)
        control.commit(decisions[0])
        self.assertEqual(control.poll(103),([],[]))
        self.assertEqual(self.board(control,states[4])[0],[])

    def test_all_boarded_wait_cancels_for_new_alive_member(self):
        control,avatars,states = self.setup_room()
        self.board(control,states[0]);self.board(control,states[1])
        self.assertEqual(control.poll(100)[1][0]['reason'],'all_boarded')
        newcomer = self.state(3)
        avatars.members[(1,3)] = dict(state=newcomer)
        control.sync(avatars)
        self.assertEqual(control.poll(102)[0],[])
        self.board(control,newcomer)
        self.assertEqual(control.poll(102)[0],[])
        decisions,_ = control.poll(104)
        self.assertEqual(decisions[0]['reason'],'all_boarded')
        self.assertEqual(len(decisions[0]['seats']),3)

    def test_no_survivors_is_immediate_and_does_not_require_helicopter(self):
        control,avatars,states = self.setup_room()
        for state in states:state['world'].dead=True
        decisions,_ = control.poll(100)
        self.assertEqual(decisions[0]['reason'],'no_survivors')
        self.assertEqual(decisions[0]['seats'],{})
        self.assertEqual(decisions[0]['helicopter_uid'],0)

    def test_loading_member_cancels_old_deadline_before_new_wait(self):
        control,avatars,states=self.setup_room()
        for state in states:self.board(control,state)
        control.poll(100)
        newcomer=self.state(3)
        world=newcomer.pop('world')
        avatars.members[(1,3)]=dict(state=newcomer)
        control.sync(avatars)
        self.assertEqual(control.poll(103)[0],[])
        self.assertIsNone(control.rooms[1]['due'])
        world.dead=True;newcomer['world']=world
        self.assertEqual(control.poll(104)[0],[])
        self.assertEqual(control.poll(106)[0][0]['ended_at'],106)

    def test_death_leave_rebind_and_new_room_epoch_release_correct_seats(self):
        control,avatars,states = self.setup_room()
        self.board(control,states[0]);self.board(control,states[1])
        states[0]['world'].dead=True
        states[0]['vehicles'].cancel_on_death()
        control.sync(avatars)
        self.assertEqual(control.rooms[1]['seats'],{2:2})
        replacement = dict(states[1]);avatars.members[(1,2)]['state']=replacement
        control.sync(avatars)
        self.assertIs(control.rooms[1]['members'][2],replacement)
        self.assertEqual(control.rooms[1]['seats'],{2:2})
        replacement['transport_retired']=True
        control.sync(avatars)
        self.assertEqual(control.rooms[1]['seats'],{})
        avatars.members.clear();control.sync(avatars)
        self.assertEqual(control.rooms,{})
        newcomer=self.state(3);avatars.members[(1,3)]=dict(state=newcomer)
        control.sync(avatars)
        self.assertEqual(self.board(control,newcomer)[1]['seat'],1)

    def test_hover_gate_rejection_does_not_reserve_and_other_room_is_isolated(self):
        control,avatars,states=self.setup_room()
        states[0]['vehicles'].vehicles[900]['flight_phase']=1
        self.assertEqual(self.board(control,states[0])[0],[])
        self.assertEqual(control.rooms[1]['seats'],{})

    def endpoint(self, control, avatars, states, fixture):
        endpoint=Endpoint.__new__(Endpoint)
        endpoint.shared_evacuation=control
        endpoint.peer_avatars=avatars
        endpoint.evacuation_result_fixture=fixture
        endpoint.room_display_name='LOCAL'
        endpoint.records=[];endpoint.sent=[]
        endpoint.capture=SimpleNamespace(record=lambda kind,**kw:endpoint.records.append((kind,kw)))
        endpoint.send_application_batch=lambda d,r,state,packets:endpoint.sent.append((state,packets))
        for state in states:
            state['match_statistics']=MatchStatistics(started_at=90)
            state['peer_avatar_anchor']=(None,('127.0.0.1',10000+state['actor_uid']),100)
        return endpoint

    def test_endpoint_prepares_every_result_before_freezing_and_sends_once(self):
        control,avatars,states=self.setup_room()
        for state in states:self.board(control,state)
        class Fixture:
            invalid=True
            def messages(self,uid,room,report,name):
                if self.invalid and uid==2:raise ValueError('выбранный отрицательный контроль')
                return [(0xd62,struct.pack('>QI',uid,report['rescued']))]
        fixture=Fixture();endpoint=self.endpoint(control,avatars,states,fixture)
        statistics=[state['match_statistics'] for state in states]
        control.poll(100)
        endpoint.poll_shared_evacuation(102)
        self.assertFalse(control.rooms[1]['finished'])
        self.assertEqual(endpoint.sent,[])
        self.assertTrue(all(stat.ended_at is None for stat in statistics))
        fixture.invalid=False
        endpoint.poll_shared_evacuation(103)
        self.assertTrue(control.rooms[1]['finished'])
        self.assertEqual(len(endpoint.sent),2)
        for state,packets in endpoint.sent:
            self.assertTrue(state['match_finished'])
            self.assertNotIn('world',state)
            self.assertEqual(packets[-1],(0x6589,struct.pack('>BQ',1,900)))
            self.assertEqual([code for code,_ in packets].count(0x6580),2)
        self.assertTrue(all(stat.rescued and stat.ended_at==102 for stat in statistics))
        endpoint.poll_shared_evacuation(104)
        self.assertEqual(len(endpoint.sent),2)
        other=self.state(3,2);avatars.members[(2,3)]=dict(state=other)
        control.sync(avatars)
        self.assertEqual(self.board(control,other)[1]['seat'],1)
        self.assertEqual(control.rooms[1]['seats'],{})
