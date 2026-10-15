"""Бюджет реального пути, отказ без мутации и явная смена server anchor."""
import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'server/directory'))
from movement_validation_2022 import MovementLimits, MovementState


def request(*points, floats=(0,0,0)):
    return dict(points=[dict(position=p, value=0xffffffff) for p in points], floats=floats)


class MovementTests(unittest.TestCase):
    def test_repeated_packets_do_not_grant_a_new_burst(self):
        state = MovementState(MovementLimits(), (0,0,0), 100)
        self.assertTrue(state.accept(request((10000,0,0)),100)[0])
        before = (state.position,state.updated_at,state.horizontal_budget,state.vertical_budget)
        self.assertFalse(state.accept(request((10001,0,0)),100)[0])
        self.assertEqual((state.position,state.updated_at,state.horizontal_budget,state.vertical_budget),before)
        self.assertTrue(state.accept(request((10050,0,0)),100.01)[0])
        self.assertFalse(state.accept(request((10051,0,0)),100.01)[0])

    def test_history_path_cannot_hide_an_out_and_back_jump(self):
        state = MovementState(MovementLimits(), (0,0,0), 0)
        accepted, info = state.accept(request((10000,0,0),(0,0,0)),1)
        self.assertFalse(accepted)
        self.assertEqual(info['horizontal_cm'],20000)
        self.assertEqual(state.position,(0,0,0))
        self.assertTrue(state.accept(request((500,0,0),(1000,0,0)),1)[0])

    def test_idle_credit_is_bounded_and_axes_have_independent_budgets(self):
        state = MovementState(MovementLimits(), (0,0,0), 0)
        self.assertFalse(state.accept(request((10001,0,0)),1000)[0])
        self.assertFalse(state.accept(request((0,0,40001)),1000)[0])
        self.assertEqual(state.updated_at,0)
        self.assertTrue(state.accept(request((10000,0,40000)),1000)[0])
        self.assertEqual((state.horizontal_budget,state.vertical_budget),(0,0))

    def test_invalid_orientation_time_and_empty_points_do_not_change_anchor(self):
        state = MovementState(MovementLimits(), (1,2,3), 10)
        for movement, now in [(request((2,2,3),floats=(float('nan'),0,0)),11),
                              (request((2,2,3)),9), (request((2,2,3)),float('inf'))]:
            self.assertFalse(state.accept(movement,now)[0])
            self.assertEqual((state.position,state.updated_at),((1,2,3),10))
        self.assertTrue(state.accept(request(),100)[0])
        self.assertEqual((state.position,state.updated_at),((1,2,3),10))

    def test_explicit_authorized_reset_and_invalid_limits(self):
        state = MovementState(MovementLimits(), (0,0,0), 0)
        state.reset((1000000,2000000,3000000),10)
        self.assertTrue(state.accept(request((1000500,2000000,3000000)),10)[0])
        for value in (None,True,{'extra':1},{'burst_seconds':True},
                      {'burst_seconds':float('nan')},{'horizontal_speed_cm_s':1}):
            with self.assertRaises(ValueError): MovementLimits.load(value)
