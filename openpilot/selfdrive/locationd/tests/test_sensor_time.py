#!/usr/bin/env python3
"""What a late frame costs, and what a broken timebase costs.

`locationdTemporaryError` follows deviceMotion.inputsOK, which follows the
per-service invalid counter. A frame whose stamp is far from its publish time is
dropped -- that is a transport hiccup, and a handful of them per drive must not
latch the alert for the rest of it. A timebase that is actually wrong must still
latch, and a wrong *sample* (INPUT_INVALID) must count at once.
"""
from collections import defaultdict
import unittest

import numpy as np

from openpilot.cereal import log
from openpilot.common.test import OpenpilotTestCase
from openpilot.selfdrive.locationd.locationd import (
  CAM_ODO_POSE_DELAY, CAMODO_INVALID_GRACE, HandleLogResult, INPUT_INVALID_LIMIT,
  INPUT_INVALID_RECOVERY, LocationEstimator, MAX_SENSOR_TIME_DIFF,
  calculate_invalid_input_decay, update_observation_invalid)

FREQ = 104.0          # accelerometer
LIMIT = 10            # round(INPUT_INVALID_LIMIT * FREQ / 20)
THRESHOLD = LIMIT - 0.5
DECAY = dict.fromkeys(("accelerometer",), 0.99995068)
GRACE = dict.fromkeys(("accelerometer",), max(1, round(0.5 * FREQ)))
LIMITS = dict.fromkeys(("accelerometer",), LIMIT)


def drive(results):
  """Feed results through the counter; return (bucket, index it crossed threshold)."""
  bucket, run = defaultdict(float), defaultdict(int)
  latched = None
  for i, res in enumerate(results):
    update_observation_invalid(res, "accelerometer", bucket, run, DECAY, GRACE, LIMITS)
    if bucket["accelerometer"] >= THRESHOLD and latched is None:
      latched = i
  return bucket["accelerometer"], latched


class TestSensorTimeWindow(OpenpilotTestCase):
  """The check itself is stateless and absolute: same clock, close in time."""

  def _est(self) -> LocationEstimator:
    return LocationEstimator.__new__(LocationEstimator)

  def test_a_frame_in_the_window_is_usable(self):
    assert self._est()._validate_sensor_time(10.002, 10.0)

  def test_a_late_frame_is_dropped(self):
    assert not self._est()._validate_sensor_time(10.0 + MAX_SENSOR_TIME_DIFF + 0.05, 10.0)

  def test_a_frame_ahead_of_the_log_time_is_dropped(self):
    assert not self._est()._validate_sensor_time(10.0 - MAX_SENSOR_TIME_DIFF - 0.05, 10.0)

  def test_an_empty_reading_is_dropped(self):
    assert not self._est()._validate_sensor_time(0.0, 10.0)


class TestInvalidCounter(OpenpilotTestCase):
  def test_isolated_late_frames_never_latch(self):
    for pct in (1, 3, 5):
      res = [HandleLogResult.SUCCESS] * 4000
      for i in range(0, 4000, max(1, 100 // pct)):
        res[i] = HandleLogResult.TIMING_INVALID
      bucket, latched = drive(res)
      self.assertIsNone(latched, f"{pct}% late frames latched (bucket={bucket})")

  def test_a_burst_shorter_than_the_grace_never_latches(self):
    res = [HandleLogResult.SUCCESS] * 100 + [HandleLogResult.TIMING_INVALID] * (int(0.5 * FREQ) - 1) + \
          [HandleLogResult.SUCCESS] * 100
    _, latched = drive(res)
    self.assertIsNone(latched)

  def test_a_sustained_timebase_fault_still_latches(self):
    res = [HandleLogResult.SUCCESS] * 500 + [HandleLogResult.TIMING_INVALID] * 2000
    _, latched = drive(res)
    self.assertIsNotNone(latched, "a broken timebase must still raise the alert")
    self.assertGreater(latched, 500, "must not latch before the fault starts")

  def test_a_wrong_sample_counts_at_once(self):
    res = [HandleLogResult.SUCCESS] * 20 + [HandleLogResult.INPUT_INVALID] * 20
    _, latched = drive(res)
    self.assertIsNotNone(latched, "a wrong sample is a fault, not a hiccup")

  def test_success_clears_the_consecutive_run(self):
    res = ([HandleLogResult.TIMING_INVALID] * (int(0.5 * FREQ) - 2) + [HandleLogResult.SUCCESS]) * 8
    _, latched = drive(res)
    self.assertIsNone(latched, "runs interrupted by a good frame must not accumulate")

  def test_the_counter_falls_once_good_frames_return(self):
    # the decay is multiplicative and upstream's: a fault that lasted long enough
    # to cross the limit leaves a high reading that comes down slowly. What must
    # hold is that it comes down at all while good frames flow.
    res = [HandleLogResult.TIMING_INVALID] * 400 + [HandleLogResult.SUCCESS] * 2000
    bucket, _ = drive(res)
    during_fault, _ = drive([HandleLogResult.TIMING_INVALID] * 400 + [HandleLogResult.SUCCESS] * 200)
    self.assertLess(bucket, during_fault, "the counter must fall once the fault clears")

  def test_the_counter_cannot_pile_up_past_the_limit(self):
    # 79 rejected gyro samples in one parking manoeuvre took the gyroscope budget
    # to 75 against a limit of 10; decaying that back under the threshold takes
    # ~395 s at 104 Hz, and the measured outage was 414 s. The budget is meant to
    # be a "10 s to recover" allowance, so it must not accumulate past the limit.
    res = [HandleLogResult.INPUT_INVALID] * 500
    bucket, _ = drive(res)
    self.assertLessEqual(bucket, LIMIT, f"budget piled up to {bucket}, above the limit {LIMIT}")


class TestGyroCamodoCrossCheck(OpenpilotTestCase):
  """The cross-check has no low-speed exemption, on purpose.

  Route 00000039 looked like it needed one: 79 correct gyro samples were
  rejected while creeping at 1.2-2.1 m/s with the wheel held at +-385 deg. But
  the camera was not saying "not turning" because the car was slow -- it was
  publishing a dead pose. Route 00000041 showed the same pose at 5-10 m/s for a
  whole drive, so no speed gate would have covered it, and a gate would only
  blind the check below 5 m/s. What actually protects parking is that a dead
  pose never becomes the reference (TestDeadCameraPose).
  """

  @staticmethod
  def _gyro(t: float, device_z: float):
    """A gyroscope event whose device-frame z-rate is `device_z` (meas[2] = -v[0])."""
    evt = log.Event.new_message()
    evt.init('gyroscope')
    evt.gyroscope.timestamp = int(t * 1e9)
    evt.gyroscope.source = 'lsm6ds3trc'
    evt.gyroscope.init('gyroUncalibrated')
    evt.gyroscope.gyroUncalibrated.v = [-device_z, 0.0, 0.0]
    return evt.gyroscope

  def _est(self):
    est = LocationEstimator(False, None)
    est.camodo_yawrate_distribution = np.array([0.0, 0.01])  # threshold = 0.30 rad/s
    return est

  def test_a_disagreeing_gyro_is_rejected_at_any_speed(self):
    for speed in (20.0, 5.0, 2.0, 0.0):
      est = self._est()
      est.car_speed = speed
      msg = self._gyro(10.0, 0.4)
      self.assertEqual(est.handle_log(10.0, 'gyroscope', msg), HandleLogResult.INPUT_INVALID,
                       'rejected at %.1f m/s: there is no speed exemption' % speed)

  def test_a_dead_pose_leaves_nothing_to_check_the_gyro_against(self):
    # the parking case: vision cannot see the turn, the reference stays "no
    # idea" (std 10 -> threshold 300 rad/s), so a correct gyro is never thrown
    # away for want of a camera that is blind
    est = LocationEstimator(False, None)
    evt = log.Event.new_message()
    evt.init('cameraOdometry')
    co = evt.cameraOdometry
    co.timestampEof = int((10.0 + CAM_ODO_POSE_DELAY) * 1e9)
    co.rot = [0.0, 0.0, 0.0002]
    co.rotStd = [0.001] * 3
    co.trans = [0.25, 0.0, 0.0]
    co.transStd = [0.02] * 3
    est.handle_log(10.0, 'cameraOdometry', co)
    self.assertEqual(float(est.camodo_yawrate_distribution[1]), 10.0,
                     'a dead pose must not narrow the cross-check')
    est.car_speed = 1.5
    self.assertEqual(est.handle_log(10.2, 'gyroscope', self._gyro(10.2, 0.3)),
                     HandleLogResult.SUCCESS)

  def test_a_broken_sample_is_still_rejected_while_parked(self):
    # a sample outside the rotation sanity bound is rejected at any speed
    est = self._est()
    est.car_speed = 0.0
    msg = self._gyro(10.0, 20.0)
    self.assertEqual(est.handle_log(10.0, 'gyroscope', msg), HandleLogResult.INPUT_INVALID)


class TestDeadCameraPose(OpenpilotTestCase):
  """A model that does not produce pose publishes zeros with a camera's
  confidence: route 00000041, 14740 chestnut frames at rotStd 0.0010 and
  |rot| 0.0002, against 0.0275 and 0.0246 on the small model's three. Fed to
  the filter, that bends GYRO_BIAS onto a car that never turns and makes the
  cross-check reject every real turn."""

  @staticmethod
  def _camodo(t, rot_z, std_z, trans_x=0.25):
    evt = log.Event.new_message()
    evt.init('cameraOdometry')
    co = evt.cameraOdometry
    co.timestampEof = int((t + CAM_ODO_POSE_DELAY) * 1e9)
    co.rot = [0.0, 0.0, rot_z]
    co.rotStd = [std_z] * 3
    co.trans = [trans_x, 0.0, 0.0]
    co.transStd = [0.02] * 3
    return co

  def test_a_zero_pose_with_a_tiny_std_is_not_fed_to_the_filter(self):
    est = LocationEstimator(False, None)
    before = est.camodo_yawrate_distribution.copy()
    res = est.handle_log(10.0, 'cameraOdometry', self._camodo(10.0, 0.0002, 0.001))
    self.assertEqual(res, HandleLogResult.SUCCESS)
    np.testing.assert_array_equal(est.camodo_yawrate_distribution, before,
                                  'a dead pose must not become the camera reference')
    self.assertEqual(float(est.camodo_yawrate_distribution[1]), 10.0,
                     'the reference stays "no idea", so the cross-check cannot reject the gyro')

  def test_a_real_pose_is_still_used(self):
    est = LocationEstimator(False, None)
    res = est.handle_log(10.0, 'cameraOdometry', self._camodo(10.0, 0.05, 0.027))
    self.assertEqual(res, HandleLogResult.SUCCESS)
    self.assertGreater(abs(float(est.camodo_yawrate_distribution[0])), 0.01,
                       'a real turn becomes the reference')

  def test_a_zero_pose_with_a_believable_std_is_kept(self):
    # parked, and the camera says so with a confidence a camera can have
    est = LocationEstimator(False, None)
    est.handle_log(10.0, 'cameraOdometry', self._camodo(10.0, 0.0, 0.03))
    self.assertLess(float(est.camodo_yawrate_distribution[1]), 1.0,
                    'a believable zero is a measurement, not a dead pose')


class TestCameraOdoGrace(OpenpilotTestCase):
  """A big/small model switch must not latch inputsOK.

  cameraOdometry's budget is round(INPUT_INVALID_LIMIT * 20/20) = 2 and its
  threshold is 1.5, so charging it once already crosses the threshold. Every
  model switch publishes exactly one cameraOdometry with valid=false: route
  0000003b had 16 modelV2.big flips and each was followed by one such frame, and
  every one of them held inputsOK down for the ~10 s the decay needs (7 events,
  98.3 s over threshold on that drive).
  """

  def test_two_charged_frames_latch_because_decay_is_slow(self):
    limit = round(INPUT_INVALID_LIMIT * (20.0 / 20.0))  # cameraOdometry runs at 20 Hz
    thr = limit - 0.5
    decay = calculate_invalid_input_decay(limit, INPUT_INVALID_RECOVERY, 20.0)
    self.assertEqual(limit, 2)
    self.assertLess(1, thr, "one charged frame alone is survivable")
    # but a second one a full second later is not: 20 good frames only take 2.0
    # down to ~1.94, so isolated bad frames one second apart still accumulate
    self.assertGreater(2 * decay ** 20, thr)

  def test_the_grace_outlasts_a_model_switch(self):
    # a switch costs one frame; the grace has to be longer than that
    self.assertGreaterEqual(CAMODO_INVALID_GRACE, 2,
                            "grace <= 1 means a model switch latches inputsOK again")

  def test_the_grace_is_far_shorter_than_a_real_outage(self):
    # 3 frames at 20 Hz is 150 ms; a genuinely dead camera pipeline lasts seconds
    self.assertLess(CAMODO_INVALID_GRACE / 20.0, 1.0)


if __name__ == "__main__":
  unittest.main()
