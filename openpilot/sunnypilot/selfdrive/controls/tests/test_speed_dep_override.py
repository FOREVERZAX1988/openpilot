"""
Copyright (c) 2026-, Zeph Leggett.

This file is part of zoompilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.

The per-frame speed-dependent torque interpolation in LatControlTorqueExtZP: the
latAccelFactor and friction the controller reads, toggle-off behavior, manual override
priority, its tune scale and change detection. Tested on the override chain alone
(the TorqueParamsOverride half of LatControlTorqueExt); the torqued message handling, through a
real controller, is in test_speed_dep_ext_update.py.
"""
from types import SimpleNamespace

import numpy as np

from opendbc.car.mazda.values import MazdaFlags
from openpilot.common.test import OpenpilotTestCase, approx
from openpilot.sunnypilot.selfdrive.car.tests.fakes import FakeParams
from openpilot.sunnypilot.selfdrive.controls.lib import latcontrol_torque_ext_override as override_module
from openpilot.sunnypilot.selfdrive.controls.lib.latcontrol_torque_ext_override import LatControlTorqueExtOverride
from openpilot.sunnypilot.selfdrive.controls.lib.latcontrol_torque_ext_zp import LatControlTorqueExtZP
from openpilot.sunnypilot.selfdrive.locationd.tests.speed_dep_helpers import (
  SAMPLE_SPEED_BP, SAMPLE_LAT_ACCEL_FACTOR_BP, SAMPLE_FRICTION_BP, activate_speed_dep, make_cp, make_torque_params,
)


class TorqueParamsOverride(LatControlTorqueExtZP, LatControlTorqueExtOverride):
  """The torque-params half of LatControlTorqueExt: upstream's manual override under the fork's
  layer, without NNLC and jerk-aware, which these tests do not reach. The host only carries
  steer_max."""

  def __init__(self, CP):
    LatControlTorqueExtOverride.__init__(self, CP)
    LatControlTorqueExtZP.__init__(self, CP)
    self.lac_torque = SimpleNamespace(steer_max=1.0)


def make_override(monkeypatch):
  """Factory for a TorqueParamsOverride whose Params is a FakeParams; the fake is reachable
  afterwards as ovr.params."""
  def _make(enforce=False, manual_override=False, manual_lat_accel_factor='200', manual_friction='15', CP=None):
    fake = FakeParams(EnforceTorqueControl=enforce, TorqueParamsOverrideEnabled=manual_override,
                      TorqueParamsOverrideLatAccelFactor=manual_lat_accel_factor, TorqueParamsOverrideFriction=manual_friction)
    monkeypatch.setattr(override_module, "Params", lambda: fake)
    return TorqueParamsOverride(CP or make_cp())
  return _make


class TestInterpolatedBySpeed(OpenpilotTestCase):
  """latAccelFactor and friction come from the tables at the previous frame's speed, clamped to
  the end bins, before torque_from_lateral_accel and get_friction read them."""

  def test_both_params_follow_the_tables(self, make_override):
    for v_ego in [0.0, 6.5, 10.0, 21.0, 35.0, 37.5, 100.0]:
      with self.subTest(v_ego=v_ego):
        ovr = make_override()
        activate_speed_dep(ovr)
        tp = make_torque_params(latAccelFactor=999.0, friction=999.0)  # sentinels
        ovr._last_vego = v_ego
        ovr.update_override_torque_params(tp)
        assert tp.latAccelFactor == approx(np.interp(v_ego, SAMPLE_SPEED_BP, SAMPLE_LAT_ACCEL_FACTOR_BP), abs=1e-4)
        assert tp.friction == approx(np.interp(v_ego, SAMPLE_SPEED_BP, SAMPLE_FRICTION_BP), abs=1e-4)


class TestInactivePassesThrough(OpenpilotTestCase):
  """Inactive (never activated, or deactivated when torqued sent empty bins) or active with
  no tables, the controller keeps the global values it was handed."""

  def test_globals_pass_through(self, make_override):
    for state in ["fresh", "deactivated", "no_tables"]:
      with self.subTest(state=state):
        ovr = make_override()
        if state != "fresh":
          activate_speed_dep(ovr)
        if state == "deactivated":
          ovr._speed_dep_active = False
        elif state == "no_tables":
          ovr._speed_dep_speed_bp = []
        # Float32-exact literals so the pass-through check can stay an exact equality
        laf, fric = float(np.float32(2.35)), float(np.float32(0.12))
        tp = make_torque_params(latAccelFactor=laf, friction=fric)
        ovr._last_vego = 15.0
        ovr.update_override_torque_params(tp)
        assert tp.latAccelFactor == laf
        assert tp.friction == fric


class TestManualOverridePriority(OpenpilotTestCase):
  """Manual override must take priority over speed-dep."""

  def test_manual_overwrites_speed_dep(self, make_override):
    ovr = make_override(enforce=True, manual_override=True, manual_lat_accel_factor='350', manual_friction='25')
    activate_speed_dep(ovr)
    ovr._last_vego = 15.0

    tp = make_torque_params()
    # frame = -1, after +1 -> frame=0, 0 % 300 == 0 -> manual fires
    ovr.update_override_torque_params(tp)

    assert tp.latAccelFactor == approx(350.0, abs=0.1), "Manual latAccelFactor should overwrite speed-dep"
    assert tp.friction == approx(25.0, abs=0.1), "Manual friction should overwrite speed-dep"

  def test_manual_wins_every_frame(self, make_override):
    """The manual override must own the params on EVERY frame, not just the 3 s poll frame:
    the per-frame speed-dep interpolation used to out-write it 299/300 frames."""
    ovr = make_override(enforce=True, manual_override=True, manual_lat_accel_factor='350', manual_friction='25')
    activate_speed_dep(ovr)
    ovr._last_vego = 15.0

    tp = make_torque_params()
    for frame in range(10):
      ovr.update_override_torque_params(tp)
      assert tp.latAccelFactor == approx(350.0), f"speed-dep out-wrote manual on frame {frame}"
      assert tp.friction == approx(25.0), f"speed-dep out-wrote manual friction on frame {frame}"

  def test_manual_toggle_off_mid_drive_returns_to_speed_dep(self, make_override):
    """Flipping the override off mid-drive hands the params back to speed-dep at the next 3 s poll."""
    ovr = make_override(enforce=True, manual_override=True, manual_lat_accel_factor='350', manual_friction='25')
    activate_speed_dep(ovr)
    ovr._last_vego = 15.0

    tp = make_torque_params()
    ovr.update_override_torque_params(tp)
    assert tp.latAccelFactor == approx(350.0)

    ovr.params.put_bool("TorqueParamsOverrideEnabled", False)
    for _ in range(301):  # crosses the next poll frame
      ovr.update_override_torque_params(tp)

    expected_factor = float(np.interp(15.0, SAMPLE_SPEED_BP, SAMPLE_LAT_ACCEL_FACTOR_BP))
    assert tp.latAccelFactor == approx(expected_factor, abs=1e-4)

  def test_speed_dep_used_when_manual_off(self, make_override):
    ovr = make_override(enforce=True, manual_override=False)
    activate_speed_dep(ovr)
    ovr._last_vego = 15.0

    tp = make_torque_params()
    ovr.update_override_torque_params(tp)

    expected_factor = float(np.interp(15.0, SAMPLE_SPEED_BP, SAMPLE_LAT_ACCEL_FACTOR_BP))
    assert tp.latAccelFactor == approx(expected_factor, abs=1e-4), "Without manual override, speed-dep should be used"


class TestManualOverrideTuneScale(OpenpilotTestCase):
  """Typed on upstream's scale like params.toml; the Mazda EPS envelope's STEER_MAX is 1.5x it."""

  def test_typed_values_put_stock_counts_on_the_wire(self, make_override):
    CP = make_cp('MAZDA_CX5_2022', brand='mazda')
    CP.flags = int(MazdaFlags.GEN1 | MazdaFlags.STEER_TO_ZERO_EPS)
    ovr = make_override(enforce=True, manual_override=True, manual_lat_accel_factor='1.2', manual_friction='0.15', CP=CP)
    tp = make_torque_params()
    ovr.update_override_torque_params(tp)
    # counts per m/s^2 and friction counts of an 800-count build running the typed values
    assert 1200 / tp.latAccelFactor == approx(800 / 1.2, rel=1e-6)
    assert tp.friction * 1200 == approx(0.15 * 800, rel=1e-6)


class TestChangeDetection(OpenpilotTestCase):
  """update_override_torque_params should only return changed=True when values differ."""

  def test_no_change_returns_false(self, make_override):
    ovr = make_override()
    activate_speed_dep(ovr)
    ovr._last_vego = 15.0

    tp = make_torque_params()
    ovr.update_override_torque_params(tp)
    changed = ovr.update_override_torque_params(tp)  # same speed: no change
    assert not changed, "Should return False when values haven't changed"

  def test_speed_change_returns_true(self, make_override):
    ovr = make_override()
    activate_speed_dep(ovr)

    tp = make_torque_params()
    ovr._last_vego = 6.5
    ovr.update_override_torque_params(tp)

    ovr._last_vego = 37.5  # big speed change -> values change
    changed = ovr.update_override_torque_params(tp)
    assert changed, "Should return True when values changed"

  def test_float32_builder_does_not_report_change_every_frame(self, make_override):
    """The real torque_params is a capnp Float32 builder that hands back the rounded value,
    so the comparison must be made in float32 or every frame re-runs update_limits."""
    ovr = make_override()
    activate_speed_dep(ovr)
    ovr._last_vego = 13.7  # between bins: the interp is not float32-exact
    tp = make_torque_params()
    assert ovr.update_override_torque_params(tp)
    assert not ovr.update_override_torque_params(tp)
    assert tp.latAccelFactor == approx(float(np.interp(13.7, SAMPLE_SPEED_BP, SAMPLE_LAT_ACCEL_FACTOR_BP)), rel=1e-6)
    ovr._last_vego = 13.8
    assert ovr.update_override_torque_params(tp)
