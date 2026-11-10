"""Tests for the Force Stop 2.0 state machine (StarPilot force_stop.py port).

Pins the properties that matter for a control-path module: the approach
ceiling math, commitment after the timer, the standstill hold and the driver
release, the light-clear release, and the frame-timestamp guards.
"""
import unittest

from openpilot.sunnypilot.selfdrive.controls.lib.force_stop import (
  MODEL_APPROACH_DECEL,
  STANDSTILL_HOLD_NS,
  StopFrame,
  StopTune,
  ForceStop,
  vehicle_tune,
)

SEC = 1_000_000_000
MODEL_START = 1_000_000_000_000


def make_frame(**overrides) -> StopFrame:
  base = dict(
    model_ns=MODEL_START, speed_mps=15.0, horizon_m=80.0, light=True,
    raw_model_stopped=False, model_should_stop=False, standstill=False,
    enabled=True, pedal_override=False, tracking_lead=False,
    lead_present=False, lead_distance_m=500.0, lead_speed_mps=15.0,
    driving_in_curve=False, road_curvature=0.0, blinker=False,
    steering_angle_deg=0.0,
  )
  base.update(overrides)
  return StopFrame(**base)


class FakeStopClock:
  """Steps the model timestamp in 50 ms ticks (the model rate ForceStop expects)."""

  def __init__(self):
    self.t = MODEL_START

  def tick(self, seconds=0.05):
    self.t += int(seconds * SEC)
    return self.t


class TestApproach(unittest.TestCase):
  def test_light_approach_sets_a_ceiling_below_current_speed(self):
    """A red light 80 m ahead: the approach ceiling from the 0.65 m/s^2
    profile over (80 - 6) m is far below 15 m/s."""
    policy = ForceStop()
    clock = FakeStopClock()
    plan = policy.step(make_frame(model_ns=clock.tick()), StopTune())
    self.assertIsNotNone(plan.speed_ceiling_mps)
    expected = (2 * MODEL_APPROACH_DECEL * (80.0 - 6.0)) ** 0.5
    self.assertAlmostEqual(plan.speed_ceiling_mps, expected, places=6)
    self.assertFalse(plan.forcing)
    self.assertAlmostEqual(plan.approach_distance_m, 80.0)

  def test_persistent_light_commits_after_the_timer(self):
    """The 0.5 s commitment timer runs only while the light path is active;
    after it, the plan is committed (forcing) with a tracked distance."""
    policy = ForceStop()
    clock = FakeStopClock()
    for _ in range(30):
      plan = policy.step(make_frame(model_ns=clock.tick()), StopTune())
    self.assertTrue(plan.forcing)
    self.assertGreater(plan.tracked_distance_m, 0.0)
    self.assertIsNotNone(plan.obstacle_m)
    self.assertAlmostEqual(plan.jerk_scale, StopTune().jerk_scale)

  def test_ceiling_stays_within_approach_physics(self):
    """The committed ceiling never exceeds the approach physics, and the
    tracked distance re-anchors to the model horizon while far from the
    handoff (StarPilot's designed sawtooth), so monotonicity is NOT asserted."""
    policy = ForceStop()
    clock = FakeStopClock()
    bound = (2 * MODEL_APPROACH_DECEL * (80.0 - 6.0)) ** 0.5
    for _ in range(40):
      plan = policy.step(make_frame(model_ns=clock.tick()), StopTune())
      if plan.speed_ceiling_mps is not None:
        self.assertLessEqual(plan.speed_ceiling_mps, bound + 1e-6)
      if plan.forcing:
        self.assertGreaterEqual(plan.tracked_distance_m, 0.0)


class TestHoldAndRelease(unittest.TestCase):
  def test_standstill_holds_then_releases_after_timeout(self):
    policy = ForceStop()
    clock = FakeStopClock()
    for _ in range(30):
      policy.step(make_frame(model_ns=clock.tick()), StopTune())
    # roll to a standstill in the committed scene: the hold latches
    plan = policy.step(make_frame(model_ns=clock.tick(), standstill=True, speed_mps=0.0), StopTune())
    self.assertTrue(plan.manual_hold)
    self.assertEqual(plan.speed_ceiling_mps, 0.0)
    # no pedal: the 2 s hold expires and releases (with a 10 s re-entry veto)
    clock.tick(STANDSTILL_HOLD_NS / SEC)
    plan = policy.step(make_frame(model_ns=clock.tick(), standstill=True, speed_mps=0.0), StopTune())
    self.assertFalse(plan.manual_hold)

  def test_driver_pedal_releases_the_hold_immediately(self):
    policy = ForceStop()
    clock = FakeStopClock()
    for _ in range(30):
      policy.step(make_frame(model_ns=clock.tick()), StopTune())
    policy.step(make_frame(model_ns=clock.tick(), standstill=True, speed_mps=0.0), StopTune())
    plan = policy.step(make_frame(model_ns=clock.tick(), standstill=True, speed_mps=0.0,
                                  pedal_override=True), StopTune())
    self.assertFalse(plan.manual_hold)

  def test_light_clear_releases_the_commitment(self):
    policy = ForceStop()
    clock = FakeStopClock()
    for _ in range(30):
      policy.step(make_frame(model_ns=clock.tick()), StopTune())
    self.assertTrue(policy.forcing)
    # light goes green and the model reports a clear 200 m horizon
    for _ in range(15):  # the 0.5 s light-clear confirmation
      plan = policy.step(make_frame(model_ns=clock.tick(), light=False, horizon_m=200.0), StopTune())
    self.assertFalse(policy.forcing)


class TestGuards(unittest.TestCase):
  def test_disabled_resets(self):
    policy = ForceStop()
    clock = FakeStopClock()
    for _ in range(30):
      policy.step(make_frame(model_ns=clock.tick()), StopTune())
    self.assertTrue(policy.forcing)
    plan = policy.step(make_frame(model_ns=clock.tick(), enabled=False), StopTune())
    self.assertFalse(plan.forcing)
    self.assertIsNone(plan.speed_ceiling_mps)
    # a backward model timestamp on a running machine resets it (empty plan)
    clock.tick(1.0)
    for _ in range(5):
      policy.step(make_frame(model_ns=clock.tick()), StopTune())
    stale_ns = clock.t - int(2.0 * SEC)  # > 250 ms in the past
    plan = policy.step(make_frame(model_ns=stale_ns), StopTune())
    self.assertEqual(plan.model_ns, 0)
    # non-finite speed resets
    plan = policy.step(make_frame(model_ns=clock.tick(), speed_mps=float("nan")), StopTune())
    self.assertEqual(plan.model_ns, 0)

  def test_lead_veto_blocks_engagement(self):
    policy = ForceStop()
    clock = FakeStopClock()
    for _ in range(40):
      plan = policy.step(make_frame(model_ns=clock.tick(), lead_present=True,
                                    lead_distance_m=30.0, lead_speed_mps=10.0,
                                    tracking_lead=True), StopTune())
    self.assertFalse(plan.forcing)
    self.assertIsNone(plan.speed_ceiling_mps)

  def test_vehicle_tune_table(self):
    self.assertEqual(vehicle_tune('TOYOTA_CAMRY_TSS2').handoff_m, 4.5)
    self.assertEqual(vehicle_tune('HYUNDAI_ELANTRA_2021').jerk_scale, 0.8)
    self.assertEqual(vehicle_tune('HYUNDAI_SANTA_FE_2022').low_speed_hold_mps, 2.5)
    self.assertEqual(vehicle_tune('UNKNOWN_CAR').handoff_m, 6.0)


if __name__ == "__main__":
  unittest.main()
