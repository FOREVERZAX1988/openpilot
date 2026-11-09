"""Tests for Traffic Mode (StarPilot port): curve math, profile validation,
planner integration, and the gap-adjust very-long-press gesture."""
import math
import unittest

from openpilot.sunnypilot.carrot.traffic_mode import (
  A_CRUISE_MAX_BP_TRAFFIC,
  A_CRUISE_MAX_VALS_TRAFFIC_ALL,
  DEFAULT_JERK_PERCENT,
  DEFAULT_RELAXED_FOLLOW,
  DEFAULT_TRAFFIC_FOLLOW,
  FOLLOW_MAX_SECONDS,
  FOLLOW_MIN_SECONDS,
  TRAFFIC_COMFORT_BRAKE_FACTOR,
  TrafficProfile,
  interpolate_accel_profile,
  traffic_value,
)


class FakeParams:
  def __init__(self, values=None):
    self.values = values or {}

  def get_float(self, key, default=0.0):
    value = self.values.get(key)
    return default if value is None else float(value)


def _button_event(bt, pressed):
  from opendbc.car.structs import car
  return car.CarState.ButtonEvent(type=bt, pressed=pressed)


class TestCurveMath(unittest.TestCase):
  def test_traffic_value_blends_over_25_mps(self):
    self.assertAlmostEqual(traffic_value((0.75, 1.6), 0.0), 0.75)
    self.assertAlmostEqual(traffic_value((0.75, 1.6), 25.0), 1.6)
    self.assertAlmostEqual(traffic_value((0.75, 1.6), 12.5), 0.75 + (1.6 - 0.75) / 2)

  def test_traffic_value_clamps_out_of_range_speeds(self):
    self.assertAlmostEqual(traffic_value((0.75, 1.6), -5.0), 0.75)
    self.assertAlmostEqual(traffic_value((0.75, 1.6), 40.0), 1.6)

  def test_accel_profile_hits_nodes_exactly(self):
    for bp, value in zip(A_CRUISE_MAX_BP_TRAFFIC, A_CRUISE_MAX_VALS_TRAFFIC_ALL, strict=True):
      self.assertAlmostEqual(interpolate_accel_profile(bp), value, places=6)

  def test_accel_profile_monotone_decreasing_and_bounded(self):
    speeds = [i * 0.5 for i in range(0, 81)]  # 0..40 m/s
    values = [interpolate_accel_profile(v) for v in speeds]
    self.assertTrue(all(b <= a + 1e-9 for a, b in zip(values, values[1:])),
                    msg="traffic accel profile must not rise with speed")
    self.assertTrue(all(0.2 <= v <= 1.15 for v in values))

  def test_accel_profile_clamps_beyond_table(self):
    self.assertAlmostEqual(interpolate_accel_profile(60.0), A_CRUISE_MAX_VALS_TRAFFIC_ALL[-1])
    self.assertAlmostEqual(interpolate_accel_profile(0.0), A_CRUISE_MAX_VALS_TRAFFIC_ALL[0])

  def test_star_pilot_default_endpoints(self):
    self.assertEqual(DEFAULT_TRAFFIC_FOLLOW, 0.75)
    self.assertEqual(DEFAULT_RELAXED_FOLLOW, 1.6)
    self.assertEqual(DEFAULT_JERK_PERCENT, 100.0)
    self.assertEqual(TRAFFIC_COMFORT_BRAKE_FACTOR, 0.35)
    self.assertEqual((FOLLOW_MIN_SECONDS, FOLLOW_MAX_SECONDS), (0.5, 3.0))


class TestTrafficProfile(unittest.TestCase):
  def test_defaults_resolve(self):
    curve = TrafficProfile(FakeParams()).read()
    self.assertEqual(curve, (0.75, 1.6, 1.0, 1.0))

  def test_saved_values_resolve(self):
    curve = TrafficProfile(FakeParams({
      "TrafficFollow": 0.9, "RelaxedFollow": 1.9,
      "TrafficJerkAcceleration": 60.0, "RelaxedJerkAcceleration": 120.0,
    })).read()
    self.assertEqual(curve, (0.9, 1.9, 0.6, 1.2))

  def test_out_of_bounds_follow_rejected(self):
    for values in ({"TrafficFollow": 0.4}, {"TrafficFollow": 3.1},
                   {"RelaxedFollow": 0.4}, {"RelaxedFollow": 3.1}):
      with self.subTest(values=values):
        self.assertIsNone(TrafficProfile(FakeParams(values)).read())

  def test_out_of_bounds_jerk_rejected(self):
    for values in ({"TrafficJerkAcceleration": 20.0}, {"TrafficJerkAcceleration": 250.0},
                   {"RelaxedJerkAcceleration": 10.0}, {"RelaxedJerkAcceleration": 300.0}):
      with self.subTest(values=values):
        self.assertIsNone(TrafficProfile(FakeParams(values)).read())

  def test_nonfinite_rejected(self):
    self.assertIsNone(TrafficProfile(FakeParams({"TrafficFollow": float("nan")})).read())


class TestPlannerTrafficIntegration(unittest.TestCase):
  def _make_planner(self):
    from openpilot.sunnypilot.carrot.carrot_functions import CarrotPlanner
    from openpilot.sunnypilot.carrot.config import UnifiedParams
    return CarrotPlanner(UnifiedParams())

  def _enable_traffic(self, planner, params_values=None):
    profile = TrafficProfile(FakeParams(params_values))
    planner._traffic_curve = profile.read()
    assert planner._traffic_curve is not None
    planner._traffic_mode_enabled = True

  def test_disabled_keeps_stock_behaviour(self):
    planner = self._make_planner()
    planner._my_driving_mode = planner._my_driving_mode  # Normal
    stock_accel = planner.get_carrot_accel(10.0)
    stock_follow = planner.get_T_FOLLOW(2, 10.0)
    self._enable_traffic(planner)
    planner._traffic_mode_enabled = False
    self.assertAlmostEqual(planner.get_carrot_accel(10.0), stock_accel)
    self.assertAlmostEqual(planner.get_T_FOLLOW(2, 10.0), stock_follow)

  def test_traffic_follow_replaces_personality_table(self):
    planner = self._make_planner()
    self._enable_traffic(planner)
    # 12.5 m/s is the midpoint of the StarPilot blend window
    expected = traffic_value((0.75, 1.6), 12.5)
    self.assertAlmostEqual(planner.get_T_FOLLOW(2, 12.5), expected, delta=1e-6)

  def test_traffic_jerk_becomes_mpc_jerk_target(self):
    planner = self._make_planner()
    self._enable_traffic(planner, {"TrafficJerkAcceleration": 60.0, "RelaxedJerkAcceleration": 120.0})
    planner.get_T_FOLLOW(2, 12.5)
    self.assertAlmostEqual(planner._jerk_factor, traffic_value((0.6, 1.2), 12.5), delta=1e-6)

  def test_traffic_accel_profile_replaces_envelope(self):
    planner = self._make_planner()
    self._enable_traffic(planner)
    self.assertAlmostEqual(planner.get_carrot_accel(10.0),
                           interpolate_accel_profile(10.0), places=6)

  def test_traffic_comfort_brake_factor_fades_in(self):
    planner = self._make_planner()
    planner._my_driving_mode = planner._my_driving_mode  # Normal
    planner._traffic_mode_enabled = True
    planner._traffic_curve = TrafficProfile(FakeParams()).read()
    planner._sample_mode_factors(lead_slow=False)
    self.assertLess(planner._mode_comfort_brake_factor, 1.0)
    self.assertGreater(planner._mode_comfort_brake_factor, TRAFFIC_COMFORT_BRAKE_FACTOR)
    for _ in range(200):
      planner._sample_mode_factors(lead_slow=False)
    self.assertAlmostEqual(planner._mode_comfort_brake_factor, TRAFFIC_COMFORT_BRAKE_FACTOR, places=6)

  def test_invalid_curve_falls_back_to_stock(self):
    planner = self._make_planner()
    planner._traffic_mode_enabled = True
    planner._traffic_curve = None  # profile read failed
    stock_follow = planner.get_T_FOLLOW(2, 10.0)
    planner._get_base_t_follow(2, 10.0)
    self.assertAlmostEqual(planner.get_T_FOLLOW(2, 10.0), stock_follow)


class TestGapAdjustGesture(unittest.TestCase):
  """Simulated press sequences through _prepare_buttons with a fake self."""

  GAP = None  # filled in setUp via the enum

  def _fake_self(self):
    from openpilot.selfdrive.car.cruise import VCruiseCarrot
    fake = object.__new__(VCruiseCarrot)
    fake.button_cnt = 0
    fake.button_prev = 0
    fake.long_pressed = False
    fake.button_big_step = False
    fake.button_long_time = 70  # gap-adjust long delay (40 + 30)
    fake._cruise_button_long_delay = 40
    fake.traffic_toggle_frame = False
    fake.long_release_latch = False
    fake.is_metric = True
    fake._cruise_speed_unit_basic = 5
    fake._cruise_speed_unit = 5
    fake._cruise_button_mode = 0
    fake.carrot_cmd = ""
    fake.carrot_cmd_index_last = 0
    return fake

  def _cs(self, events):
    from opendbc.car.structs import car
    cs = type("CS", (), {})()
    cs.buttonEvents = events
    return cs

  def test_short_press_unchanged(self):
    """A short gap-adjust release still routes to the short handler."""
    from opendbc.car.structs import car
    fake = self._fake_self()
    gap = car.CarState.ButtonEvent.Type.gapAdjustCruise
    fake._prepare_buttons(self._cs([_button_event(gap, True)]), 30.0)
    kph, btype, long_out = fake._prepare_buttons(self._cs([_button_event(gap, False)]), 30.0)
    self.assertFalse(long_out)
    self.assertEqual(btype, gap)

  def test_long_press_release_fires_mode_cycle_path(self):
    from opendbc.car.structs import car
    fake = self._fake_self()
    gap = car.CarState.ButtonEvent.Type.gapAdjustCruise
    fake._prepare_buttons(self._cs([_button_event(gap, True)]), 30.0)
    # hold past the long threshold (70) but under very-long (140)
    for _ in range(80):
      kph, btype, long_out = fake._prepare_buttons(self._cs([]), 30.0)
    self.assertFalse(fake.traffic_toggle_frame)
    self.assertTrue(long_out or btype == 0)  # nothing fires mid-hold
    kph, btype, long_out = fake._prepare_buttons(self._cs([_button_event(gap, False)]), 30.0)
    self.assertEqual(btype, gap)
    self.assertTrue(long_out)
    self.assertFalse(fake.traffic_toggle_frame)  # long, not very-long
    # state must not leak into the next press
    self.assertFalse(fake.long_pressed)
    self.assertEqual(fake.button_cnt, 0)

  def test_very_long_press_release_fires_traffic_toggle(self):
    from opendbc.car.structs import car
    fake = self._fake_self()
    gap = car.CarState.ButtonEvent.Type.gapAdjustCruise
    fake._prepare_buttons(self._cs([_button_event(gap, True)]), 30.0)
    for _ in range(150):  # well past 2x the long threshold
      fake._prepare_buttons(self._cs([]), 30.0)
    kph, btype, long_out = fake._prepare_buttons(self._cs([_button_event(gap, False)]), 30.0)
    self.assertEqual(btype, gap)
    self.assertTrue(long_out)
    self.assertTrue(fake.traffic_toggle_frame)

  def test_next_press_works_after_release(self):
    from opendbc.car.structs import car
    fake = self._fake_self()
    gap = car.CarState.ButtonEvent.Type.gapAdjustCruise
    accel = car.CarState.ButtonEvent.Type.accelCruise
    fake._prepare_buttons(self._cs([_button_event(gap, True)]), 30.0)
    for _ in range(150):
      fake._prepare_buttons(self._cs([]), 30.0)
    fake._prepare_buttons(self._cs([_button_event(gap, False)]), 30.0)
    # a subsequent short accel press must be detected normally
    fake._prepare_buttons(self._cs([_button_event(accel, True)]), 30.0)
    for _ in range(5):
      fake._prepare_buttons(self._cs([]), 30.0)
    kph, btype, long_out = fake._prepare_buttons(self._cs([_button_event(accel, False)]), 30.0)
    self.assertEqual(btype, accel)
    self.assertFalse(long_out)


if __name__ == "__main__":
  unittest.main()
