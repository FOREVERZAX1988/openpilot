"""Source-timed Ioniq comfort hysteresis unit tests.

Verbatim port of StarPilot starpilot/longitudinal/tests/test_throttle_gate.py
ModelThrottleGateTests (the four gate-contract tests). The two NativePlanner
tests there depend on StarPilot's candidate()/messages() harness fixtures and
an optional clock_ns constructor; the planner wiring branch in our fork is a
verbatim mirror behind the ModelThrottleGateEnabled param and is verified on
device A/B instead.
"""

import unittest

from openpilot.sunnypilot.selfdrive.controls.lib.throttle_gate import ModelThrottleGate


BASE_NS = 10_000_000_000
FRAME_NS = 50_000_000


class ModelThrottleGateTests(unittest.TestCase):
  def setUp(self):
    self.gate = ModelThrottleGate()

  def step(self, index, probability, *, speed=20.0, now_ns=None, stamp_ns=None, valid=True):
    stamp = BASE_NS + index * FRAME_NS if stamp_ns is None else stamp_ns
    return self.gate.step(probability, speed, low_speed_mps=2.5, model_ns=stamp,
                          now_ns=stamp + 10_000_000 if now_ns is None else now_ns, model_valid=valid)

  def test_confirmed_thresholds_and_low_speed_bypass(self):
    for frame in range(5):
      self.assertTrue(self.step(frame, 0.34))
    self.assertFalse(self.step(5, 0.34))
    self.assertFalse(self.step(6, 0.44))
    for frame in range(7, 12):
      self.assertFalse(self.step(frame, 0.46))
    self.assertTrue(self.step(12, 0.46))
    self.assertTrue(self.step(13, 0.34, speed=2.5))
    self.assertFalse(self.step(14, 0.34, speed=2.5, valid=False))
    self.assertTrue(self.step(15, 0.34, speed=2.5))

  def test_repeated_stale_future_and_gap_cannot_accumulate_hold(self):
    self.assertTrue(self.step(0, 0.34))
    self.assertFalse(self.step(0, 0.34))
    for _ in range(10):
      self.assertFalse(self.step(0, 0.9))
    self.assertFalse(self.step(1, 0.9, now_ns=BASE_NS + FRAME_NS - 1))
    self.assertFalse(self.step(2, 0.9, now_ns=BASE_NS + FRAME_NS * 2 + 251_000_000))
    self.assertFalse(self.step(8, 0.9))
    for frame in range(9, 14):
      self.assertFalse(self.step(frame, 0.9))
    self.assertTrue(self.step(14, 0.9))

  def test_unknown_probability_never_grants_and_reset_clears_epoch(self):
    self.assertFalse(self.step(0, float('nan')))
    self.assertFalse(self.step(0, 1.0))
    self.gate.reset()
    self.assertTrue(self.step(0, 1.0))

  def test_future_outlier_does_not_poison_valid_stream(self):
    self.assertTrue(self.step(0, 0.34))
    self.assertFalse(self.step(100, 0.34, now_ns=BASE_NS + 20_000_000))
    for frame in range(1, 6):
      self.assertFalse(self.step(frame, 0.9))
    self.assertTrue(self.step(6, 0.9))


if __name__ == '__main__':
  unittest.main()
