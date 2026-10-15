"""Общие места, водитель и поздний snapshot; modeled, не native физика."""
import struct
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server/directory'))
from shared_vehicle_2022 import SharedVehicleRooms
from vehicle_probe_2022 import VehicleState


class SharedVehicleTests(unittest.TestCase):
    def state(self,account,room=1):
        return dict(actor_uid=account,room_uid=room,world=SimpleNamespace(dead=False),
                    vehicles=VehicleState(account))

    def spawn(self,configuration=102):
        body=bytearray(164)
        struct.pack_into('>QIIIiii',body,0,900,configuration,1,21600,100,200,300)
        return bytes(body)

    def setup_room(self):
        control=SharedVehicleRooms();first=self.state(10);second=self.state(20)
        for state in (first,second):
            state['vehicles'].register(0x654b,self.spawn())
            control.register(state,0x654b,self.spawn())
        avatars=SimpleNamespace(members={(1,10):dict(state=first,avatar=500),
                                        (1,20):dict(state=second,avatar=600)})
        control.sync(avatars,100)
        return control,avatars,first,second

    def board(self,control,state,seat):
        return control.handle(state,0x6541,struct.pack('>QI',900,seat),100)

    def motion(self,tick=100):
        body=bytearray(73);struct.pack_into('>QI',body,0,900,tick)
        struct.pack_into('>iii',body,13,400,500,600)
        struct.pack_into('>4f',body,53,0,0,0,1)
        return bytes(body)

    def test_seat_conflict_is_atomic_and_remote_geton_uses_unit_uid(self):
        control,avatars,first,second=self.setup_room()
        packets,event,outputs=self.board(control,first,1)
        self.assertEqual(event['action'],'geton')
        self.assertEqual(struct.unpack_from('>Q',packets[0][1],16)[0],10)
        self.assertEqual(struct.unpack_from('>Q',outputs[0][1][0][1],16)[0],500)
        packets,event,outputs=self.board(control,second,1)
        self.assertEqual(event['reason'],'seat_occupied')
        self.assertEqual((packets,outputs),([],[]))
        self.assertIsNone(second['vehicles'].seated)
        self.assertEqual(control.rooms[1]['seats'][900],{1:10})
        self.assertEqual(self.board(control,second,2)[1]['seat'],2)

    def test_only_driver_can_move_and_tick_replay_is_rejected(self):
        control,avatars,first,second=self.setup_room()
        self.board(control,first,1);self.board(control,second,2)
        self.assertEqual(control.handle(second,0x6549,self.motion(),100)[1]['reason'],'not_driver')
        self.assertEqual(first['vehicles'].vehicles[900]['position'],(100,200,300))
        packets,event,outputs=control.handle(first,0x6549,self.motion(0xfffffffe),100)
        self.assertEqual(packets,[])
        self.assertEqual(outputs,[(second,[(0x6575,self.motion(0xfffffffe))])])
        self.assertEqual(second['vehicles'].vehicles[900]['position'],(400,500,600))
        self.assertEqual(control.handle(first,0x6549,self.motion(0xfffffffe),100)[1]['reason'],'stale_motion')
        self.assertEqual(control.handle(first,0x6549,self.motion(1),100)[1]['action'],'vehicle_move')
        self.assertEqual(control.handle(first,0x6549,self.motion(0xffffffff),100)[1]['reason'],'stale_motion')

    def test_switch_owner_after_exit_and_translate_both_events(self):
        control,avatars,first,second=self.setup_room()
        self.board(control,first,1);self.board(control,second,2)
        self.assertEqual(control.handle(second,0x6547,struct.pack('>I',1),100)[1]['reason'],'seat_occupied')
        packets,event,outputs=control.handle(first,0x6543,struct.pack('>BiiiB',0,110,210,310,0),100)
        self.assertEqual(struct.unpack_from('>Q',outputs[0][1][0][1],12)[0],500)
        packets,event,outputs=control.handle(second,0x6547,struct.pack('>I',1),100)
        self.assertEqual(event['action'],'seat_switch')
        self.assertEqual(struct.unpack_from('>Q',outputs[0][1][0][1],8)[0],600)
        self.assertEqual(control.rooms[1]['seats'][900],{1:20})
        self.assertEqual(control.handle(first,0x6549,self.motion(),100)[1]['reason'],'not_driver')
        self.assertEqual(control.handle(second,0x6549,self.motion(),100)[1]['action'],'vehicle_move')

    def test_late_fixture_keeps_authoritative_hp_position_and_snapshot_seats(self):
        control,avatars,first,second=self.setup_room()
        self.board(control,first,1)
        control.handle(first,0x6549,self.motion(),100)
        first['vehicles'].vehicles[900]['hp']=10000
        late=self.state(30);late['vehicles'].register(0x654b,self.spawn())
        body=control.register(late,0x654b,self.spawn())
        self.assertEqual(struct.unpack_from('>Iiii',body,16),(10000,400,500,600))
        avatars.members[(1,30)]=dict(state=late,avatar=700);control.sync(avatars,101)
        control.snapshots(102)
        outputs,_=control.snapshots(103)
        packets=next(p for s,p in outputs if s is late)
        self.assertEqual(packets[0][0],0x656d)
        self.assertEqual(packets[1],(0x6575,self.motion()))
        self.assertEqual(struct.unpack_from('>Q',packets[2][1],16)[0],500)

    def test_rebind_detected_when_avatar_member_dict_is_mutated(self):
        control,avatars,first,second=self.setup_room()
        self.board(control,first,1);control.snapshots(102);control.snapshots(104)
        replacement=dict(second);avatars.members[(1,20)]['state']=replacement
        control.sync(avatars,105)
        outputs,_=control.snapshots(107)
        self.assertEqual(len(outputs),1)
        self.assertIs(outputs[0][0],replacement)

    def test_death_leave_room_epoch_and_room_isolation(self):
        control,avatars,first,second=self.setup_room()
        self.board(control,first,1);self.board(control,second,2)
        first['world'].dead=True;first['vehicles'].cancel_on_death()
        control.sync(avatars,101)
        self.assertEqual(control.rooms[1]['seats'][900],{2:20})
        other=self.state(30,2);other['vehicles'].register(0x654b,self.spawn())
        control.register(other,0x654b,self.spawn());avatars.members[(2,30)]=dict(state=other,avatar=700)
        control.sync(avatars,102)
        self.assertEqual(self.board(control,other,1)[1]['seat'],1)
        second['transport_retired']=True;control.sync(avatars,103)
        self.assertEqual(control.rooms[1]['seats'][900],{})
        avatars.members.pop((1,10));control.sync(avatars,104)
        self.assertNotIn(1,control.rooms)
        self.assertIn(2,control.rooms)

    def test_old_transport_and_wrong_configuration_cannot_change_authority(self):
        control,avatars,first,second=self.setup_room()
        replacement=dict(first);avatars.members[(1,10)]['state']=replacement
        control.sync(avatars,101)
        self.assertEqual(self.board(control,first,1)[1]['reason'],'invalid_member')
        second['vehicles'].register(0x654b,self.spawn(109))
        with self.assertRaises(ValueError):control.register(second,0x654b,self.spawn(109))
        self.assertEqual(second['vehicles'].vehicles[900]['configuration'],102)

    def test_owner_packet_activates_remote_role_and_self_uses_account(self):
        control,avatars,first,second=self.setup_room()
        own,event,outputs=self.board(control,first,1)
        self.assertEqual([code for code,_ in own],[0x6542,0x656d])
        self.assertEqual(len(own[1][1]),52)
        self.assertEqual(struct.unpack_from('>QIQ',own[1][1]),(900,0,10))
        remote=outputs[0][1][-1][1]
        self.assertEqual(struct.unpack_from('>QIQ',remote),(900,0,500))
        control.handle(first,0x6549,self.motion(),100)
        body=control.owner_packet(control.rooms[1],900,second)[1]
        self.assertEqual(body[20:33],self.motion()[13:26])
        self.assertEqual(body[33:49],self.motion()[53:69])

    def test_death_releases_native_owner_to_remaining_peer(self):
        control,avatars,first,second=self.setup_room()
        self.board(control,first,1)
        control.snapshots(102);control.snapshots(104)
        first['world'].dead=True;first['vehicles'].cancel_on_death()
        control.sync(avatars,105)
        outputs,_=control.snapshots(105)
        body=next(body for state,packets in outputs if state is second for code,body in packets if code==0x656d)
        self.assertEqual(struct.unpack_from('>QIQ',body),(900,0,0))
        self.assertEqual(control.snapshots(105),([],[]))

    def test_invalid_motion_cannot_poison_late_snapshot_or_transform(self):
        control,avatars,first,second=self.setup_room();self.board(control,first,1)
        for offset,value in ((26,float('nan')),(53,float('inf'))):
            body=bytearray(self.motion());struct.pack_into('>f',body,offset,value)
            packets,event,outputs=control.handle(first,0x6549,bytes(body),100)
            self.assertEqual(event['reason'],'invalid_motion')
            self.assertEqual((packets,outputs),([],[]))
        self.assertEqual(first['vehicles'].vehicles[900]['position'],(100,200,300))
        self.assertEqual(control.rooms[1]['motion'],{})

    def test_disconnect_clears_remote_native_seat_before_owner_update(self):
        control,avatars,first,second=self.setup_room()
        self.board(control,first,1);self.board(control,second,2)
        control.snapshots(102);control.snapshots(104)
        del avatars.members[(1,10)];control.sync(avatars,105)
        outputs,_=control.snapshots(105)
        codes=[code for target,packets in outputs if target is second for code,body in packets]
        self.assertEqual(codes,[0x6544,0x656d])
        body=outputs[0][1][0][1]
        self.assertEqual(len(body),54)
        self.assertEqual(struct.unpack_from('>QIQII',body),(900,1,500,1,0))
        self.assertEqual(control.snapshots(105),([],[]))
