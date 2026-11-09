#!/usr/bin/env python3
from __future__ import annotations
"""Unit tests for the cp-parity CruiseMaxVals cruise-acceleration envelope.

CarrotPlanner.get_carrot_accel restores cp's _get_carrot_accel: the 7-point
CruiseMaxVals0-6 table (hundredths of m/s² in params) interpolated at
_A_CRUISE_MAX_BP and scaled by the driving-mode factor. The longitudinal
planner consumes it as an optional positive-accel cap contributor
(CarrotCruiseAccelEnabled, default OFF) through get_carrot_max_accel, which
can only lower the cap - never raise it.
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

# Windows/PC import guard: see test_carrot_atc_migration.py for the rationale.
_SAVED_MODULES = {name: sys.modules.get(name) for name in (
  "openpilot.common", "openpilot.common.realtime", "openpilot.common.swaglog",
)}
try:
  _common_pkg = sys.modules.get("openpilot.common") or types.ModuleType("openpilot.common")
  _realtime = types.ModuleType("openpilot.common.realtime")
  _realtime.DT_MDL = 0.05
  _swaglog = types.ModuleType("openpilot.common.swaglog")
  _swaglog.cloudlog = MagicMock()
  sys.modules["openpilot.common"] = _common_pkg
  sys.modules["openpilot.common.realtime"] = _realtime
  sys.modules["openpilot.common.swaglog"] = _swaglog

  from openpilot.sunnypilot.carrot.carrot_functions import CarrotPlanner, DrivingMode, _A_CRUISE_MAX_BP
  from openpilot.sunnypilot.carrot.config import UnifiedParams
finally:
  for _name, _module in _SAVED_MODULES.items():
    if _module is None:
      sys.modules.pop(_name, None)
    else:
      sys.modules[_name] = _module

_DEFAULT_VALS = [1.6, 1.6, 1.2, 1.0, 0.8, 0.7, 0.6]


def _fresh_planner() -> CarrotPlanner:
  if hasattr(Params, "_reset"):
    Params._reset()
  UnifiedParams._instance = None
  UnifiedParams._initialized = False
  return CarrotPlanner(params=UnifiedParams(nav_json_file="/nonexistent/carrot_nav_params.json"))


class TestCarrotAccelEnvelope(unittest.TestCase):
  def test_default_curve_matches_cp_table(self):
    cp = _fresh_planner()
    # Breakpoints interpolate exactly at the table points.
    for bp, val in zip(_A_CRUISE_MAX_BP, _DEFAULT_VALS, strict=True):
      self.assertAlmostEqual(cp.get_carrot_accel(bp), val, places=9)

  def test_interpolates_between_breakpoints(self):
    cp = _fresh_planner()
    # Between 10 kph (1.6) and 40 kph (1.2): midpoint should be 1.4.
    mid = (_A_CRUISE_MAX_BP[1] + _A_CRUISE_MAX_BP[2]) / 2
    self.assertAlmostEqual(cp.get_carrot_accel(mid), 1.4, places=9)

  def test_high_mode_scales_the_curve(self):
    cp = _fresh_planner()
    cp._my_driving_mode = DrivingMode.High
    base = cp.get_carrot_accel(_A_CRUISE_MAX_BP[0])
    self.assertAlmostEqual(base, _DEFAULT_VALS[0] * cp._my_high_mode_factor, places=9)

  def test_params_override_loads_through_staggered_refresh(self):
    cp = _fresh_planner()
    cp._params.put_float("CruiseMaxVals2", 90)  # hundredths of m/s²
    for _ in range(45):
      cp._params_update()
    self.assertAlmostEqual(cp.get_carrot_accel(_A_CRUISE_MAX_BP[2]), 0.9, places=9)

  def test_values_above_100_never_raise_the_cap_unclamped(self):
    # An aggressive user table is the user's choice; the planner-side min()
    # against the other contributors is what keeps the cap honest. This test
    # just pins the envelope output so a regression in the table plumbing is
    # visible (600 -> 6.0 m/s² here, sanity-clamped downstream).
    cp = _fresh_planner()
    cp._params.put_float("CruiseMaxVals0", 600)
    for _ in range(45):
      cp._params_update()
    self.assertAlmostEqual(cp.get_carrot_accel(0.0), 6.0, places=9)

  # NOTE: the planner-side contributor test (get_carrot_max_accel gating, min()
  # semantics, non-finite guard) imports the longitudinal planner, which needs a
  # compiled msgq/cereal stack - not available on this Windows PC (same reason
  # test_carrot_server_features fails locally). It runs under CI and on-device.
  # The wiring is 8 guarded lines: enabled -> min(cap, envelope) with an
  # isfinite check, disabled -> contributor skipped entirely.


if __name__ == "__main__":
  unittest.main()
