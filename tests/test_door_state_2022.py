"""Дверной state/границы/повтор запросов и повторный native snapshot."""
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server/directory'))
from door_state_2022 import DoorFixture, DoorState


class DoorStateTests(unittest.TestCase):
    def setUp(self):
        self.position = (415727.9375,557603.5625,259024.234375)
        self.fixture = DoorFixture({7767:(self.position,0)})
        self.state = DoorState(self.fixture)

    def request(self, status=1, identifier=7767, position=None):
        return self.state.handle(struct.pack('>II',identifier,status),self.position if position is None else position)

    def test_desired_state_repeat_does_not_toggle(self):
        for _ in range(2):
            outputs,event=self.request()
            self.assertEqual(outputs,[(0x6f55,struct.pack('>IBBBBQ',7767,1,0,0,0,0))])
            self.assertEqual(self.state.status[7767],1)
        self.assertFalse(event['changed'])
        _,event=self.request(0)
        self.assertTrue(event['changed']);self.assertEqual(self.state.status[7767],0)

    def test_second_open_direction_has_distinct_state(self):
        outputs, event = self.request(2)
        self.assertEqual(outputs[0][1][4],2)
        self.assertEqual(event['state'],2)

    def test_reject_malformed_unknown_state_far_without_mutation(self):
        for payload,pos,reason in ((b'',self.position,'length'),(struct.pack('>II',4,1),self.position,'unknown_entity'),
                                  (struct.pack('>II',7767,3),self.position,'state'),(struct.pack('>II',7767,1),None,'position'),
                                  (struct.pack('>II',7767,1),(0,0,0),'distance')):
            outputs,event=self.state.handle(payload,pos)
            self.assertEqual(outputs,[]);self.assertEqual(event['reason'],reason);self.assertEqual(self.state.status[7767],0)

    def test_snapshot_once_reentry_and_resume_preserve_state(self):
        self.assertEqual(len(self.state.snapshot(self.position)),1)
        self.assertFalse(self.state.snapshot(self.position))
        self.request()
        self.assertFalse(self.state.snapshot((0,0,0)))
        self.assertEqual(self.state.snapshot(self.position)[0][1][4],1)
        self.state.resume()
        self.assertEqual(self.state.snapshot(self.position)[0][1][4],1)

    def test_snapshot_batch_limit_without_losing_remaining(self):
        state=DoorState(DoorFixture({i:(self.position,0) for i in range(1,34)}))
        self.assertEqual([len(state.snapshot(self.position)) for _ in range(4)],[16,16,1,0])

    def test_new_session_starts_initial_closed(self):
        self.request()
        self.assertEqual(DoorState(self.fixture).status[7767],0)

    def test_fixture_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'doors.json'
            data=dict(map=16010,doors=[dict(id=7767,position_cm=list(self.position),initial_state=0)])
            path.write_text(json.dumps(data));self.assertEqual(len(DoorFixture.load(path).doors),1)
            for replacement in (dict(map=1),dict(doors=data['doors']*2),dict(interaction_radius_cm=True),dict(doors=[dict(id=1,position_cm=[float('nan'),0,0])])):
                broken=dict(data,**replacement);path.write_text(json.dumps(broken))
                with self.assertRaises(ValueError):DoorFixture.load(path)
