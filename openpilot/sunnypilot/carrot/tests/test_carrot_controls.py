#!/usr/bin/env python3
from __future__ import annotations
"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
"""Unit tests for CarrotControls lat-suspend behavior."""

import sys
import types
import unittest
from unittest.mock import MagicMock

# Minimal mocks so the module imports without a compiled capnp runtime.
_common_pkg = types.ModuleType("openpilot.common")

# --- sys.modules stubs are import shims for hosts without a compiled capnp
# runtime. Two things matter for test isolation:
#   1. install them through _install_stub() so tearDownModule() can put the real
#      modules back into sys.modules;
#   2. keep the *package* stubs resolvable: give them the real package __path__,
#      otherwise "import openpilot.common.test" / "opendbc.car.car_helpers" fail
#      with "'x' is not a package" for every test module imported afterwards in
#      the same process (that was the collection error in the combined run).
_LEAKED_SYS_MODULES: dict[str, object] = {}


def _install_stub(name: str, module) -> None:
  # NOTE: these stubs deliberately have no __path__/__spec__. Giving them the real package
  # path makes deeper real imports (e.g. openpilot.common.hardware.base -> openpilot.cereal.log)
  # resolve while the stub is installed, which fails in a different way. Keep the fake a leaf
  # object and just guarantee it is removed again (see tearDownModule) so it cannot leak into
  # other test modules.
  _LEAKED_SYS_MODULES.setdefault(name, sys.modules.get(name))
  sys.modules[name] = module


def _drop_stubs() -> None:
  for _name, _original in _LEAKED_SYS_MODULES.items():
    if _original is None:
      sys.modules.pop(_name, None)
    else:
      sys.modules[_name] = _original
  _LEAKED_SYS_MODULES.clear()


def tearDownModule() -> None:
  _drop_stubs()


_common_pkg.realtime = types.ModuleType("openpilot.common.realtime")
_common_pkg.realtime.DT_CTRL = 0.01
_common_pkg.params = MagicMock()
_common_pkg.swaglog = MagicMock(cloudlog=MagicMock())
_install_stub("openpilot.common", _common_pkg)
_install_stub("openpilot.common.realtime", _common_pkg.realtime)
_install_stub("openpilot.common.params", _common_pkg.params)
_install_stub("openpilot.common.swaglog", _common_pkg.swaglog)

from openpilot.sunnypilot.carrot.carrot_controls import CarrotControls


class _FakeCS:
  def __init__(self, steering_pressed: bool = False, steering_angle_deg: float = 0.0):
    self.steeringPressed = steering_pressed
    self.steeringAngleDeg = steering_angle_deg


# The shims above only exist to let this module import the code under test. Drop them as soon
# as that import is done so they cannot leak into any other test module (a fake
# 'openpilot.common' module breaks 'import openpilot.common.test' elsewhere).
_drop_stubs()


class TestCarrotControlsLatSuspend(unittest.TestCase):
  def setUp(self):
    self.ctrl = CarrotControls(MagicMock())
    self.ctrl.params = MagicMock()
    self.ctrl.params.get = lambda key: 300  # LatSuspendAngleDeg = 300 degrees

  def test_no_suspend_when_steering_small(self):
    cs = _FakeCS(steering_pressed=True, steering_angle_deg=10.0)
    for _ in range(200):
      active = self.ctrl.lat_suspend_control(cs, True)
    self.assertTrue(active)
    self.assertFalse(self.ctrl.lat_suspend_active)

  def test_suspend_after_delay_at_large_angle(self):
    cs = _FakeCS(steering_pressed=True, steering_angle_deg=350.0)
    active = True
    for _ in range(99):
      active = self.ctrl.lat_suspend_control(cs, True)
    self.assertTrue(active)
    active = self.ctrl.lat_suspend_control(cs, True)
    self.assertFalse(active)
    self.assertTrue(self.ctrl.lat_suspend_active)

  def test_suspend_holds_and_resumes(self):
    # Enter suspend.
    cs = _FakeCS(steering_pressed=True, steering_angle_deg=350.0)
    for _ in range(110):
      self.ctrl.lat_suspend_control(cs, True)
    self.assertTrue(self.ctrl.lat_suspend_active)

    # Stay suspended while still steering hard.
    active = self.ctrl.lat_suspend_control(cs, True)
    self.assertFalse(active)

    # Release steering but stay at large angle -> still suspended (exit angle not met).
    cs = _FakeCS(steering_pressed=False, steering_angle_deg=350.0)
    for _ in range(60):
      active = self.ctrl.lat_suspend_control(cs, True)
    self.assertFalse(active)
    self.assertTrue(self.ctrl.lat_suspend_active)

    # Move to small angle and wait for hold time.
    cs = _FakeCS(steering_pressed=False, steering_angle_deg=10.0)
    for _ in range(60):
      active = self.ctrl.lat_suspend_control(cs, True)
    self.assertTrue(active)
    self.assertFalse(self.ctrl.lat_suspend_active)

  def test_timer_resets_when_condition_lost(self):
    cs = _FakeCS(steering_pressed=True, steering_angle_deg=350.0)
    for _ in range(50):
      self.ctrl.lat_suspend_control(cs, True)
    self.assertFalse(self.ctrl.lat_suspend_active)

    # Briefly lose the condition.
    cs = _FakeCS(steering_pressed=True, steering_angle_deg=10.0)
    self.ctrl.lat_suspend_control(cs, True)

    # Re-enter must wait full delay again.
    cs = _FakeCS(steering_pressed=True, steering_angle_deg=350.0)
    active = True
    for _ in range(99):
      active = self.ctrl.lat_suspend_control(cs, True)
    self.assertTrue(active)
    active = self.ctrl.lat_suspend_control(cs, True)
    self.assertFalse(active)


if __name__ == "__main__":
  unittest.main()
