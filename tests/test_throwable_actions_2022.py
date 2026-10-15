"""Native wire cold142 и проверки расхода/времени/повторов локального peer."""
from dataclasses import replace
from pathlib import Path
import struct
import sys
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server/directory'))
from throwable_actions_2022 import (ThrowableActions, decode_throw, decode_finish,
                                    launch_broadcast, finish_broadcast)
from game_endpoint_probe_2022 import Endpoint
from actor_probe_2022 import ActorState, ActorFixture
import test_weapon_probe_2022 as weapon_tests


class ThrowableActionTests(unittest.TestCase):
    request = bytes.fromhex('0000c3510005920c00084ce90003f4c3000000267500000000000006d90000059c4400084b170003f3640000000000000009c4')
    finished = bytes.fromhex('0000c351000000010002040000123460000000000000000000059dcc00084a750003f3360000000000')

    def state(self):
        weapon = weapon_tests.WeaponStateTests().recycling_state(50001, 2)
        weapon.position = (365100, 544000, 259107)
        weapon.equipped_throwables = {5: (50001, 2)}
        weapon.known_equipped_throwable_slots.add(5)
        weapon.hand_slot = 5
        return weapon

    def test_real_native_request_finish_and_sync_shapes(self):
        request, finished = decode_throw(self.request), decode_finish(self.finished)
        self.assertEqual((request.definition, request.identifier, request.speed), (50001, 0, 2500))
        self.assertEqual(finished.actors, (0x2040000123460,))
        self.assertEqual((finished.actor_fields, finished.entities), ((), ()))
        self.assertEqual(finished.point, (368076, 543349, 258870))
        launch, final = launch_broadcast(request, 123, 456), finish_broadcast(finished, 123, 456)
        self.assertEqual((len(launch), len(final)), (54, 41))
        self.assertEqual(struct.unpack_from('>Q', launch, 8)[0], 123)
        self.assertEqual(struct.unpack_from('>Q', final, 21)[0], 123)
        self.assertEqual(struct.unpack_from('>I', final, 37)[0], 456)

    def test_one_consumption_fuse_then_one_finish(self):
        weapon, actions = self.state(), ThrowableActions()
        before = weapon.bag_weight_hundredths()
        replies, event = actions.launch(weapon, self.request, 100)
        self.assertEqual(event['action'], 'throw_started')
        self.assertEqual(weapon.equipped_throwables[5], (50001, 1))
        self.assertEqual(weapon.bag_weight_hundredths(), before-1200)
        self.assertEqual(replies[0], (0x1005, struct.pack('>III',50001,0,0)))
        self.assertEqual(actions.launch(weapon,self.request,101)[1]['reason'], 'duplicate_identifier')
        self.assertEqual(actions.finish(self.finished,123,102)[1]['reason'], 'throw_fuse_window')
        replies, event, finished = actions.finish(self.finished,123,105)
        self.assertEqual(event['action'], 'throw_finished')
        self.assertEqual([code for code,_ in replies], [0x1008,0x1009])
        self.assertIsNotNone(finished)
        self.assertEqual(actions.finish(self.finished,123,106)[1]['reason'], 'unknown_or_completed_throw')
        self.assertEqual(weapon.equipped_throwables[5], (50001,1))
        self.assertFalse(actions.pending)

    def test_rejected_launch_is_atomic_and_does_not_grant_from_bag(self):
        for reason, alter in [('throw_not_in_hand',lambda w:setattr(w,'hand_slot',1)),
                              ('reload_pending',lambda w:setattr(w,'pending_reload',{'slot':1})),
                              ('throw_origin',lambda w:setattr(w,'position',(1,2,3)))]:
            weapon=self.state();alter(weapon);before=weapon.inventory_records()
            replies,event=ThrowableActions().launch(weapon,self.request,100)
            self.assertEqual(event['reason'],reason)
            self.assertEqual(weapon.inventory_records(),before)
            self.assertEqual(struct.unpack('>III',replies[0][1])[-1],1)
        weapon=self.state();weapon.equipped_throwables.clear();weapon.throwables[50001]=2
        self.assertEqual(ThrowableActions().launch(weapon,self.request,100)[1]['reason'],'throw_not_in_hand')

    def test_malformed_arrays_and_unknown_or_displaced_finish(self):
        for body in [self.request[:-1],self.request+b'\0',bytes(51)]:
            with self.assertRaises(ValueError):decode_throw(body)
        for body in [self.finished[:-1],self.finished+b'\0',struct.pack('>II',50001,121),
                     struct.pack('>III',50001,0,121),struct.pack('>IIII',50001,0,0,301)]:
            with self.assertRaises(ValueError):decode_finish(body)
        actions=ThrowableActions();weapon=self.state();actions.launch(weapon,self.request,100)
        bad=bytearray(self.finished);struct.pack_into('>3i',bad,24,1,2,3)
        self.assertEqual(actions.finish(bytes(bad),123,105)[1]['reason'],'throw_final_position')
        self.assertIn(0,actions.pending)
        self.assertEqual(actions.expire(111),[0])
        self.assertEqual(weapon.equipped_throwables[5],(50001,1))
        self.assertEqual(actions.finish(self.finished,123,111)[1]['reason'],'unknown_or_completed_throw')

    def test_diagnostic_area_damage_requires_type_radius_and_reported_target(self):
        actor=ActorState(ActorFixture(123,bytes(64),bytes(1100),bytes(64),(368076,543349,258870),
                                     ((368076,543349,258870),),0,1000,20,collision_boxes=(),armor_definition=201001,
                                     armor_durability=30,armor_absorb_percent=50))
        actor.started=True
        weapon=self.state();weapon.fixture=replace(weapon.fixture,throwable_actions=True,diagnostic_frag_damage=100)
        endpoint=Endpoint.__new__(Endpoint);recorded=[]
        endpoint.capture=SimpleNamespace(record=lambda *a,**kw:recorded.append(kw))
        endpoint.send_application_batch=lambda *a:None
        state={'weapon':weapon,'target_actor':actor,'actor_uid':999}
        finish=replace(decode_finish(self.finished),actors=(123,))
        endpoint.apply_diagnostic_grenade(None,None,state,replace(finish,definition=50002))
        endpoint.apply_diagnostic_grenade(None,None,state,replace(finish,point=(1,2,3)))
        endpoint.apply_diagnostic_grenade(None,None,state,replace(finish,actors=(456,)))
        self.assertEqual((actor.hp,actor.armor_durability),(1000,30))
        endpoint.apply_diagnostic_grenade(None,None,state,finish)
        self.assertEqual((actor.hp,actor.armor_durability),(930,0))
        self.assertFalse(recorded[-1]['original_damage_formula'])

    def test_diagnostic_area_damage_obstacle_and_death(self):
        fixture=ActorFixture(123,bytes(64),bytes(1100),bytes(64),(100,0,0),((100,0,0),),
                             0,1000,20,collision_boxes=(((40,-10,-10),(60,10,10)),))
        actor=ActorState(fixture);actor.started=True
        weapon=self.state();weapon.fixture=replace(weapon.fixture,throwable_actions=True,diagnostic_frag_damage=1000)
        endpoint=Endpoint.__new__(Endpoint);recorded=[];packets=[]
        endpoint.capture=SimpleNamespace(record=lambda *a,**kw:recorded.append(kw))
        endpoint.send_application_batch=lambda d,r,s,p:packets.extend(p)
        state={'weapon':weapon,'target_actor':actor,'actor_uid':999}
        finish=replace(decode_finish(self.finished),actors=(123,),point=(0,0,0))
        endpoint.apply_diagnostic_grenade(None,None,state,finish)
        self.assertEqual(actor.hp,1000)
        actor.fixture=replace(fixture,collision_boxes=())
        endpoint.apply_diagnostic_grenade(None,None,state,finish)
        self.assertEqual(actor.hp,0)
        self.assertIn((0x533,struct.pack('>IQ',0,123)),packets)
        endpoint.apply_diagnostic_grenade(None,None,state,finish)
        self.assertEqual(recorded[-1]['reason'],'target_not_alive')
        for damage in (True,0,1001,1.5):
            with self.assertRaises(ValueError):actor.diagnostic_area_damage(damage)


if __name__ == '__main__':
    unittest.main()
