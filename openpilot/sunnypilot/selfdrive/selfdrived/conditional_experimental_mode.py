"""
Copyright (c) 2026-, sunnypilot and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.

Conditional Experimental Mode, a sunnypilot-shaped port of StarPilot's conditional_experimental_mode.

The StarPilot original lives inside its planner skeleton and scores conditions off StarPilotPlanner
attributes (model_length, lane widths, stop-sign latches). This port keeps the parts that only need
data selfdrived already subscribes to - curvature, radarState lead, blinkers, plus modelV2 and
longitudinalPlan for the stop-light, signal-lane and chill-scene triggers - and drives the very
same ExperimentalMode param the manual switch uses, so planner/UI keep their single consumption path
(selfdriveStateSP.zoompilot.experimentalMode). No capnp change, no planner change.

Priority model: when the master switch is on, conditions own the mode; a manual switch (wheel long
press or onroad button) takes over for MANUAL_HOLD_SECONDS, after which conditions resume. At
standstill the current mode is frozen rather than re-evaluated.
"""
import math
import time

import numpy as np

from openpilot.common.filter_simple import FirstOrderFilter
from openpilot.common.params import Params
from openpilot.selfdrive.modeld.constants import ModelConstants
from opendbc.car import structs

# selfdrived runs at 100 Hz (Ratekeeper(100)); DT_CTRL inlined from common.realtime to keep
# this module importable on PC, where common.hardware (and its fcntl chain) is unavailable.
DT_CTRL = 0.01

# CEStatus values published on the memory params for UI/debugging: why EXP is on right now.
CE_OFF = 0
CE_CURVES = 1
CE_LEAD = 2
CE_SIGNAL = 3
CE_MANUAL = 4
CE_CCM_SPEED = 5   # CCM chill: open road at cruise speed, no lead
CE_CCM_LEAD = 6    # CCM chill: stable lead at highway speed
CE_CCM_VETO = 7    # CCM veto: complex scene, experimental forced on
CE_STOP = 8        # CEM/CCM stop-light trigger (starpilot policy.py:480 maps CEM_STOP to 8)
CE_CCM_LAUNCH = 9  # CCM launch candidate; starpilot reports it as the generic chill status 6

# --- curve trigger ------------------------------------------------------------
CURVE_LAT_ACC = 2.0            # m/s^2 of lateral acceleration that counts as "demanding"
CURVE_FILTER_TIME = 0.8        # s; lower = snappier, higher = smoother
CURVE_MIN_EGO = 13.4           # m/s (~30 mph); curves at parking speeds are not highway curves
CURVE_THRESHOLD = 0.5          # filtered score that trips the trigger (filter input is bool)

# --- slow lead trigger ---------------------------------------------------------
LEAD_MAX_EGO = 35.31           # m/s (~79 mph); above this, slow leads stop switching modes
LEAD_CONTINUITY_MAX_TIME = 4.0
LEAD_CONTINUITY_MIN_DISTANCE = 40.0
LEAD_MIN_CLOSING_SPEED = 0.75  # m/s; slower closing speeds are just traffic, not a trigger
LEAD_FILTER_TIME = 0.8

# --- hysteresis ----------------------------------------------------------------
TRANSITION_GUARD_TIME = 0.50   # a trigger holds the mode this long even if it clears
TRANSITION_BUFFER_TIME = 0.25  # after the hold, this grace keeps the mode through flickers

# --- manual interaction ---------------------------------------------------------
MANUAL_HOLD_SECONDS = 60.0     # a manual switch muzzles the conditions for this long
PARAMS_READ_PERIOD = 1.0       # s; matches SelfdrivedZP's PARAMS_READ_FRAMES cadence

# --- Conditional Chill Mode (StarPilot conditional_mode/policy.py _ccm port) -----
# CCM is the reverse conditional: chill on the fast/open road, experimental again
# the moment the scene turns complex (curves, blinkers, slow leads, standstill).
CCM_SPEED_MPS = 45 * 0.44704          # no-lead chill needs this ego speed (verbatim default)
CCM_SPEED_WITH_LEAD_MPS = 35 * 0.44704  # stable-lead chill threshold (verbatim default)
CCM_SET_SPEED_MARGIN_MPS = 3 * 0.44704  # cruise set speed must exceed ego by this (verbatim)
CCM_SPEED_CONFIRM_S = 0.35    # StarPilot CCM_SPEED_CONFIRM_S
CCM_LEAD_CONFIRM_S = 1.0      # StarPilot CCM_LEAD_CONFIRM_S
CCM_MIN_DWELL_S = 1.2         # StarPilot CCM_MIN_DWELL_S
CCM_EXIT_BUFFER_S = 0.35      # StarPilot CCM_EXIT_BUFFER_S

# --- stop-light trigger (StarPilot conditional_mode/stop.py) ----------------------
# StarPilot feeds its stop detector planner-owned inputs (model stop time,
# forcing-stop latches, sign recognition). This port keeps the model-length core
# with MODEL_STOP_TIME_S as the verbatim default preference and a corroborated
# release; the plan/model stop bit can veto a release but never acquires a
# light (stop.py:3-4).
STOP_FILTER_TIME_S = 0.8        # stop.py:101 FirstOrderFilter(0.0, 0.8, DT_MDL)
LEAD_CLEAR_FILTER_TIME_S = 0.6  # stop.py:102
STOP_THRESHOLD = 1.0 - 1.0 / math.e  # stop.py:22
STOP_THRESHOLD_SQUARED = STOP_THRESHOLD * STOP_THRESHOLD  # stop.py:359 filtered = x >= THRESHOLD**2
FROZEN_RAW_STOP_DISTANCE_M = 50.0  # stop.py:27 (CRUISING_SPEED * PLANNER_TIME = 5.0 * T_IDXS[-1])
STOP_MODEL_RELEASE_MARGIN_M = 4.0  # stop.py:28
STOP_CLEAR_DWELL_S = 0.5        # stop.py:170
STOP_RESET_MAX_MPH = 75.0       # stop.py:317 the detector resets above this speed
MODEL_STOP_TIME_S = 7.7         # preferences.py:42 model_stop_s default (verbatim)

# --- committed-turn veto for the stop detector (StarPilot turn_scene.py) ----------
TURN_MAX_SPEED_MPS = 15.0 * 0.44704       # turn_scene.py:12
TURN_MIN_STEERING_ANGLE_DEG = 45.0        # turn_scene.py:13
TURN_CURVE_LAT_ACC_MPS2 = 1.3             # projection.py:39 FROZEN_CURVE_ACCEL_MPS2 (driving_in_curve)

# --- signal-lane width qualifier (StarPilot conditional_mode/signal_lane.py) ------
SIGNAL_LANE_CADENCE_FRAMES = 4            # signal_lane.py:174 self._count % 4 == 0
LANE_CHANGE_SPEED_MIN_MPS = 20 * 0.44704  # sp desire_helper.py:16 LANE_CHANGE_SPEED_MIN (signal_lane.py:166 gate)

# --- chill-scene evidence (StarPilot conditional_mode/chill_scene.py) -------------
LOW_SPEED_STOP_MAX_MPS = 18.0 * 0.44704   # chill_scene.py:16 LOW_SPEED_STOP_MAX_MPS
LAUNCH_EXIT_MPS = 15.0 * 0.44704          # chill_scene.py:17 LAUNCH_EXIT_MPS
LAUNCH_ENTRY_MAX_MPS = 1.0                # chill_scene.py:18 LAUNCH_ENTRY_MAX_MPS

# --- stop-release quiet period (StarPilot conditional_mode/policy.py) -------------
CEM_STOP_RELEASE_SUPPRESS_S = 2.0         # policy.py:21 CEM_STOP_RELEASE_SUPPRESS_S


def _scale_threshold(v_ego: float) -> float:
  """Speed-scaled lead filter threshold, from StarPilot: harder to trip with speed."""
  bp = [0.0, 17.9, 26.8, 35.8, 44.7]
  fp = [0.58, 0.60, 0.62, 0.75, 0.90]
  return float(np.interp(v_ego, bp, fp))


def _lane_polyline(line) -> tuple[np.ndarray, np.ndarray] | None:
  """Validated model polyline: finite, in range, forward-monotonic (signal_lane.py:84-99)."""
  try:
    xs = tuple(float(v) for v in line.x)
    ys = tuple(float(v) for v in line.y)
  except (AttributeError, TypeError, ValueError, OverflowError):
    return None
  n = ModelConstants.IDX_N
  if len(xs) != n or len(ys) != n:
    return None
  if any(not math.isfinite(v) or not 0.0 <= v <= 500.0 for v in xs):
    return None
  if any(not math.isfinite(v) or not -30.0 <= v <= 30.0 for v in ys):
    return None
  if any(b <= a for a, b in zip(xs, xs[1:], strict=False)):  # signal_lane.py:97
    return None
  return np.asarray(xs, dtype=float), np.asarray(ys, dtype=float)


def _lane_width_between(outer, inner, edge) -> float | None:
  """Adjacent-lane width bounded by the road edge (signal_lane.py:102-111)."""
  outer_line, inner_line, edge_line = _lane_polyline(outer), _lane_polyline(inner), _lane_polyline(edge)
  if outer_line is None or inner_line is None or edge_line is None:
    return None
  ox, oy = outer_line
  ix, iy = inner_line
  ex, ey = edge_line
  lane_width = float(np.median(np.abs(iy - np.interp(ix, ox, oy))))  # signal_lane.py:109
  edge_width = float(np.median(np.abs(iy - np.interp(ix, ex, ey))))  # signal_lane.py:110
  return 0.0 if edge_width < lane_width else lane_width              # signal_lane.py:111


def _lane_model_widths(model) -> tuple[float, float] | None:
  """(left, right) adjacent-lane widths from model geometry (signal_lane.py:114-124)."""
  try:
    lines, edges = model.laneLines, model.roadEdges
    if len(lines) != 4 or len(edges) != 2:
      return None
    left = _lane_width_between(lines[0], lines[1], edges[0])
    right = _lane_width_between(lines[3], lines[2], edges[1])
  except (AttributeError, TypeError, ValueError, OverflowError):
    return None
  return (left, right) if left is not None and right is not None else None


class _StopLightDetector:
  """StarPilot StopLightDetector core (stop.py): a red light is acquired from a
  sustained model-length stop shorter than the speed-scaled expectation while the
  blocking lead is clear, and released only on corroborated clear evidence
  (horizon recovered, plan no longer stopping, 0.5 s dwell). The plan/model stop
  bit can veto a release but never acquires (stop.py:3-4). StarPilot's
  vision-handoff/approach-hold arms need radarTrackId/lead.tracked inputs that
  sp's radarState does not carry, so acquisition is filter-only here."""

  def __init__(self, dt: float):
    self.light_filter = FirstOrderFilter(0.0, STOP_FILTER_TIME_S, dt)          # stop.py:101
    self.lead_clear_filter = FirstOrderFilter(0.0, LEAD_CLEAR_FILTER_TIME_S, dt)  # stop.py:102
    self.model_detected = False
    self.committed = False
    self.commit_distance_m = 0.0
    self.clear_since: float | None = None

  def reset(self) -> None:
    self.light_filter.x = 0.0
    self.lead_clear_filter.x = 0.0
    self.model_detected = False
    self.committed = False
    self.commit_distance_m = 0.0
    self.clear_since = None

  def reset_filters(self) -> None:
    """_reset_light (stop.py:125-132): clears the filters but keeps the commit."""
    self.light_filter.x = 0.0
    self.lead_clear_filter.x = 0.0
    self.model_detected = False

  def _commit(self, horizon: float | None, model_stopping: bool, should_stop: bool | None,
              speed: float, now: float, dt: float, acquire: bool) -> bool:
    """stop.py:134-179 commit core. Returns True when the commit released."""
    if acquire and not self.committed and horizon is not None:  # stop.py:153-155
      self.committed = True
      self.commit_distance_m = horizon
    released = False
    if self.committed:
      self.commit_distance_m = max(0.0, self.commit_distance_m - speed * dt)  # stop.py:158
      clear = (horizon is not None and not model_stopping and should_stop is False and
               horizon >= max(FROZEN_RAW_STOP_DISTANCE_M, self.commit_distance_m) + STOP_MODEL_RELEASE_MARGIN_M)  # stop.py:161-164
      if clear:
        if self.clear_since is not None and now - self.clear_since >= STOP_CLEAR_DWELL_S:  # stop.py:169-170
          released = True
          self.reset()
        elif self.clear_since is None:
          self.clear_since = now
      else:
        self.clear_since = None
    return released

  def update(self, speed: float, horizon: float | None, lead_present: bool, lead_distance: float | None,
             should_stop: bool | None, turn_scene: bool, now: float, dt: float) -> tuple[bool, bool, bool]:
    """Returns (light_detected, model_stopping, released); light_detected == committed."""
    if turn_scene or speed / 0.44704 > STOP_RESET_MAX_MPH:  # stop.py:317-322
      self.reset_filters()
      model_stopping = horizon is not None and horizon < FROZEN_RAW_STOP_DISTANCE_M
      released = self._commit(horizon, model_stopping, should_stop, speed, now, dt, acquire=False)
      return self.committed, model_stopping, released

    # speed-scaled stop expectation (stop.py:324-339); MODEL_STOP_TIME_S stands in
    # for the planner-owned model stop time sp does not expose
    speed_mph = speed / 0.44704
    boost = float(np.interp(speed_mph, [0.0, 35.0, 45.0], [1.0, 1.0, 1.2]))       # stop.py:329
    cap_factor = float(np.interp(speed_mph, [0.0, 35.0, 45.0], [0.0, 0.0, 1.0]))  # stop.py:330
    adjusted_time = MODEL_STOP_TIME_S * boost
    if cap_factor > 0.0:  # stop.py:332-333
      adjusted_time = min(adjusted_time, 9.0 * cap_factor + MODEL_STOP_TIME_S * (1.0 - cap_factor))
    threshold_m = max(speed * adjusted_time, 0.0)
    if self.model_detected:
      model_stopping = horizon is not None and horizon < threshold_m + 4.0            # stop.py:336
    else:
      model_stopping = horizon is not None and horizon < max(threshold_m - 2.5, 0.0)  # stop.py:338
    self.model_detected = model_stopping

    relevant = bool(lead_present and lead_distance is not None and lead_distance < threshold_m + 15.0)  # stop.py:341
    self.lead_clear_filter.update(not relevant)
    lead_cleared = bool(self.lead_clear_filter.x >= STOP_THRESHOLD)                    # stop.py:356-357
    self.light_filter.update(model_stopping and lead_cleared)                          # stop.py:358
    filtered = bool(self.light_filter.x >= STOP_THRESHOLD_SQUARED and lead_cleared)    # stop.py:359

    released = self._commit(horizon, model_stopping, should_stop, speed, now, dt, acquire=filtered)
    return self.committed, model_stopping, released


class ConditionalExperimentalMode:
  def __init__(self, CP: structs.CarParams, params: Params | None = None, now_fn=time.monotonic):
    self.CP = CP
    self.params = params or Params()
    self._now = now_fn

    self.frame = 0
    self._params_read_frame = 0

    self.enabled = False
    self.ccm_enabled = False
    self.curves_enabled = True
    self.curves_lead_enabled = True
    self.lead_enabled = True
    self.signal_speed = 0.0  # m/s; 0 disables the signal trigger
    self.stop_enabled = True
    self.signal_lane_width = 0.0  # m; 0 keeps the unqualified blinker+speed signal trigger
    self.ccm_launch_enabled = False

    self.curve_filter = FirstOrderFilter(0.0, CURVE_FILTER_TIME, DT_CTRL)
    self.lead_filter = FirstOrderFilter(0.0, LEAD_FILTER_TIME, DT_CTRL)

    self.experimental_mode = False
    self._last_written_mode: bool | None = None
    self._ce_status = CE_OFF
    self._last_ce_status_written: int | None = None

    self.mode_hold_until = 0.0
    self.mode_false_since = 0.0
    self.manual_hold_until = 0.0

    # CCM state (StarPilot ConditionalModePolicy._ccm counterparts)
    self.ccm_chill = False
    self.ccm_hold_until = 0.0
    self.ccm_candidate_reason = None
    self.ccm_candidate_since = 0.0
    self.ccm_false_since = 0.0

    # stop-light / chill-scene state (StarPilot stop.py / chill_scene.py counterparts)
    self._stop_detector = _StopLightDetector(DT_CTRL)
    self.stop_release_suppress_until = 0.0
    self._launch_active = False
    self._lane_last_model_stamp: int | None = None
    self._lane_frame_count = 0
    self._lane_widths: tuple[float, float] | None = None

    # StarPilot LeadDetector fallback (sunnypilot/carrot/lead_tracking.py port). Imported lazily
    # on first use: lead_tracking -> common.realtime pulls the fcntl hardware chain, which the
    # DT_CTRL inlining above deliberately avoids so this module stays importable on PC.
    # Fallback only: it keeps the slow-lead judge alive through a short radarState lead dropout;
    # a healthy lead reaches the judges untouched, so a working factory radar sees no change.
    self._lead_detector = None            # LeadDetector once lazily built, or False when unavailable
    self._lead_source_max_age_s = 0.25    # StarPilot lead_tracking.py:24 SOURCE_MAX_AGE_S
    self._lead_cached_tracked: bool | None = None
    self._lead_last_model_stamp = 0

    # initial read so toggles/configure values apply from the first frame, not after the
    # first 1 s refresh tick
    self._read_params()

  def _read_params(self) -> None:
    self.enabled = self.CP.openpilotLongitudinalControl and self.params.get_bool("ConditionalExperimental")
    self.ccm_enabled = self.CP.openpilotLongitudinalControl and self.params.get_bool("ConditionalChill")
    # get_bool never consults the registered default, so default-on keys must go through
    # get(..., return_default=True) or an untouched install reads them as False.
    self.curves_enabled = bool(self.params.get("CECurves", return_default=True))
    self.curves_lead_enabled = bool(self.params.get("CECurvesLead", return_default=True))
    self.lead_enabled = bool(self.params.get("CELead", return_default=True))
    try:
      self.signal_speed = float(self.params.get("CESignalSpeed", return_default=True))
    except (TypeError, ValueError):
      self.signal_speed = 0.0
    self.stop_enabled = bool(self.params.get("CEStopLights", return_default=True))
    try:
      self.signal_lane_width = float(self.params.get("CESignalLaneWidth", return_default=True))
    except (TypeError, ValueError):
      self.signal_lane_width = 0.0
    self.ccm_launch_enabled = self.CP.openpilotLongitudinalControl and bool(self.params.get("CEChillLaunch", return_default=True))

  @property
  def manual_override_active(self) -> bool:
    return self._now() < self.manual_hold_until

  def update(self, CS, sm) -> bool:
    """Run every selfdrived frame (100 Hz). Returns the experimental mode."""
    self.frame += 1
    now = self._now()

    if self.frame % int(PARAMS_READ_PERIOD / DT_CTRL) == 0:
      self._read_params()

    standstill = bool(CS.standstill)

    # A manual switch (wheel long press via selfdrived_zp, or the onroad button) writes the
    # ExperimentalMode param itself. Any divergence from what we last wrote is a driver action:
    # adopt it and muzzle the conditions for a while.
    if self._last_written_mode is not None and not self.manual_override_active:
      param_mode = self.params.get_bool("ExperimentalMode")
      if param_mode != self._last_written_mode:
        self.manual_hold_until = now + MANUAL_HOLD_SECONDS
        self.experimental_mode = param_mode

    if self.manual_override_active:
      self._reset_holds()
      self.experimental_mode = self.params.get_bool("ExperimentalMode")
      self._publish(self.experimental_mode, CE_MANUAL)
      return self.experimental_mode

    if not self.enabled and not self.ccm_enabled:
      # Both master switches off: pure manual behaviour, nothing to do. One publish so a
      # stale CEStatus gets cleared, then go quiet.
      self._stop_detector.reset()
      self._launch_active = False
      self.stop_release_suppress_until = 0.0
      self._publish(self.params.get_bool("ExperimentalMode"), CE_OFF)
      self._reset_holds()
      return self.experimental_mode

    # Evidence layer: the model-fed stop detector and chill scene update every frame so
    # holds survive standstill freezes and both mode branches consume the same observation.
    v_ego = float(CS.vEgo)
    horizon = self._model_horizon(sm)
    stop_obs = self._update_stop_detector(CS, sm, v_ego, horizon, now)
    chill_obs = self._update_chill_scene(sm, v_ego, horizon, stop_obs)

    if self.ccm_enabled:
      # Conditional Chill (StarPilot CCM): the reverse conditional owns the mode
      # when its master switch is on; the CEM triggers double as its vetoes.
      return self._update_ccm(CS, sm, now, v_ego, stop_obs, chill_obs)

    if standstill:
      # Freeze: neither evaluate conditions nor drop the mode while stopped.
      return self.experimental_mode

    status, triggered = self._evaluate(CS, sm, v_ego, stop_obs, now)

    if triggered:
      self.mode_hold_until = now + TRANSITION_GUARD_TIME
      self.mode_false_since = 0.0
    elif self.experimental_mode and self.mode_false_since == 0.0:
      self.mode_false_since = now
    elif not self.experimental_mode:
      self.mode_false_since = 0.0

    hold_active = now < self.mode_hold_until
    buffer_active = self.mode_false_since != 0.0 and (now - self.mode_false_since) < TRANSITION_BUFFER_TIME
    self.experimental_mode = triggered or hold_active or buffer_active

    ce_value = status if self.experimental_mode else CE_OFF
    self._publish(self.experimental_mode, ce_value)
    return self.experimental_mode

  # ---- Conditional Chill Mode (StarPilot _ccm port) ------------------------ #

  def _ccm_veto(self, CS, sm, v_ego: float, stop_obs, chill_obs) -> tuple[bool, int]:
    """Complex-scene vetoes: experimental is forced back on immediately.

    StarPilot additionally vetoes on stop signs and its planner's
    forcing-stop latch - evidence selfdrived does not subscribe to, so those
    fields are absent here rather than assumed negative.
    """
    following_lead = self._following_lead(sm)
    if self.curves_enabled and (self.curves_lead_enabled or not following_lead):
      if self._curve_detected(sm, v_ego):
        return True, CE_CURVES
    if self._slow_lead(sm, v_ego):
      return True, CE_LEAD
    if CS.leftBlinker or CS.rightBlinker:
      # StarPilot vetoes on any blinker regardless of speed.
      return True, CE_SIGNAL
    if stop_obs[0]:
      # StarPilot vetoes on the stop-light detector unconditionally (policy.py:495).
      return True, CE_STOP
    if chill_obs[0]:
      # StarPilot vetoes on the low-speed stop scene unless a launch is active
      # (policy.py:499,503); the launch waive below handles the exception.
      return True, CE_CCM_VETO
    return False, CE_OFF

  def _ccm_candidate(self, CS, sm, v_ego: float, launch: bool) -> tuple[bool, int]:
    """Open-road / stable-lead / launch chill candidates (StarPilot policy.py:519-534)."""
    if launch:
      return True, CE_CCM_LAUNCH  # policy.py:520-521
    lead_status = self._following_lead(sm)
    if not lead_status:
      try:
        v_cruise = float(CS.vCruise)
      except (AttributeError, TypeError, ValueError):
        v_cruise = 0.0
      if v_ego >= CCM_SPEED_MPS and v_cruise - v_ego >= CCM_SET_SPEED_MARGIN_MPS:
        return True, CE_CCM_SPEED
      return False, CE_OFF
    if v_ego >= CCM_SPEED_WITH_LEAD_MPS and self._stable_lead(sm, v_ego):
      return True, CE_CCM_LEAD
    return False, CE_OFF

  def _stable_lead(self, sm, v_ego: float) -> bool:
    """StarPilot _stable_lead verbatim math on the radarState lead."""
    try:
      lead = sm["radarState"].leadOne
      distance = float(lead.dRel)
      lead_speed = float(lead.vLead)
      accel = float(lead.aLeadK)
    except (KeyError, TypeError, AttributeError):
      return False
    # RadarState.LeadData uses `present`; `.status` is CarControlSP's name.
    if not bool(lead.present):
      return False
    # radar presence is authoritative; vision-only leads need model confidence
    radar = bool(getattr(lead, "radar", True))
    probability = getattr(lead, "modelProb", None)
    confident = radar or (probability is not None and math.isfinite(float(probability)) and float(probability) >= 0.9)
    if not confident:
      return False
    max_distance = min(90.0, max(35.0, v_ego * 4.5))
    max_closing = max(1.25, 0.05 * v_ego)
    return bool(distance < max_distance and lead_speed > 1.5
                and max(0.0, -accel) <= 0.2 and max(0.0, v_ego - lead_speed) <= max_closing)

  def _update_ccm(self, CS, sm, now: float, v_ego: float, stop_obs, chill_obs) -> bool:
    veto, veto_status = self._ccm_veto(CS, sm, v_ego, stop_obs, chill_obs)
    launch = self.ccm_launch_enabled and bool(chill_obs[1])  # policy.py:501 ccm_launch and launch_candidate
    if veto or (CS.standstill and not launch):  # policy.py:503: launch waives the standstill veto
      # StarPilot hard veto (standstill included): chill drops, experimental on.
      self.ccm_chill = False
      self.ccm_candidate_reason = None
      self.ccm_candidate_since = 0.0
      self.ccm_false_since = 0.0
      self.experimental_mode = True
      self._publish(True, veto_status or CE_CCM_VETO)
      return True

    candidate, candidate_status = self._ccm_candidate(CS, sm, v_ego, launch)
    if candidate:
      if candidate_status != self.ccm_candidate_reason:
        self.ccm_candidate_reason = candidate_status
        self.ccm_candidate_since = now
      self.ccm_false_since = 0.0
      # CCM_LAUNCH_CONFIRM_S is 0.0 (policy.py:24); launch chills immediately.
      confirm = CCM_SPEED_CONFIRM_S if candidate_status == CE_CCM_SPEED else CCM_LEAD_CONFIRM_S if candidate_status == CE_CCM_LEAD else 0.0
      if self.ccm_chill or now - self.ccm_candidate_since >= confirm:
        self.ccm_chill = True
        self.ccm_hold_until = max(self.ccm_hold_until, now + CCM_MIN_DWELL_S)
    else:
      self.ccm_candidate_reason = None
      if self.ccm_chill and self.ccm_false_since == 0.0:
        self.ccm_false_since = now
      hold = now < self.ccm_hold_until
      buffer = self.ccm_false_since != 0.0 and (now - self.ccm_false_since) < CCM_EXIT_BUFFER_S
      if self.ccm_chill and not (hold or buffer):
        self.ccm_chill = False

    self.experimental_mode = not self.ccm_chill
    if self.ccm_chill:
      status = candidate_status if candidate else CE_OFF
    elif veto_status != CE_OFF:
      status = veto_status
    else:
      status = CE_OFF
    self._publish(self.experimental_mode, status)
    return self.experimental_mode

  def _evaluate(self, CS, sm, v_ego: float, stop_obs, now: float) -> tuple[int, bool]:
    """Returns (status_if_triggered, triggered). Conditions ordered by priority."""
    if now < self.stop_release_suppress_until:
      # StarPilot suppresses triggers during the quiet period after a stop release
      # so the launch does not immediately flip the mode back (policy.py:349,439).
      return CE_OFF, False

    following_lead = self._following_lead(sm)

    if self.curves_enabled and (self.curves_lead_enabled or not following_lead):
      if self._curve_detected(sm, v_ego):
        return CE_CURVES, True

    if self.lead_enabled and v_ego <= LEAD_MAX_EGO and self._slow_lead(sm, v_ego):
      return CE_LEAD, True

    if self.signal_speed > 0.0 and v_ego < self.signal_speed and (CS.leftBlinker or CS.rightBlinker):
      # StarPilot qualifies the signal trigger with the blinker-side lane width
      # (policy.py:392-399 + signal_lane.py). With CESignalLaneWidth unset (0.0)
      # the pre-existing blinker+speed behaviour is unchanged.
      if self.signal_lane_width <= 0.0 or self._blinker_side_lane_narrow(sm, CS, v_ego):
        return CE_SIGNAL, True

    if self.stop_enabled and stop_obs[0]:
      # CEM_STOP: the committed model-length stop light (policy.py:404-405; the
      # forcing_stop half has no sp source, so only the detector half applies).
      return CE_STOP, True

    return CE_OFF, False

  # ---- stop-light / chill-scene / signal-lane evidence (model-fed) ------------ #

  @staticmethod
  def _model_horizon(sm) -> float | None:
    """Planned-path forward extent (projection.py:213-238): the last position.x
    plus the bend excess, so a curved plan does not read as a shortened one."""
    try:
      model = sm["modelV2"]
      xs = tuple(float(v) for v in model.position.x)
      ys = tuple(float(v) for v in model.position.y)
    except (KeyError, TypeError, AttributeError, ValueError, OverflowError):
      return None
    if len(xs) != ModelConstants.IDX_N or len(ys) != ModelConstants.IDX_N:
      return None
    if any(not math.isfinite(v) or not 0.0 <= v <= 500.0 for v in xs):
      return None
    if any(not math.isfinite(v) or not -500.0 <= v <= 500.0 for v in ys):
      return None
    if any(b < a for a, b in zip(xs, xs[1:], strict=False)):  # projection.py:222
      return None
    bend = sum(math.hypot(x1 - x0, y1 - y0) - (x1 - x0)  # projection.py:237 _bend_excess
               for x0, x1, y0, y1 in zip(xs, xs[1:], ys, ys[1:], strict=False))
    return min(xs[-1] + bend, 500.0)  # projection.py:224

  @staticmethod
  def _lead_snapshot(sm) -> tuple[bool, float, float, float | None, float | None] | None:
    """(present, dRel, vLead, vRel, aLeadK) from radarState.leadOne; None when the
    source is unavailable. sp's cereal renamed cp's LeadData.status to present."""
    try:
      lead = sm["radarState"].leadOne
      present = bool(lead.present)
      distance = float(lead.dRel)
      speed = float(lead.vLead)
    except (KeyError, TypeError, AttributeError, ValueError):
      return None
    v_rel = accel = None
    try:
      v_rel = float(lead.vRel)  # log.capnp:775; chill_scene.py:28 uses the raw value only
    except (TypeError, AttributeError, ValueError):
      pass
    try:
      accel = float(lead.aLeadK)
    except (TypeError, AttributeError, ValueError):
      pass
    return present, distance, speed, v_rel, accel

  @staticmethod
  def _plan_stop_bit(sm) -> bool | None:
    """Plan/model stop bit for release vetoes. StarPilot reads the planner's
    should_stop (projection.py:746-747); sp exposes longitudinalPlan.shouldStop
    (log.capnp:1311) with modelV2.action.shouldStop (log.capnp:1232) as fallback.
    None must never prove a release (stop.py:163 requires `is False`), and this
    bit only ever vetoes - it cannot acquire a light (stop.py:3-4)."""
    try:
      return bool(sm["longitudinalPlan"].shouldStop)
    except (KeyError, TypeError, AttributeError, ValueError):
      pass
    try:
      return bool(sm["modelV2"].action.shouldStop)
    except (KeyError, TypeError, AttributeError, ValueError):
      return None

  @staticmethod
  def _plan_throttle_bits(sm) -> tuple[bool, bool]:
    """(should_stop, allow_throttle) from longitudinalPlan (log.capnp:1311-1312);
    missing evidence reads as (False, True) - chill_scene.py:120-121 treats None
    as a no-veto, so launch eligibility only depends on published bits."""
    try:
      plan = sm["longitudinalPlan"]
      return bool(plan.shouldStop), bool(plan.allowThrottle)
    except (KeyError, TypeError, AttributeError, ValueError):
      return False, True

  def _update_stop_detector(self, CS, sm, v_ego: float, horizon: float | None, now: float) -> tuple[bool, bool]:
    """Feed the stop detector the sp-reachable subset of StarPilot's StopFrame
    (projection.py:644-672). Returns (light_detected, model_stopping)."""
    lead = self._lead_snapshot(sm)
    lead_present = bool(lead[0]) if lead is not None else False
    lead_distance = lead[1] if lead is not None and lead[0] else None
    should_stop = self._plan_stop_bit(sm)
    standstill = bool(CS.standstill)

    # committed-turn scene (turn_scene.py:26-45): standstill/too fast/no blinker is
    # a known no; the active branch needs the steering angle or a measured curve
    turn_scene = False
    if not standstill and v_ego <= TURN_MAX_SPEED_MPS and (CS.leftBlinker or CS.rightBlinker):
      try:
        angle = float(CS.steeringAngleDeg)
      except (TypeError, AttributeError, ValueError):
        angle = None
      try:
        curvature = abs(float(sm["controlsState"].desiredCurvature))
        driving_in_curve = curvature * v_ego * v_ego >= TURN_CURVE_LAT_ACC_MPS2
      except (KeyError, TypeError, AttributeError, ValueError):
        driving_in_curve = False
      turn_scene = driving_in_curve or (angle is not None and abs(angle) >= TURN_MIN_STEERING_ANGLE_DEG)

    light_detected, model_stopping, released = self._stop_detector.update(
      v_ego, horizon, lead_present, lead_distance, should_stop, turn_scene, now, DT_CTRL)
    if released:
      # policy.py:349,417-418,431-432: a stop release always opens the 2 s quiet period.
      self.stop_release_suppress_until = now + CEM_STOP_RELEASE_SUPPRESS_S
    return light_detected, model_stopping

  def _update_chill_scene(self, sm, v_ego: float, horizon: float | None, stop_obs) -> tuple[bool, bool]:
    """StarPilot ChillSceneDetector evidence (chill_scene.py): returns
    (low_speed_stop_scene, launch_candidate). low_speed_stop is the CCM veto
    evidence (policy.py:499); the launch latch is one-shot per low-speed scene
    with its frozen exit at LAUNCH_EXIT_MPS (chill_scene.py:133-181)."""
    raw_model_stopped = horizon < FROZEN_RAW_STOP_DISTANCE_M if horizon is not None else False  # projection.py:730

    # low_speed_stop (chill_scene.py:88-108); unknown sources read as no-veto here
    if v_ego >= LOW_SPEED_STOP_MAX_MPS:  # chill_scene.py:89-90
      low_speed_stop = False
    elif raw_model_stopped or stop_obs[1]:  # chill_scene.py:91
      low_speed_stop = True
    else:
      lead = self._lead_snapshot(sm)
      low_speed_stop = bool(lead is not None and lead[0] and
                            lead[1] < max(40.0, v_ego * 4.5) and lead[2] < max(6.0, v_ego + 0.5))  # chill_scene.py:98-101

    # launch latch (chill_scene.py:110-181); starpilot additionally checks sign
    # recognition / forcing-stop / red-light owners sp does not publish
    if self._launch_active and v_ego >= LAUNCH_EXIT_MPS:  # chill_scene.py:172-174
      self._launch_active = False
    stop_scene = raw_model_stopped or stop_obs[1] or stop_obs[0]  # chill_scene.py:116-119 subset
    should_stop, allow_throttle = self._plan_throttle_bits(sm)
    try:
      selfdrive_enabled = bool(sm["carControl"].enabled)  # chill_scene.py:114
    except (KeyError, TypeError, AttributeError, ValueError):
      selfdrive_enabled = False
    if not self._launch_active and v_ego > LAUNCH_ENTRY_MAX_MPS:  # chill_scene.py:112
      eligible = False
    elif not selfdrive_enabled or stop_scene:
      eligible = False
    elif should_stop or not allow_throttle:  # chill_scene.py:120-121
      eligible = False
    else:
      lead = self._lead_snapshot(sm)
      if lead is None:
        eligible = False  # chill_scene.py:158-163: unknown radar evidence cannot launch
      elif not lead[0]:
        eligible = True  # "go" with no lead, chill_scene.py:122-123
      else:
        v_rel, accel = lead[3], lead[4]
        closing = max(0.0, v_ego - lead[2])
        eligible = bool(lead[2] >= 0.35 and lead[2] - v_ego >= 0.2 and
                        v_rel is not None and v_rel >= 0.2 and
                        accel is not None and accel >= 0.08 and max(0.0, -accel) <= 0.2 and
                        closing <= 0.75)  # chill_scene.py:127-130 departing test
    self._launch_active = eligible  # chill_scene.py:179
    return low_speed_stop, eligible

  def _blinker_side_lane_narrow(self, sm, CS, v_ego: float) -> bool:
    """True only when the blinker-side adjacent lane is measured narrower than
    CESignalLaneWidth (policy.py:397 `not scene.lane_available`, signal_lane.py:181-185).
    Unknown geometry is not evidence of a missing lane (signal_lane.py:6-7)."""
    width = self._lane_width(sm, bool(CS.leftBlinker), v_ego)
    return width is not None and width < self.signal_lane_width

  def _lane_width(self, sm, left: bool, v_ego: float) -> float | None:
    """Cached lane widths recomputed every 4th new model frame (signal_lane.py:172-178),
    reset below the lane-change speed (signal_lane.py:166-168)."""
    try:
      model = sm["modelV2"]
    except (KeyError, TypeError):
      return None
    new_frame = False
    stamp = getattr(model, "logMonoTime", None)
    if type(stamp) is int and stamp != self._lane_last_model_stamp:
      self._lane_last_model_stamp = stamp
      new_frame = True
    if v_ego < LANE_CHANGE_SPEED_MIN_MPS:  # signal_lane.py:166-168
      self._lane_frame_count = 0
      self._lane_widths = (0.0, 0.0)
    elif new_frame:
      self._lane_frame_count += 1
      if self._lane_frame_count % SIGNAL_LANE_CADENCE_FRAMES == 0:
        self._lane_widths = _lane_model_widths(model)
    widths = self._lane_widths
    if widths is None:
      return None
    return widths[0] if left else widths[1]  # signal_lane.py:181

  def _curve_detected(self, sm, v_ego: float) -> bool:
    if v_ego <= CURVE_MIN_EGO:
      self.curve_filter.update(0.0)
      return False

    try:
      curvature = abs(float(sm["controlsState"].desiredCurvature))
    except (KeyError, TypeError, AttributeError):
      self.curve_filter.update(0.0)
      return False

    lat_acc = curvature * v_ego * v_ego
    self.curve_filter.update(lat_acc >= CURVE_LAT_ACC)
    return bool(self.curve_filter.x >= CURVE_THRESHOLD)

  def _lead_hold_active(self, sm, v_ego: float) -> bool:
    """True while the LeadDetector's 0.5 s consensus (threshold 1-1/e) still counts the last known lead.

    Steps the detector once per model frame; it dedups by the model stamp itself
    (starpilot/lead_tracking.py:191-197), so calling this at 100 Hz is safe. Every source is
    bounded to SOURCE_MAX_AGE_S = 0.25 s against the newest stamp (lead_tracking.py:24), so a
    longer dropout resets the detector and the hold ends. The follow time is the 1.45 s floor
    StarPilot's host applies to planner headway (starpilot/curve_speed/host.py:131-136, 204);
    selfdrived has no planner headway view.
    """
    if self._lead_detector is None:
      try:
        from openpilot.sunnypilot.carrot.lead_tracking import LeadDetector
        self._lead_detector = LeadDetector()
      except Exception:
        self._lead_detector = False
    detector = self._lead_detector
    if detector is False:
      return False
    try:
      radar_stamp = sm.logMonoTime.get("radarState", 0)
      model_stamp = sm.logMonoTime.get("modelV2", 0)
      car_stamp = sm.logMonoTime.get("carState", 0)
      newest = max(radar_stamp, model_stamp, car_stamp)
      fresh = (type(stamp) is int and stamp > 0 and newest - stamp <= self._lead_source_max_age_s * 1e9
               for stamp in (radar_stamp, model_stamp, car_stamp))
      if not all(fresh):
        detector.reset()
        self._lead_cached_tracked = None
        return False
      observation = detector.step(
        sm["radarState"].leadOne, sm["modelV2"],
        speed_mps=v_ego,
        t_follow_s=1.45,
        standstill=bool(sm["carState"].standstill),
        observed_mono_s=model_stamp / 1e9,
        now_mono_s=newest / 1e9,
        radar_fresh=True,
        model_fresh=True,
        car_fresh=True,
        headway_fresh=True,
      )
      if model_stamp > self._lead_last_model_stamp:
        self._lead_last_model_stamp = model_stamp
        # Unknown on a NEW model tick means the detector reset (or advanced to unknown);
        # unknown on the SAME tick is just the per-model-frame dedup and the state is unchanged.
        self._lead_cached_tracked = observation.tracked
      return self._lead_cached_tracked is True
    except (KeyError, AttributeError, TypeError, ValueError, OverflowError):
      detector.reset()
      self._lead_cached_tracked = None
      return False

  def _slow_lead(self, sm, v_ego: float) -> bool:
    # Dropout fallback: while the detector consensus still holds the last known lead, a missing
    # or flickering leadOne freezes the filter instead of driving it to zero. A valid lead hits
    # neither branch below, so its behaviour is exactly the pre-fallback judge.
    held = self._lead_hold_active(sm, v_ego)
    try:
      lead = sm["radarState"].leadOne
      lead_status = bool(lead.present)   # RadarState.LeadData names it `present`
      lead_distance = float(lead.dRel)
      lead_speed = float(lead.vLead)
    except (KeyError, TypeError, AttributeError):
      if held:
        return bool(self.lead_filter.x >= _scale_threshold(v_ego))
      self.lead_filter.update(0.0)
      return False

    if not lead_status:
      if held:
        return bool(self.lead_filter.x >= _scale_threshold(v_ego))
      self.lead_filter.update(0.0)
      return False

    closing_speed = max(0.0, v_ego - lead_speed)
    min_closing_speed = max(LEAD_MIN_CLOSING_SPEED, 0.04 * v_ego)
    in_range = lead_distance < max(LEAD_CONTINUITY_MIN_DISTANCE, v_ego * LEAD_CONTINUITY_MAX_TIME)

    candidate = bool(in_range and closing_speed >= min_closing_speed and lead_speed < v_ego - 0.5)
    self.lead_filter.update(candidate)
    return bool(self.lead_filter.x >= _scale_threshold(v_ego))

  @staticmethod
  def _following_lead(sm) -> bool:
    try:
      # RadarState.LeadData's presence bit is `present` (@11); `status` is
      # CarControlSP.LeadData's name for the same bit. The old read threw into
      # the except and made every real drive look lead-less.
      return bool(sm["radarState"].leadOne.present)
    except (KeyError, TypeError, AttributeError):
      return False

  def _publish(self, mode: bool, ce_status: int) -> None:
    if mode != self._last_written_mode:
      self.params.put_bool("ExperimentalMode", mode)
      self._last_written_mode = mode
    if ce_status != self._last_ce_status_written:
      try:
        self.params.put_int("CEStatus", ce_status)
      except Exception:
        pass  # CEStatus is a UI hint only; never let it break the mode logic
      self._last_ce_status_written = ce_status
    self._ce_status = ce_status

  def _reset_holds(self) -> None:
    self.mode_hold_until = 0.0
    self.mode_false_since = 0.0
