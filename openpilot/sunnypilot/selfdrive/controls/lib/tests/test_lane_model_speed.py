import math
import unittest

from openpilot.sunnypilot.selfdrive.controls.lib.lane_model_speed import LaneModelSpeedGuard


def warmed_guard():
  guard = LaneModelSpeedGuard(recovery_frames=20)
  for _ in range(21):
    guard.update(30.0, 30.0, 30.0)
  return guard


class TestLaneModelSpeed(unittest.TestCase):

  def test_startup_and_recovery_require_continuous_good_frames(self):
    guard = LaneModelSpeedGuard(recovery_frames=20)
    self.assertFalse(any(guard.update(30.0, 30.0, 30.0) for _ in range(20)))
    self.assertTrue(guard.update(30.0, 30.0, 30.0))
    self.assertFalse(guard.update(29.04, 9.93, 12.09))
    self.assertFalse(any(guard.update(30.0, 30.0, 30.0) for _ in range(20)))
    self.assertTrue(guard.update(30.0, 30.0, 30.0))

  def test_whole_trajectory_collapse_despite_increasing_profile(self):
    guard = warmed_guard()
    # Tucson incident: original end/start condition passes at highway speed.
    self.assertTrue(12.09 > 9.93 * 0.7)
    self.assertFalse(guard.update(104.54 / 3.6, 9.93, 12.09))
    self.assertEqual(guard.valid_frames, 0)

  def test_original_predicted_deceleration_still_blocks(self):
    guard = warmed_guard()
    self.assertFalse(guard.update(30.0, 30.0, 20.9))

  def test_usable_trajectories_and_ratio_boundary(self):
    for actual, start, end in [
      (30.0, 21.0, 21.0),
      (30.0, 30.0, 21.0),
      (10.0, 9.0, 12.0),
      (0.0, 0.0, 0.0),
      (1.0, 1.0, 2.0),
      (30.0, 32.0, 34.0),
    ]:
      with self.subTest(actual=actual, start=start, end=end):
        self.assertTrue(warmed_guard().update(actual, start, end))

  def test_invalid_or_mismatched_speeds_block_immediately(self):
    for actual, start, end in [
      (30.0, 20.999, 30.0),
      (30.0, 30.0, 20.999),
      (10.0, 0.0, 12.0),
      (math.nan, 30.0, 30.0),
      (30.0, math.nan, 30.0),
      (30.0, 30.0, math.nan),
      (math.inf, 30.0, 30.0),
      (30.0, math.inf, 30.0),
      (30.0, 30.0, math.inf),
      (-1.0, 30.0, 30.0),
      (30.0, -1.0, 30.0),
      (30.0, 30.0, -1.0),
    ]:
      with self.subTest(actual=actual, start=start, end=end):
        self.assertFalse(warmed_guard().update(actual, start, end))

  def test_intermittent_mismatch_cannot_accumulate_recovery_credit(self):
    guard = warmed_guard()
    for _ in range(10):
      self.assertFalse(guard.update(30.0, 10.0, 15.0))
      self.assertFalse(any(guard.update(30.0, 30.0, 30.0) for _ in range(19)))
    self.assertFalse(guard.update(30.0, 30.0, 30.0))
    self.assertTrue(guard.update(30.0, 30.0, 30.0))

  def test_normal_profiles_preserve_original_gate_sequence(self):
    guard = LaneModelSpeedGuard(recovery_frames=20)
    count = 0
    for i in range(1000):
      actual = 5 + (i % 40)
      start = actual * 0.95
      end = start * (0.5 if i % 71 == 0 else 1.1)
      count = 0 if end < start * 0.7 else count + 1
      self.assertEqual(guard.update(actual, start, end), count > 20)


if __name__ == "__main__":
  unittest.main()
