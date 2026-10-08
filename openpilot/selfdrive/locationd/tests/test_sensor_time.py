#!/usr/bin/env python3
"""The IMU timestamp check must be relative to each sensor's own recent skew, so a
wall-clock step (sensord "time jumped") does not reject the rest of the drive, while a
genuinely jittering sensor is still refused."""
from collections import defaultdict, deque
import unittest

import numpy as np

from openpilot.common.test import OpenpilotTestCase
from openpilot.selfdrive.locationd.locationd import LocationEstimator


class TestSensorTimeBaseline(OpenpilotTestCase):
  def _estimator(self) -> LocationEstimator:
    # Only the clock-skew state is needed; skip the Kalman/params construction.
    est = LocationEstimator.__new__(LocationEstimator)
    est._sensor_skew_history = defaultdict(lambda: deque(maxlen=25))
    est._sensor_skew_candidate = {}
    return est

  def test_steady_skew_is_accepted(self):
    est = self._estimator()
    for i in range(30):
      assert est._validate_sensor_time(i + 0.002, i, "accelerometer")

  def test_lone_spike_is_rejected_and_recovers(self):
    est = self._estimator()
    for i in range(10):
      est._validate_sensor_time(i + 0.002, i, "accelerometer")
    # one frame 200 ms off the sensor's own baseline
    assert not est._validate_sensor_time(10.0 + 0.202, 10.0, "accelerometer")
    for i in range(11, 25):
      assert est._validate_sensor_time(i + 0.002, i, "accelerometer")

  def test_clock_step_is_absorbed(self):
    est = self._estimator()
    for i in range(10):
      est._validate_sensor_time(i + 0.002, i, "gyroscope")
    # wall clock steps +1.5 s: every skew shifts by the same amount
    results = [est._validate_sensor_time(i + 1.5 + 0.002, i, "gyroscope") for i in range(10, 25)]
    assert sum(1 for ok in results if not ok) <= 2, "a clock step must cost at most the two transient frames"
    assert results[-1]

  def test_large_clock_step_is_absorbed(self):
    est = self._estimator()
    for i in range(10):
      est._validate_sensor_time(i + 0.002, i, "accelerometer")
    step = -71.0 * 24 * 3600  # the 71-day RTC/GNSS step seen in sensord logs
    results = [est._validate_sensor_time(i + step + 0.002, i, "accelerometer") for i in range(10, 25)]
    assert sum(1 for ok in results if not ok) <= 2
    assert results[-1]

  def test_random_jitter_is_still_rejected(self):
    est = self._estimator()
    for i in range(10):
      est._validate_sensor_time(i + 0.002, i, "accelerometer")
    rng = np.random.default_rng(0)
    rejected = 0
    for i in range(10, 40):
      if not est._validate_sensor_time(i + float(rng.uniform(-0.5, 0.5)), i, "accelerometer"):
        rejected += 1
    assert rejected >= 20, f"a jittering sensor must be refused, only {rejected}/30 rejected"


if __name__ == "__main__":
  unittest.main()
