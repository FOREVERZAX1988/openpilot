"""Tests for the driving-mode smoother (StarPilot ProfileSmoother port).

Covers:
  * bounded-rate fade of the mode-derived accel/comfort factors,
  * transitions starting from stock (never from the previous target),
  * steady-state collapse to stock (applied history cleared),
  * invalid-input reset to stock,
  * CarrotPlanner._sample_mode_factors mapping + instant proximity min(),
  * the jerk-factor fade via the planner property (per-tick gated).
"""
import unittest

from openpilot.common.test import OpenpilotTestCase

from openpilot.sunnypilot.carrot.carrot_functions import (
  ACCEL_STEP_RATE,
  DrivingMode,
  DrivingModeSmoother,
  JERK_STEP_RATE,
  ModeComfortFactors,
  STOCK_FACTORS,
  move_toward,
)
from openpilot.sunnypilot.carrot.config import UnifiedParams

DT = 0.05  # DT_MDL


def _make_planner():
  from openpilot.sunnypilot.carrot.carrot_functions import CarrotPlanner
  return CarrotPlanner(UnifiedParams())


class TestMoveToward(OpenpilotTestCase):
  def test_bounded_both_directions(self):
    self.assertEqual(move_toward(1.0, 0.8, 0.05), 0.95)
    self.assertEqual(move_toward(1.0, 0.8, 1.0), 0.8)  # clamped, no overshoot
    self.assertAlmostEqual(move_toward(0.8, 1.0, 0.05), 0.85)
    self.assertEqual(move_toward(0.5, 0.5, 0.05), 0.5)


class TestDrivingModeSmoother(OpenpilotTestCase):
  def test_fades_at_bounded_rate(self):
    s = DrivingModeSmoother()
    safe = ModeComfortFactors(0.8, 0.9)
    applied = s.sample(safe, DT)
    self.assertAlmostEqual(applied.accel_factor, 1.0 - ACCEL_STEP_RATE * DT)
    self.assertAlmostEqual(applied.comfort_brake_factor, 1.0 - ACCEL_STEP_RATE * DT)
    self.assertIsNotNone(s.applied)

  def test_converges_then_collapses_to_stock(self):
    s = DrivingModeSmoother()
    safe = ModeComfortFactors(0.8, 0.9)
    for _ in range(200):
      applied = s.sample(safe, DT)
    self.assertEqual(applied, safe)
    self.assertIsNotNone(s.applied)
    # back to stock: fades, then the applied history collapses
    for _ in range(200):
      applied = s.sample(STOCK_FACTORS, DT)
    self.assertEqual(applied, STOCK_FACTORS)
    self.assertIsNone(s.applied)
    # stock with no history returns immediately without creating state
    self.assertEqual(s.sample(STOCK_FACTORS, DT), STOCK_FACTORS)
    self.assertIsNone(s.applied)

  def test_transition_starts_from_stock(self):
    s = DrivingModeSmoother()
    safe = ModeComfortFactors(0.8, 0.9)
    eco = ModeComfortFactors(0.9, 1.0)
    applied = s.sample(safe, DT)
    self.assertAlmostEqual(applied.accel_factor, 1.0 - ACCEL_STEP_RATE * DT)
    # switch target mid-fade: the ramp continues from the applied value,
    # never jumps to the new target nor restarts from a previous target
    applied = s.sample(eco, DT)
    self.assertAlmostEqual(applied.accel_factor, 1.0 - 2 * ACCEL_STEP_RATE * DT)

  def test_invalid_input_resets_to_stock(self):
    s = DrivingModeSmoother()
    s.sample(ModeComfortFactors(0.8, 0.9), DT)
    for bad_dt in (0.0, -0.05, 0.3, float("nan"), "x"):
      applied = s.sample(ModeComfortFactors(0.8, 0.9), bad_dt)
      self.assertEqual(applied, STOCK_FACTORS, msg=f"dt={bad_dt}")
      self.assertIsNone(s.applied)
    applied = s.sample(("not", "factors"), DT)
    self.assertEqual(applied, STOCK_FACTORS)
    self.assertIsNone(s.applied)


class TestPlannerModeFactors(OpenpilotTestCase):
  def test_steady_state_matches_old_mapping(self):
    """At convergence the faded factors equal the old instant mapping."""
    p = _make_planner()
    for mode, expected_accel in ((DrivingMode.Normal, 1.0), (DrivingMode.Eco, p._my_eco_factor),
                                 (DrivingMode.Safe, p._my_safe_mode_factor), (DrivingMode.High, 1.0)):
      p._my_driving_mode = mode
      for _ in range(200):
        p._sample_mode_factors(lead_slow=False)
      expected_comfort = 0.9 if mode == DrivingMode.Safe else 1.0
      self.assertAlmostEqual(p._my_safe_factor, expected_accel, msg=str(mode))
      self.assertAlmostEqual(p._mode_comfort_brake_factor, expected_comfort, msg=str(mode))

  def test_mode_change_fades_not_steps(self):
    p = _make_planner()
    p._my_driving_mode = DrivingMode.Normal
    p._sample_mode_factors(lead_slow=False)
    self.assertEqual(p._my_safe_factor, 1.0)
    p._my_driving_mode = DrivingMode.Safe
    p._sample_mode_factors(lead_slow=False)
    self.assertLess(p._my_safe_factor, 1.0)
    self.assertGreater(p._my_safe_factor, p._my_safe_mode_factor)  # still fading
    self.assertLess(p._mode_comfort_brake_factor, 1.0)

  def test_proximity_reduction_is_instant(self):
    """The lead-proximity safety factor must never be delayed by the fade."""
    p = _make_planner()
    p._my_driving_mode = DrivingMode.Normal
    p._sample_mode_factors(lead_slow=True)
    self.assertEqual(p._my_safe_factor, p._my_safe_mode_factor)

  def test_default_planner_has_no_fade_history(self):
    """A default (Normal) planner must be indistinguishable from before the port."""
    p = _make_planner()
    p._sample_mode_factors(lead_slow=False)
    self.assertEqual(p._my_safe_factor, 1.0)
    self.assertEqual(p._mode_comfort_brake_factor, 1.0)
    self.assertIsNone(p._mode_smoother.applied)
    self.assertAlmostEqual(p._comfort_brake, p._comfort_brake_base * 1.0)


class TestPlannerJerkFade(OpenpilotTestCase):
  def test_jerk_fades_at_star_pilot_rate(self):
    p = _make_planner()
    p._jerk_factor = 0.5
    self.assertAlmostEqual(p.jerk_factor, 1.0 - JERK_STEP_RATE * DT)
    p._frame += 1
    self.assertAlmostEqual(p.jerk_factor, 1.0 - 2 * JERK_STEP_RATE * DT)

  def test_jerk_fade_gated_per_tick(self):
    """Repeated reads within one tick must not advance the fade."""
    p = _make_planner()
    p._jerk_factor = 0.5
    first = p.jerk_factor
    for _ in range(5):
      self.assertEqual(p.jerk_factor, first)
    p._frame += 1
    self.assertLess(p.jerk_factor, first)

  def test_jerk_converges_exactly(self):
    p = _make_planner()
    p._jerk_factor = 0.5
    for _ in range(50):
      p._frame += 1
      value = p.jerk_factor
    self.assertEqual(value, 0.5)


if __name__ == "__main__":
  unittest.main()
