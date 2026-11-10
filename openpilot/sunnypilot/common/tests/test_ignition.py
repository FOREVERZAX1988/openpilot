"""
Copyright (c) 2026-, Zeph Leggett.

This file is part of zoompilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
from types import SimpleNamespace
import unittest

from openpilot.cereal import log
from openpilot.sunnypilot.common import ignition
from openpilot.sunnypilot.common.ignition import get_ignition_state, IGNITION_CAN_DROP_HOLD_S

PandaType = log.PandaState.PandaType


def ps(can=False, line=False, panda_type=PandaType.tres):
  return SimpleNamespace(pandaType=panda_type, ignitionCan=can, ignitionLine=line)


class TestIgnition(unittest.TestCase):

  def setUp(self):
    # _fresh_state fixture
    ignition._ignition_can_last_seen = None
    self.addCleanup(setattr, ignition, "_ignition_can_last_seen", None)

  def test_can_on(self):
    self.assertTrue(get_ignition_state([ps(can=True)], now=0.0))
    self.assertTrue(get_ignition_state([ps(can=True, line=True)], now=1.0))

  def test_can_drop_with_line_high_holds_then_releases(self):
    self.assertTrue(get_ignition_state([ps(can=True, line=True)], now=10.0))
    for dt in (0.0, 1.0, IGNITION_CAN_DROP_HOLD_S - 0.1):
      self.assertTrue(get_ignition_state([ps(can=False, line=True)], now=10.0 + dt))
    self.assertFalse(get_ignition_state([ps(can=False, line=True)], now=10.0 + IGNITION_CAN_DROP_HOLD_S))
    # Mazda: line stays high ~30 s after key-off, it must not bring ignition back
    self.assertFalse(get_ignition_state([ps(can=False, line=True)], now=35.0))

  def test_can_drop_with_line_low_is_off_immediately(self):
    self.assertTrue(get_ignition_state([ps(can=True, line=True)], now=10.0))
    self.assertFalse(get_ignition_state([ps(can=False, line=False)], now=10.0))

  def test_line_only_car_follows_the_line(self):
    self.assertTrue(get_ignition_state([ps(line=True)], now=0.0))
    self.assertTrue(get_ignition_state([ps(line=True)], now=100.0))
    self.assertFalse(get_ignition_state([ps(line=False)], now=101.0))
    self.assertTrue(get_ignition_state([ps(line=True)], now=102.0))

  def test_no_valid_panda_is_off_and_resets(self):
    self.assertTrue(get_ignition_state([ps(can=True, line=True)], now=0.0))
    self.assertFalse(get_ignition_state([ps(can=True, line=True, panda_type=PandaType.unknown)], now=0.5))
    self.assertFalse(get_ignition_state([], now=0.6))
    self.assertIsNone(ignition._ignition_can_last_seen)
    # back to line-only semantics until CAN is seen again
    self.assertTrue(get_ignition_state([ps(line=True)], now=1.0))

  def test_can_recovery_inside_hold_window_restarts_it(self):
    self.assertTrue(get_ignition_state([ps(can=True, line=True)], now=0.0))
    self.assertTrue(get_ignition_state([ps(can=False, line=True)], now=3.0))
    self.assertTrue(get_ignition_state([ps(can=True, line=True)], now=4.0))
    # a new drop measures from the recovery, not the first drop
    self.assertTrue(get_ignition_state([ps(can=False, line=True)], now=4.0 + IGNITION_CAN_DROP_HOLD_S - 0.1))
    self.assertFalse(get_ignition_state([ps(can=False, line=True)], now=4.0 + IGNITION_CAN_DROP_HOLD_S))

  def test_any_panda_counts(self):
    states = [ps(can=False, line=False), ps(can=True, line=False)]
    self.assertTrue(get_ignition_state(states, now=0.0))
    states = [ps(can=False, line=True), ps(can=False, line=False)]
    self.assertTrue(get_ignition_state(states, now=2.0))
    self.assertFalse(get_ignition_state(states, now=2.0 + IGNITION_CAN_DROP_HOLD_S))

  def test_default_clock(self):
    # the callers pass nothing; the monotonic default must work
    self.assertTrue(get_ignition_state([ps(can=True)]))
    self.assertTrue(get_ignition_state([ps(line=True)]))


if __name__ == "__main__":
  unittest.main()
