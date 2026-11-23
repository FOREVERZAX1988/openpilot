"""
Copyright (c) 2026-, sunnypilot and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.

Tests for the conditional experimental mode: trigger conditions, hysteresis, the manual
override muzzle and the standstill freeze. All condition inputs come through fake carState /
sm doubles; the params are dict-backed so writes are inspectable.
"""
import os
import sys
import types

# the repo checkout keeps opendbc in opendbc_repo (mirroring launch_env.sh); a bare
# pytest run from the repo root does not have it on sys.path, a device/uv env does.
# Must run before the CEM import below, whose chain resolves opendbc.car.
# tests/ → selfdrived → selfdrive → sunnypilot → openpilot → repo root
_repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
  os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))))
_opendbc_repo = os.path.join(_repo, "opendbc_repo")
if os.path.isdir(_opendbc_repo) and _opendbc_repo not in sys.path:
  sys.path.append(_opendbc_repo)

try:
  import fcntl  # noqa: F401
except ImportError:
  sys.modules.setdefault('fcntl', types.ModuleType('fcntl'))

# common.params loads libparams_c.so via ctypes at import time; no Windows build exists.
# The CEM only needs the Params *class symbol* for typing/defaults - tests inject FakeCEParams.
# Run single-file (pytest --noconftest): stubbing here would leak into a shared session.
try:
  from openpilot.common.params import Params  # noqa: F401
except (OSError, FileNotFoundError):
  _params_mod = types.ModuleType('openpilot.common.params')

  class _ParamsStub:
    def __init__(self, *args, **kwargs):
      raise RuntimeError("real Params is unavailable on PC; inject a fake in tests")

  _params_mod.Params = _ParamsStub
  sys.modules['openpilot.common.params'] = _params_mod

from opendbc.car import structs
from openpilot.sunnypilot.selfdrive.car.tests.fakes import FakeParams
from openpilot.sunnypilot.selfdrive.selfdrived.conditional_experimental_mode import (
  CE_CCM_LAUNCH,
  CE_CCM_SPEED,
  CE_CCM_VETO,
  CE_CURVES,
  CE_LEAD,
  CE_MANUAL,
  CE_OFF,
  CE_SIGNAL,
  CE_STOP,
  MANUAL_HOLD_SECONDS,
  ConditionalExperimentalMode,
)
import unittest

DT_CTRL = 0.01


class FakeCEParams(FakeParams):
  """FakeParams plus the int put CEM uses for CEStatus, and the registered defaults
  that real Params.get(key, return_default=True) would return."""

  DEFAULTS = {"CECurves": True, "CECurvesLead": True, "CELead": True, "CESignalSpeed": 0.0,
              "CEStopLights": True, "CESignalLaneWidth": 0.0, "CEChillLaunch": False}

  def get(self, key, **kwargs):
    if key not in self.values and kwargs.get("return_default"):
      return self.DEFAULTS.get(key)
    return self.values.get(key)

  def put_int(self, key, value, **kwargs):
    self.values[key] = value


class FakeClock:
  def __init__(self):
    self.t = 0.0

  def __call__(self):
    return self.t


def car_state(v_ego=25.0, standstill=False, left_blinker=False, right_blinker=False):
  CS = car_state_msg()
  CS.vEgo = v_ego
  CS.standstill = standstill
  CS.leftBlinker = left_blinker
  CS.rightBlinker = right_blinker
  return CS


def car_state_msg():
  return structs.CarState.new_message()


def sm(desired_curvature=0.0, lead_status=False, lead_d_rel=100.0, lead_v_lead=30.0):
  class _Lead:
    pass

  lead = _Lead()
  lead.status = lead_status
  lead.dRel = lead_d_rel
  lead.vLead = lead_v_lead

  class _Radar:
    leadOne = lead

  class _Controls:
    desiredCurvature = desired_curvature

  class _SM:
    def __init__(self):
      self._data = {"controlsState": _Controls(), "radarState": _Radar()}

    def __getitem__(self, key):
      return self._data[key]

  return _SM()


def make_cem(**params):
  clock = FakeClock()
  params_obj = FakeCEParams(**{"ConditionalExperimental": True, **params})
  CP = structs.CarParams.new_message()
  CP.openpilotLongitudinalControl = True
  cem = ConditionalExperimentalMode(CP, params_obj, now_fn=clock)
  return cem, clock, params_obj


def frames(cem, n, CS, sm_obj):
  out = None
  for _ in range(n):
    out = cem.update(CS, sm_obj)
  return out




















# ---- Conditional Chill Mode (StarPilot CCM port) ------------------------------

CCM_SPEED_MPS = 45 * 0.44704


def make_ccm(**params):
  clock = FakeClock()
  params_obj = FakeCEParams(**{"ConditionalExperimental": False, "ConditionalChill": True, **params})
  CP = structs.CarParams.new_message()
  CP.openpilotLongitudinalControl = True
  cem = ConditionalExperimentalMode(CP, params_obj, now_fn=clock)
  return cem, clock, params_obj


def run_ccm_frames(cem, clock, n, CS, sm_obj, dt=0.01):
  out = None
  for _ in range(n):
    clock.t += dt
    out = cem.update(CS, sm_obj)
  return out


class TestConditionalExperimentalMode(unittest.TestCase):
  def test_curve_trigger_engages_experimental_mode(self):
    cem, _, params = make_cem()
    # 0.004 rad at 30 m/s is 3.6 m/s^2 lateral acceleration - demanding.
    sm_obj = sm(desired_curvature=0.004)
    CS = car_state(v_ego=30.0)
    # filter (tau 0.8 s) needs ~0.55 s to cross 0.5 from a sustained bool; run 2 s to be safe
    mode = frames(cem, 200, CS, sm_obj)
    assert mode is True
    assert params.values["ExperimentalMode"] is True
    assert params.values["CEStatus"] == CE_CURVES

  def test_curve_clears_after_hysteresis(self):
    cem, clock, params = make_cem()
    sm_curve = sm(desired_curvature=0.004)
    CS = car_state(v_ego=30.0)
    frames(cem, 200, CS, sm_curve)
    assert params.values["ExperimentalMode"] is True

    # conditions vanish: the filter (tau 0.8 s) must decay below the threshold first, then
    # the 0.5 s guard + 0.25 s buffer keep the mode before it drops
    sm_open = sm(desired_curvature=0.0)
    frames(cem, 20, CS, sm_open)  # 0.2 s: filter still hot, guard active
    assert params.values["ExperimentalMode"] is True
    clock.t += 1.5
    frames(cem, 100, CS, sm_open)  # 1 s: filter decays through the threshold
    clock.t += 1.5
    frames(cem, 20, CS, sm_open)
    assert params.values["ExperimentalMode"] is False
    assert params.values["CEStatus"] == CE_OFF

  def test_slow_lead_triggers_and_needs_closing_speed(self):
    cem, clock, params = make_cem()
    # 25 m/s ego, lead at 30 m ahead doing 21 m/s: closing 4 m/s, in range
    sm_obj = sm(lead_status=True, lead_d_rel=30.0, lead_v_lead=21.0)
    CS = car_state(v_ego=25.0)
    mode = frames(cem, 200, CS, sm_obj)
    assert mode is True
    assert params.values["CEStatus"] == CE_LEAD

    # lead speeds back up: filter decays and the mode drops once the hysteresis expires
    sm_fast_lead = sm(lead_status=True, lead_d_rel=60.0, lead_v_lead=25.0)
    clock.t = 10.0
    frames(cem, 30, CS, sm_fast_lead)  # filter decays but stays above the threshold: guard refreshes
    frames(cem, 30, CS, sm_fast_lead)  # filter now clearly below the threshold, buffer starts
    clock.t += 2.0  # let the guard hold and transition buffer expire
    mode = frames(cem, 5, CS, sm_fast_lead)
    assert mode is False

  def test_signal_trigger_disabled_by_default(self):
    cem, _, params = make_cem()
    CS = car_state(v_ego=8.0, left_blinker=True)
    mode = frames(cem, 30, CS, sm())
    assert mode is False
    assert params.values["CEStatus"] == CE_OFF

    cem_sig, _, _ = make_cem(CESignalSpeed=10.0)
    mode = frames(cem_sig, 30, CS, sm())
    assert mode is True
    assert cem_sig._last_ce_status_written == CE_SIGNAL

  def test_standstill_freezes_mode(self):
    cem, _, params = make_cem()
    sm_obj = sm(desired_curvature=0.004)
    CS = car_state(v_ego=30.0)
    frames(cem, 200, CS, sm_obj)
    assert params.values["ExperimentalMode"] is True

    # stop the car: no re-evaluation, mode stays pinned
    CS_stop = car_state(v_ego=0.0, standstill=True)
    frames(cem, 60, CS_stop, sm(desired_curvature=0.0))
    assert params.values["ExperimentalMode"] is True

  def test_manual_switch_adopts_and_muzzles(self):
    cem, clock, params = make_cem()
    # start with conditions ON so the CEM owns the param
    sm_obj = sm(desired_curvature=0.004)
    CS = car_state(v_ego=30.0)
    frames(cem, 200, CS, sm_obj)
    assert params.values["ExperimentalMode"] is True

    # driver turns it off behind the CEM's back
    params.values["ExperimentalMode"] = False
    clock.t += 0.1
    frames(cem, 5, CS, sm_obj)
    assert cem.manual_override_active
    assert params.values["ExperimentalMode"] is False
    assert cem._last_ce_status_written == CE_MANUAL

    # during the muzzle the demanding curve must NOT switch the mode back
    clock.t += MANUAL_HOLD_SECONDS / 2
    frames(cem, 20, CS, sm_obj)
    assert params.values["ExperimentalMode"] is False

    # after the muzzle expires conditions own the mode again
    clock.t += MANUAL_HOLD_SECONDS
    mode = frames(cem, 60, CS, sm_obj)
    assert mode is True

  def test_master_switch_off_is_inert(self):
    cem, _, params = make_cem(ConditionalExperimental=False)
    sm_obj = sm(desired_curvature=0.004)
    CS = car_state(v_ego=30.0)
    frames(cem, 200, CS, sm_obj)
    # no condition ever writes the param: the manual-only stock behaviour is untouched
    assert "ExperimentalMode" not in params.values or params.values["ExperimentalMode"] in (False, None)
    assert cem.experimental_mode is False

  def test_curve_trigger_respects_following_lead_gate(self):
    cem, _, _ = make_cem(CECurvesLead=False)
    sm_obj = sm(desired_curvature=0.004, lead_status=True)
    CS = car_state(v_ego=30.0)
    mode = frames(cem, 200, CS, sm_obj)
    assert mode is False

  def test_requires_longitudinal_control(self):
    params_obj = FakeCEParams(ConditionalExperimental=True)
    CP = structs.CarParams.new_message()
    CP.openpilotLongitudinalControl = False
    cem = ConditionalExperimentalMode(CP, params_obj)
    mode = frames(cem, 30, car_state(v_ego=30.0), sm(desired_curvature=0.004))
    assert mode is False

  def test_ccm_off_keeps_cem_semantics(self):
    cem, clock, _ = make_ccm(ConditionalChill=False, ConditionalExperimental=True)
    CS = car_state(v_ego=25.0)
    sm_obj = sm(desired_curvature=0.004)  # curve trigger
    mode = run_ccm_frames(cem, clock, 100, CS, sm_obj)
    assert mode is True  # CEM engages experimental on curves, not chill

  def test_ccm_speed_candidate_chills_after_confirmation(self):
    cem, clock, _ = make_ccm()
    CS = car_state(v_ego=CCM_SPEED_MPS + 2.0)
    CS.vCruise = CCM_SPEED_MPS + 4.0  # margin met, no lead (float32-safe)
    sm_obj = sm()
    # below the 0.35 s confirm window nothing chills yet
    mode = run_ccm_frames(cem, clock, 20, CS, sm_obj)  # 0.20 s
    assert mode is True
    mode = run_ccm_frames(cem, clock, 30, CS, sm_obj)  # past confirm
    assert mode is False  # chilled
    assert cem._ce_status == CE_CCM_SPEED

  def test_ccm_chill_needs_set_speed_margin(self):
    cem, clock, _ = make_ccm()
    CS = car_state(v_ego=CCM_SPEED_MPS + 2.0)
    CS.vCruise = CCM_SPEED_MPS + 2.0  # no margin
    mode = run_ccm_frames(cem, clock, 200, CS, sm())
    assert mode is True  # never chills at cruise speed

  def test_ccm_veto_forces_experimental(self):
    cem, clock, _ = make_ccm()
    CS = car_state(v_ego=CCM_SPEED_MPS + 2.0)
    CS.vCruise = CCM_SPEED_MPS + 8.0
    sm_obj = sm()
    run_ccm_frames(cem, clock, 100, CS, sm_obj)
    assert cem.ccm_chill is True
    # a curve appears: chill drops immediately, experimental back on
    sm_obj = sm(desired_curvature=0.006)  # >= 2.0 m/s^2 lateral at this speed
    # the curve veto reuses the CEM's 0.8 s filter, so it builds over ~0.5 s
    mode = run_ccm_frames(cem, clock, 100, CS, sm_obj)
    assert mode is True
    assert cem._ce_status == CE_CURVES

  def test_ccm_standstill_veto(self):
    cem, clock, _ = make_ccm()
    CS = car_state(v_ego=CCM_SPEED_MPS + 2.0, standstill=True)
    CS.vCruise = CCM_SPEED_MPS + 8.0
    mode = run_ccm_frames(cem, clock, 10, CS, sm())
    assert mode is True
    assert cem._ce_status == CE_CCM_VETO

  def test_ccm_blinker_veto_any_speed(self):
    cem, clock, _ = make_ccm()
    CS = car_state(v_ego=CCM_SPEED_MPS + 2.0, left_blinker=True)
    CS.vCruise = CCM_SPEED_MPS + 8.0
    mode = run_ccm_frames(cem, clock, 10, CS, sm())
    assert mode is True
    assert cem._ce_status == CE_SIGNAL

  def test_ccm_min_dwell_holds_chill_through_flickers(self):
    cem, clock, _ = make_ccm()
    CS = car_state(v_ego=CCM_SPEED_MPS + 2.0)
    CS.vCruise = CCM_SPEED_MPS + 8.0
    run_ccm_frames(cem, clock, 100, CS, sm())
    assert cem.ccm_chill is True
    # candidate lost: within the 1.2 s dwell the chill holds
    CS2 = car_state(v_ego=20.0)  # below the speed threshold, no lead
    CS2.vCruise = 30.0
    clock.t += 0.5
    mode = cem.update(CS2, sm())
    assert mode is False  # still chilled


# ---- stop-light / signal-lane / chill-scene triggers ---------------------------

import os

from types import SimpleNamespace

IDX_N = 33


def fake_line(y_val):
  return SimpleNamespace(x=[i * 6.0 for i in range(IDX_N)], y=[y_val] * IDX_N)


class _FakePosition:
  def __init__(self, horizon_m):
    self.x = [0.0] + [horizon_m] * (IDX_N - 1)  # non-decreasing; bend 0
    self.y = [0.0] * IDX_N


class _FakeModel:
  """modelV2 double; logMonoTime advances per read so the 4-frame lane cadence sees new frames."""

  def __init__(self, horizon_m, lane_ys, should_stop):
    self.position = _FakePosition(horizon_m)
    self.action = SimpleNamespace(shouldStop=should_stop)
    ys = lane_ys if lane_ys is not None else (3.5, 5.5, -5.5, -3.5)  # narrow (2 m) lanes by default
    self.laneLines = [fake_line(y) for y in ys]
    self.roadEdges = [fake_line(15.0), fake_line(-15.0)]  # beyond the outer lines on both sides
    self._stamp = 0

  @property
  def logMonoTime(self):
    self._stamp += 1
    return self._stamp


def trigger_sm(desired_curvature=0.0, lead_status=False, lead_d_rel=100.0, lead_v_lead=30.0,
               horizon_m=240.0, model_should_stop=False, plan_should_stop=False,
               plan_allow_throttle=True, lane_ys=None):
  """sm double extended with the modelV2 / longitudinalPlan / carControl the new
  triggers consume; base fields match the plain sm() factory."""
  sm_obj = sm(desired_curvature, lead_status, lead_d_rel, lead_v_lead)
  sm_obj._data["modelV2"] = _FakeModel(horizon_m, lane_ys, model_should_stop)
  sm_obj._data["longitudinalPlan"] = SimpleNamespace(shouldStop=plan_should_stop, allowThrottle=plan_allow_throttle)
  sm_obj._data["carControl"] = SimpleNamespace(enabled=True)
  return sm_obj


class TestConditionalTriggers(unittest.TestCase):
  def test_stop_trigger_acquires_and_holds(self):
    cem, clock, params = make_cem()
    CS = car_state(v_ego=25.0)
    # 30 m horizon at 25 m/s is far below the 9 s stop expectation: sustained
    # model_stopping with no blocking lead -> light_filter (tau 0.8 s) commits
    mode = run_ccm_frames(cem, clock, 150, CS, trigger_sm(horizon_m=30.0))
    assert mode is True
    assert cem._stop_detector.committed
    assert params.values["CEStatus"] == CE_STOP

  def test_stop_release_after_plan_go_and_horizon_recover(self):
    cem, clock, _ = make_cem()
    CS = car_state(v_ego=25.0)
    run_ccm_frames(cem, clock, 150, CS, trigger_sm(horizon_m=30.0))
    assert cem._stop_detector.committed
    # green: plan released, model plans past the 50 m + 4 m release band
    sm_go = trigger_sm(horizon_m=240.0)
    run_ccm_frames(cem, clock, 100, CS, sm_go)  # 1 s: > the 0.5 s clear dwell
    assert not cem._stop_detector.committed
    run_ccm_frames(cem, clock, 300, CS, sm_go)  # filters decay; guard, buffer and suppress expire
    assert cem.experimental_mode is False
    assert cem._last_ce_status_written == CE_OFF

  def test_plan_should_stop_vetoes_stop_release(self):
    cem, clock, _ = make_cem()
    CS = car_state(v_ego=25.0)
    run_ccm_frames(cem, clock, 150, CS, trigger_sm(horizon_m=30.0))
    assert cem._stop_detector.committed
    # horizon recovered but the plan still says stop: the commit must hold
    sm_go = trigger_sm(horizon_m=240.0, plan_should_stop=True)
    run_ccm_frames(cem, clock, 250, CS, sm_go)  # 2.5 s, far past the dwell
    assert cem._stop_detector.committed

  def test_stop_trigger_outranked_by_curve(self):
    cem, clock, _ = make_cem()
    CS = car_state(v_ego=30.0)
    sm_obj = trigger_sm(horizon_m=30.0, desired_curvature=0.004)  # 3.6 m/s^2 lateral
    mode = run_ccm_frames(cem, clock, 200, CS, sm_obj)
    assert mode is True
    assert cem._last_ce_status_written == CE_CURVES  # priority order unchanged

  def test_signal_lane_width_requires_narrow_lane(self):
    cem, clock, _ = make_cem(CESignalSpeed=12.0, CESignalLaneWidth=3.0)
    CS = car_state(v_ego=9.5, left_blinker=True)  # above LANE_CHANGE_SPEED_MIN so geometry is used
    # wide (5 m) adjacent lane: known-available, no trigger
    mode = run_ccm_frames(cem, clock, 60, CS, trigger_sm(lane_ys=(3.5, 8.5, -8.5, -3.5)))
    assert mode is False
    # narrow (2 m) adjacent lane: not available -> trigger
    mode = run_ccm_frames(cem, clock, 60, CS, trigger_sm())
    assert mode is True
    assert cem._last_ce_status_written == CE_SIGNAL

  def test_signal_trigger_unqualified_by_default(self):
    cem, clock, _ = make_cem(CESignalSpeed=12.0)  # CESignalLaneWidth unset (0.0)
    CS = car_state(v_ego=9.5, left_blinker=True)
    mode = run_ccm_frames(cem, clock, 60, CS, trigger_sm(lane_ys=(3.5, 8.5, -8.5, -3.5)))
    assert mode is True  # stock blinker+speed behaviour untouched

  def test_ccm_stop_light_veto(self):
    cem, clock, _ = make_ccm()
    CS = car_state(v_ego=CCM_SPEED_MPS + 2.0)
    CS.vCruise = CCM_SPEED_MPS + 8.0
    run_ccm_frames(cem, clock, 100, CS, trigger_sm(horizon_m=240.0))
    assert cem.ccm_chill is True
    # the model starts planning into a stop: the stop-light veto forces experimental
    sm_stop = trigger_sm(horizon_m=25.0)
    mode = run_ccm_frames(cem, clock, 100, CS, sm_stop)
    assert mode is True
    assert cem._ce_status == CE_STOP

  def test_ccm_low_speed_stop_scene_veto(self):
    cem, clock, _ = make_ccm()
    CS = car_state(v_ego=CCM_SPEED_MPS + 2.0)
    CS.vCruise = CCM_SPEED_MPS + 8.0
    run_ccm_frames(cem, clock, 100, CS, trigger_sm(horizon_m=240.0))
    assert cem.ccm_chill is True
    # decelerate below 18 mph with the model planning into a stop: low_speed_stop veto
    CS2 = car_state(v_ego=6.0)
    CS2.vCruise = 30.0
    clock.t += 0.5
    mode = run_ccm_frames(cem, clock, 30, CS2, trigger_sm(horizon_m=25.0))
    assert mode is True
    assert cem._ce_status == CE_CCM_VETO

  def test_ccm_launch_chill_waives_standstill_when_enabled(self):
    cem, clock, _ = make_ccm(CEChillLaunch=True)
    CS = car_state(v_ego=0.0, standstill=True)
    CS.vCruise = 30.0
    sm_obj = trigger_sm(horizon_m=240.0, plan_should_stop=False, plan_allow_throttle=True)
    mode = run_ccm_frames(cem, clock, 30, CS, sm_obj)
    assert mode is False  # chill held through the launch (policy.py:501-503)
    assert cem._ce_status == CE_CCM_LAUNCH

  def test_ccm_standstill_still_vetoes_launch_by_default(self):
    cem, clock, _ = make_ccm()  # CEChillLaunch off: starpilot ModeSettings default
    CS = car_state(v_ego=0.0, standstill=True)
    CS.vCruise = 30.0
    mode = run_ccm_frames(cem, clock, 30, CS, trigger_sm(horizon_m=240.0))
    assert mode is True
    assert cem._ce_status == CE_CCM_VETO
