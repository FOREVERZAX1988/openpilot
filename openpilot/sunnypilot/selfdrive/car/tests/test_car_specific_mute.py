#!/usr/bin/env python3
from __future__ import annotations
"""Unit tests for the MuteSeatbelt / MuteDoor consumers in CarSpecificEventsSP.

The params were registered in params_keys.h and seeded by config.py but never
consumed - the stock event engine (car_events.create) always emits doorOpen /
seatbeltNotLatched. The overlay now removes them when muted, on the same
remove-after-generate pattern the brand blocks use.
"""

import sys
import types
import unittest
from unittest.mock import MagicMock

try:
  from openpilot.common.params import Params
except (OSError, ModuleNotFoundError):
  from openpilot.common.tests import params_pc_stub
  params_pc_stub.register()
  Params = params_pc_stub.Params

# Windows/PC import guard: openpilot.common.realtime needs fcntl, and
# sunnypilot's events module imports cereal.messaging (msgq). Stub both for the
# import only, then restore - leftover stubs break later test modules in the
# same process (same pattern as test_carrot_atc_migration.py).
_SAVED_MODULES = {name: sys.modules.get(name) for name in (
  "openpilot.common.realtime", "openpilot.common.swaglog", "openpilot.common.hardware",
  "openpilot.cereal.messaging", "openpilot.selfdrive.locationd.calibrationd",
)}
try:
  _rt = types.ModuleType("openpilot.common.realtime")
  _rt.DT_MDL = 0.05
  _rt.DT_CTRL = 0.01
  _sw = types.ModuleType("openpilot.common.swaglog")
  _sw.cloudlog = MagicMock()
  # events.py imports MIN_SPEED_FILTER from calibrationd, whose own import chain
  # reaches common.hardware -> gpio -> fcntl (unavailable on Windows). The value
  # mirrors calibrationd.py: 15 mph in m/s.
  _cal = types.ModuleType("openpilot.selfdrive.locationd.calibrationd")
  _cal.MIN_SPEED_FILTER = 15 * 0.44704
  # events.py also imports HARDWARE directly; the package pulls gpio/fcntl on
  # Windows. Events only ever calls HARDWARE methods at runtime on-device.
  _hw = types.ModuleType("openpilot.common.hardware")
  _hw.HARDWARE = MagicMock(name="HARDWARE")
  sys.modules["openpilot.common.realtime"] = _rt
  sys.modules["openpilot.common.swaglog"] = _sw
  sys.modules["openpilot.selfdrive.locationd.calibrationd"] = _cal
  sys.modules["openpilot.common.hardware"] = _hw
  if "openpilot.cereal.messaging" not in sys.modules:
    try:
      import openpilot.cereal.messaging  # noqa: F401
    except (OSError, ModuleNotFoundError):
      sys.modules["openpilot.cereal.messaging"] = MagicMock(name="cereal.messaging")

  from openpilot.cereal import log
  from openpilot.selfdrive.selfdrived.events import Events
  from openpilot.sunnypilot.selfdrive.car.car_specific import CarSpecificEventsSP
finally:
  for _name, _module in _SAVED_MODULES.items():
    if _module is None:
      sys.modules.pop(_name, None)
    else:
      sys.modules[_name] = _module

EventName = log.OnroadEvent.EventName


def _make_events_sp(mute_seatbelt: bool = False, mute_door: bool = False) -> CarSpecificEventsSP:
  if hasattr(Params, "_reset"):
    Params._reset()
  params = Params()
  params.put_bool("MuteSeatbelt", mute_seatbelt)
  params.put_bool("MuteDoor", mute_door)
  cp = MagicMock()
  cp.brand = "mock"  # skips every brand-specific block
  cp_sp = MagicMock()
  return CarSpecificEventsSP(cp, cp_sp, params=params)


def _events_with(*names) -> Events:
  events = Events()
  for name in names:
    events.add(name)
  return events


def _run_update(sp: CarSpecificEventsSP, events: Events):
  cs = MagicMock()
  cs.buttonEvents = []  # update_stock_ecu iterates this
  cs.standstill = False
  return sp.update(cs, events, MagicMock())


class TestMuteAlerts(unittest.TestCase):
  def test_unmuted_events_pass_through(self):
    sp = _make_events_sp()
    events = _events_with(EventName.doorOpen, EventName.seatbeltNotLatched)
    _run_update(sp, events)
    self.assertTrue(events.has(EventName.doorOpen))
    self.assertTrue(events.has(EventName.seatbeltNotLatched))

  def test_mute_door_removes_door_event(self):
    sp = _make_events_sp(mute_door=True)
    events = _events_with(EventName.doorOpen, EventName.wrongGear)
    _run_update(sp, events)
    self.assertFalse(events.has(EventName.doorOpen))
    # unrelated events are untouched
    self.assertTrue(events.has(EventName.wrongGear))

  def test_mute_seatbelt_removes_seatbelt_event(self):
    sp = _make_events_sp(mute_seatbelt=True)
    events = _events_with(EventName.seatbeltNotLatched, EventName.reverseGear)
    _run_update(sp, events)
    self.assertFalse(events.has(EventName.seatbeltNotLatched))
    self.assertTrue(events.has(EventName.reverseGear))

  def test_slow_cadence_param_refresh(self):
    sp = _make_events_sp()
    events = _events_with(EventName.doorOpen)
    _run_update(sp, events)
    self.assertTrue(events.has(EventName.doorOpen))

    # Flip the param; the overlay refreshes every 100 frames.
    sp._params.put_bool("MuteDoor", True)
    sp._frame = 99  # next update hits the % 100 branch
    events = _events_with(EventName.doorOpen)
    _run_update(sp, events)
    self.assertFalse(events.has(EventName.doorOpen))


if __name__ == "__main__":
  unittest.main()
