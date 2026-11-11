import numpy as np

from openpilot.common.test import OpenpilotTestCase
from openpilot.common.parameterized import parameterized
from openpilot.sunnypilot.selfdrive.controls.lib.longitudinal_braking_gap import LeadComfortState, braking_gap_reference


def update(state, **kwargs):
  args = {'enabled': True, 'track_id': 43, 'dt': .05, 'distance': 20., 'relative_speed': -.5}
  args.update(kwargs)
  state.update(**args)



class TestLongitudinalBrakingGapTests(OpenpilotTestCase):

  @parameterized.expand([{'enabled': False}, {'track_id': 44}, {'distance': 100.},
                                      {'relative_speed': float('nan')}, {'dt': .3}], names=('change',))
  def test_lost_replaced_or_jumped_track_cannot_inherit_comfort_eligibility(self, change):
    state = LeadComfortState()
    for _ in range(40):
      update(state)
    state.relief = 1.
    update(state, **change)
    assert state.age <= .05
    assert state.relief == 0.


def relief(state, **changes):
  args = {'dt': .05, 'enabled': True, 'base_tf': 1.1, 'ego_speeds': np.full(13, 20.), 'lead_speeds': np.full(13, 19.),
              'lead_accel': -1., 'physical_gaps': np.full(13, 40.), 'danger_margins': np.full(13, 10.),
              'times': np.linspace(0, 10, 13), 'stop_distance': 5.}
  args.update(changes)
  return state.comfort_relief(**args)


  def test_comfort_allowance_is_bounded_and_danger_withdraws_it_immediately(self):
    state = LeadComfortState()
    state.age, state.distance, state.relative_speed = 2., 40., -1.
    for _ in range(20):
      result = relief(state)
    np.testing.assert_allclose(result, 8.)
    assert not relief(state, danger_margins=np.full(13, -1.)).any()
    assert state.relief == 0.


  @parameterized.expand([{'base_tf': .45}, {'enabled': False}, {'lead_speeds': np.zeros(13)},
                                      {'physical_gaps': np.full(13, 10.)}, {'lead_accel': 0.}], names=('change',))
  def test_short_gap_stopped_lead_and_invalid_eligibility_never_get_relief(self, change):
    state = LeadComfortState()
    state.age, state.distance, state.relative_speed = 2., 40., -1.
    assert not relief(state, **change).any()


  def test_slack_does_not_move_physical_obstacles_or_relax_another_obstacle(self):
    obstacles = np.array([[50., 30., 100.], [20., 30., 19.]])
    original = obstacles.copy()
    result = braking_gap_reference(obstacles, np.array([[-5., 0.], [-5., -5.]]), np.array([20., 20.]))
    np.testing.assert_array_equal(obstacles, original)
    np.testing.assert_array_equal(result, 0.)


  @parameterized.expand(['danger_margins', 'physical_gaps', 'ego_speeds'], names=('field',))
  def test_nonfinite_prediction_withdraws_comfort_relief(self, field):
    state = LeadComfortState()
    state.age, state.distance, state.relative_speed = 2., 40., -1.
    relief(state)
    assert state.relief > 0.
    assert not relief(state, **{field: np.full(13, np.nan)}).any()
