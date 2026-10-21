import unittest
from unittest.mock import Mock

from openpilot.sunnypilot.common.lateral_arbitration_params import read_lateral_arbitration_state

STOCK_STEER_RATIO = 16.8
STOCK_FRICTION = 0.3
STOCK_LAT_ACCEL = 1.5


def make_params(values: dict) -> Mock:
  """A Params stand-in that returns the given values and False for bools."""
  params = Mock()
  bools = {k: v for k, v in values.items() if isinstance(v, bool)}
  floats = {k: v for k, v in values.items() if not isinstance(v, bool)}

  def get_float(key, return_default=False):
    if key in floats:
      return floats[key]
    return 0.0

  params.get_float.side_effect = get_float
  params.get_bool.side_effect = lambda key: bools.get(key, False)
  return params


class TestReadLateralArbitrationState(unittest.TestCase):
  def read(self, values: dict, is_torque_car: bool = True):
    return read_lateral_arbitration_state(
      make_params(values),
      stock_steer_ratio=STOCK_STEER_RATIO,
      stock_friction=STOCK_FRICTION,
      stock_lat_accel_factor=STOCK_LAT_ACCEL,
      is_torque_car=is_torque_car,
    )

  def test_defaults_keep_the_learning_path(self):
    state = self.read({})
    self.assertFalse(state.use_custom_steer_ratio)
    self.assertFalse(state.use_custom_friction)
    self.assertFalse(state.use_custom_lat_accel_factor)
    self.assertFalse(state.force_auto_tune)
    self.assertFalse(state.force_auto_tune_off)

  def test_custom_sr_is_scaled_by_one_tenth(self):
    # The UI knob is an integer: 168 means a 16.8 ratio.
    state = self.read({"CustomSR": 168})
    self.assertTrue(state.use_custom_steer_ratio)
    self.assertAlmostEqual(state.user_steer_ratio, 16.8)

  def test_custom_sr_below_the_threshold_is_ignored(self):
    # 10 -> 1.0 after scaling, which resolve_vehicle_model_steer_ratio also
    # rejects, so it must not count as a user choice.
    state = self.read({"CustomSR": 10})
    self.assertFalse(state.use_custom_steer_ratio)
    self.assertAlmostEqual(state.user_steer_ratio, STOCK_STEER_RATIO)

  def test_steer_ratio_param_is_absolute(self):
    state = self.read({"SteerRatio": 15.5})
    self.assertTrue(state.use_custom_steer_ratio)
    self.assertAlmostEqual(state.user_steer_ratio, 15.5)

  def test_custom_sr_wins_over_the_steer_ratio_param(self):
    state = self.read({"CustomSR": 168, "SteerRatio": 15.5})
    self.assertAlmostEqual(state.user_steer_ratio, 16.8)

  def test_friction_edit_locks_the_learned_value(self):
    state = self.read({"SteerFriction": 0.45})
    self.assertTrue(state.use_custom_friction)
    self.assertAlmostEqual(state.user_friction, 0.45)

  def test_friction_at_the_stock_value_keeps_the_learned_value(self):
    state = self.read({"SteerFriction": STOCK_FRICTION})
    self.assertFalse(state.use_custom_friction)

  def test_force_auto_tune_off_locks_everything(self):
    state = self.read({"ForceAutoTuneOff": True})
    self.assertTrue(state.use_custom_friction)
    self.assertTrue(state.use_custom_lat_accel_factor)
    self.assertTrue(state.use_custom_steer_ratio)

  def test_force_auto_tune_suppresses_user_edits(self):
    state = self.read({"ForceAutoTune": True, "SteerFriction": 0.45})
    self.assertFalse(state.use_custom_friction)

  def test_non_torque_car_cannot_lock_friction(self):
    state = self.read({"SteerFriction": 0.45}, is_torque_car=False)
    self.assertFalse(state.use_custom_friction)

  def test_steer_ratio_can_be_locked_on_a_non_torque_car(self):
    state = self.read({"CustomSR": 168}, is_torque_car=False)
    self.assertTrue(state.use_custom_steer_ratio)

  def test_auto_steer_delay_toggle_is_reported(self):
    state = self.read({"UseAutoSteerDelay": False})
    self.assertTrue(state.use_custom_steer_actuator_delay)
    state = self.read({"UseAutoSteerDelay": True})
    self.assertFalse(state.use_custom_steer_actuator_delay)


if __name__ == "__main__":
  unittest.main()
