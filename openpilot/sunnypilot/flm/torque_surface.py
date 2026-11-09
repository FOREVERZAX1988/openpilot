"""StarPilot GM universal FLM surface math, carved verbatim for the full30 coordinate path.

Source: E:/StarPilot/openpilot/starpilot/flm/torque_surface.py (StarPilot branch Dom,
SHA of the copied ranges). This port keeps the GM/universal surface block byte-identical
(lines 305-828) plus the SurfaceInput frame contract (lines 103-139) and the frozen
_gm_* stage constants (lines 305-390, 392-828). Carve boundary, documented per the
fork-port-audit discipline:

- EXCLUDED (lines 19-101, 142-304): the Ioniq 6 frozen reconstruction (Ioniq6Surface,
  directional_taper_target, evaluate, ...) depends on starpilot.lateral.ioniq6_policy
  and bolt_shaping. It is Hyundai-model-specific shaping and is not part of the
  full30 universal coordinate path; it returns with the controller wiring batch.
- EXCLUDED (lines 830-921): GmFlmBinding (live controller owner state) depends on
  flm.manual_trial and the live trial owner. Wiring-batch scope.

This module computes stage values only. It is NOT a live tune, does not read Params,
does not write native parameters and is not permission to actuate. The controller
still owns its PID, filters, active state, reset order and final output conversion.
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

import numpy as np
@dataclass(frozen=True)
class SurfaceInput:
  """Pure stage sample with the controller-owned directional filter output.

  Live integration must filter directional_taper_target before evaluating FF.
  The standard-only 2023 unwind multiplier and firmware-2025 output cap remain
  in the caller. Variant is an applicability tag, not a substitute for FW proof.
  """
  speed: float
  setpoint: float
  jerk: float
  desired_angle_deg: float
  actual_angle_deg: float
  output_torque: float
  steering_pressed: bool
  filtered_directional_taper: float

  def __post_init__(self):
    values = (self.speed, self.setpoint, self.jerk, self.desired_angle_deg,
              self.actual_angle_deg, self.output_torque)
    if (type(self.steering_pressed) is not bool or
        any(isinstance(x, bool) or not isinstance(x, (int, float)) for x in values) or
        isinstance(self.filtered_directional_taper, bool) or not isinstance(self.filtered_directional_taper, (int, float))):
      raise ValueError("invalid surface input type")
    try:
      finite = all(math.isfinite(x) for x in values)
    except (OverflowError, ValueError) as exc:
      raise ValueError("invalid surface input") from exc
    if (not finite or not 0.0 <= self.speed <= 90.0 or abs(self.setpoint) > 20.0 or abs(self.jerk) > 20.0 or
        abs(self.desired_angle_deg) > 1080.0 or abs(self.actual_angle_deg) > 1080.0 or abs(self.output_torque) > 1.0):
      raise ValueError("invalid surface input")
    try:
      valid_filtered = math.isfinite(self.filtered_directional_taper) and -2.0 <= self.filtered_directional_taper <= 2.0
    except (OverflowError, ValueError) as exc:
      raise ValueError("invalid filtered directional taper") from exc
    if not valid_filtered:
      raise ValueError("invalid filtered directional taper")

# Frozen original GM/universal surface stages; immutable profile input.
_gm_BOLT_2022_2023_CENTER_FRICTION_THRESHOLD_BUMP = 0.08
_gm_BOLT_2022_2023_CENTER_FRICTION_THRESHOLD_LAT = 0.18
_gm_BOLT_2022_2023_CENTER_FRICTION_THRESHOLD_LAT_WIDTH = 0.06
_gm_BOLT_2022_2023_CENTER_FRICTION_THRESHOLD_SPEED = 6.7
_gm_BOLT_2022_2023_CENTER_FRICTION_THRESHOLD_SPEED_WIDTH = 1.5
_gm_BOLT_2022_2023_CENTER_TAPER_LAT = 0.18
_gm_BOLT_2022_2023_CENTER_TAPER_LAT_WIDTH = 0.03
_gm_BOLT_2022_2023_CENTER_TAPER_MAX = 0.11
_gm_BOLT_2022_2023_CENTER_TAPER_SPEED = 25.0
_gm_BOLT_2022_2023_CENTER_TAPER_SPEED_WIDTH = 2.5
_gm_BOLT_2022_2023_FF_CUTOFF = 1.35
_gm_BOLT_2022_2023_FF_CUTOFF_WIDTH = 0.28
_gm_BOLT_2022_2023_FF_GAIN_LEFT = 0.11
_gm_BOLT_2022_2023_FF_GAIN_RIGHT = 0.06
_gm_BOLT_2022_2023_FF_ONSET = 0.12
_gm_BOLT_2022_2023_FF_ONSET_WIDTH = 0.07
_gm_BOLT_2022_2023_FRICTION_JERK_RISE = 0.26
_gm_BOLT_2022_2023_FRICTION_LAT_RISE = 0.22
_gm_BOLT_2022_2023_PHASE_SCALE = 0.12
_gm_BOLT_2022_2023_TRANSITION_SPEED = 9.0
_gm_BOLT_2022_2023_TURN_IN_BOOST_LEFT = 0.18
_gm_BOLT_2022_2023_TURN_IN_BOOST_RIGHT = 0.13
_gm_BOLT_2022_2023_TURN_IN_THRESHOLD_REDUCTION_LEFT = 0.16
_gm_BOLT_2022_2023_TURN_IN_THRESHOLD_REDUCTION_RIGHT = 0.12
_gm_BOLT_2022_2023_UNWIND_TAPER_LEFT = 0.38
_gm_BOLT_2022_2023_UNWIND_TAPER_RIGHT = 0.4
_gm_BOLT_2022_2023_UNWIND_THRESHOLD_INCREASE_LEFT = 0.26
_gm_BOLT_2022_2023_UNWIND_THRESHOLD_INCREASE_RIGHT = 0.28
_gm_FLM_FRICTION_SPEED_KNOTS = [0.0, 5.0, 10.0, 15.0, 25.0]
_gm_IONIQ_6_CENTER_TAPER_LAT = 0.24
_gm_IONIQ_6_CENTER_TAPER_LAT_WIDTH = 0.025
_gm_IONIQ_6_CENTER_TAPER_SPEED = 18.0
_gm_IONIQ_6_CENTER_TAPER_SPEED_WIDTH = 2.5
_gm_IONIQ_6_CRAWL_TURN_IN_FF_LAT = 0.06
_gm_IONIQ_6_CRAWL_TURN_IN_FF_LAT_WIDTH = 0.035
_gm_IONIQ_6_CRAWL_TURN_IN_FF_SPEED = 5.3
_gm_IONIQ_6_CRAWL_TURN_IN_FF_SPEED_WIDTH = 1.0
_gm_IONIQ_6_CURVY_SPEED_MAX = 21.5
_gm_IONIQ_6_CURVY_SPEED_MAX_WIDTH = 1.8
_gm_IONIQ_6_CURVY_SPEED_MIN = 7.2
_gm_IONIQ_6_CURVY_SPEED_MIN_WIDTH = 1.1
_gm_IONIQ_6_CURVY_TURN_IN_TRIM_LAT_CUTOFF_WIDTH = 0.3
_gm_IONIQ_6_CURVY_TURN_IN_TRIM_LAT_END = 2.5
_gm_IONIQ_6_CURVY_TURN_IN_TRIM_LAT_ONSET_WIDTH = 0.18
_gm_IONIQ_6_CURVY_TURN_IN_TRIM_LAT_START = 1.0
_gm_IONIQ_6_CURVY_TURN_IN_TRIM_SPEED_MAX = 20.5
_gm_IONIQ_6_CURVY_TURN_IN_TRIM_SPEED_MIN = 11.5
_gm_IONIQ_6_CURVY_TURN_IN_TRIM_SPEED_WIDTH = 1.2
_gm_IONIQ_6_CURVY_UNWIND_LAT_CUTOFF_WIDTH = 0.55
_gm_IONIQ_6_CURVY_UNWIND_LAT_END = 3.6
_gm_IONIQ_6_CURVY_UNWIND_LAT_ONSET_WIDTH = 0.14
_gm_IONIQ_6_CURVY_UNWIND_LAT_START = 0.45
_gm_IONIQ_6_FF_CUTOFF = 0.48
_gm_IONIQ_6_FF_CUTOFF_WIDTH = 0.12
_gm_IONIQ_6_FF_ONSET = 0.1
_gm_IONIQ_6_FF_ONSET_WIDTH = 0.04
_gm_IONIQ_6_FRICTION_JERK_RISE = 0.24
_gm_IONIQ_6_FRICTION_LAT_RISE = 0.2
_gm_IONIQ_6_HIGHWAY_CENTER_TAPER_LAT = 0.1
_gm_IONIQ_6_HIGHWAY_CENTER_TAPER_LAT_WIDTH = 0.035
_gm_IONIQ_6_HIGHWAY_CENTER_TAPER_SPEED = 24.5
_gm_IONIQ_6_HIGHWAY_CENTER_TAPER_SPEED_WIDTH = 1.8
_gm_IONIQ_6_LOW_SPEED_ANGLE_ASSIST_ADD_BP = [0.0, 0.35, 0.65, 1.0]
_gm_IONIQ_6_LOW_SPEED_ANGLE_ASSIST_ADD_V = [1.0, 1.0, 0.88, 0.08]
_gm_IONIQ_6_LOW_SPEED_ANGLE_ASSIST_DESIRED_ANGLE = 5.5
_gm_IONIQ_6_LOW_SPEED_ANGLE_ASSIST_DESIRED_ANGLE_WIDTH = 2.4
_gm_IONIQ_6_LOW_SPEED_ANGLE_ASSIST_ERROR = 1.9
_gm_IONIQ_6_LOW_SPEED_ANGLE_ASSIST_ERROR_WIDTH = 1.2
_gm_IONIQ_6_LOW_SPEED_ANGLE_ASSIST_SPEED = 3.25
_gm_IONIQ_6_LOW_SPEED_ANGLE_ASSIST_SPEED_WIDTH = 0.45
_gm_IONIQ_6_LOW_SPEED_ANGLE_ASSIST_TRACK_RATIO_FLOOR = 0.26
_gm_IONIQ_6_LOW_SPEED_ANGLE_ASSIST_TRACK_RATIO_START = 0.66
_gm_IONIQ_6_LOW_SPEED_ANGLE_ASSIST_TRACK_RATIO_WIDTH = 0.12
_gm_IONIQ_6_LOW_SPEED_UNWIND_ASSIST_ACTUAL_ANGLE = 10.5
_gm_IONIQ_6_LOW_SPEED_UNWIND_ASSIST_ACTUAL_ANGLE_WIDTH = 4.0
_gm_IONIQ_6_LOW_SPEED_UNWIND_ASSIST_BLEND = 0.52
_gm_IONIQ_6_LOW_SPEED_UNWIND_ASSIST_ERROR = 1.6
_gm_IONIQ_6_LOW_SPEED_UNWIND_ASSIST_ERROR_WIDTH = 0.95
_gm_IONIQ_6_LOW_SPEED_UNWIND_ASSIST_MAX_TORQUE = 0.3
_gm_IONIQ_6_LOW_SPEED_UNWIND_ASSIST_SPEED = 3.35
_gm_IONIQ_6_LOW_SPEED_UNWIND_ASSIST_SPEED_WIDTH = 0.5
_gm_IONIQ_6_PHASE_SCALE = 0.1
_gm_IONIQ_6_TRANSITION_SPEED = 10.0
_gm_IONIQ_6_UNWIND_HIGH_SPEED_SPEED = 23.2
_gm_IONIQ_6_UNWIND_HIGH_SPEED_SPEED_WIDTH = 1.7

def _flm_profile_symbol(profile_key, suffix):
  return f"{profile_key}.{suffix}"

def _gm__bolt_2022_2023_low_speed_factor(surface, v_ego: float) -> float:
  return 1.0 / (1.0 + (max(v_ego, 0.0) / _gm_BOLT_2022_2023_TRANSITION_SPEED) ** 2)

def _gm__bolt_2022_2023_side_value(surface, desired_lateral_accel: float, left_value: float, right_value: float) -> float:
  return left_value if desired_lateral_accel >= 0.0 else right_value

def _gm__bolt_2022_2023_sigmoid(surface, x: float) -> float:
  return _gm__sigmoid(surface, x)

def _gm__bolt_2022_2023_transition_envelope(surface, v_ego: float, desired_lateral_accel: float, desired_lateral_jerk: float) -> float:
  lat_factor = 1.0 - math.exp(-abs(desired_lateral_accel) / _gm_BOLT_2022_2023_FRICTION_LAT_RISE)
  jerk_factor = 1.0 - math.exp(-abs(desired_lateral_jerk) / _gm_BOLT_2022_2023_FRICTION_JERK_RISE)
  return _gm__bolt_2022_2023_low_speed_factor(surface, v_ego) * lat_factor * jerk_factor

def _gm__bolt_2022_2023_transition_phase(surface, desired_lateral_accel: float, desired_lateral_jerk: float) -> float:
  return math.tanh((desired_lateral_accel * desired_lateral_jerk) / _gm_BOLT_2022_2023_PHASE_SCALE)

def _gm__flm_full_surface_curvy_speed_weight(surface, profile_key: str, v_ego: float) -> float:
  curvy_speed_min = surface.value(_flm_profile_symbol(profile_key, "curvy_speed_min"), _gm_IONIQ_6_CURVY_SPEED_MIN)
  curvy_speed_max = surface.value(_flm_profile_symbol(profile_key, "curvy_speed_max"), _gm_IONIQ_6_CURVY_SPEED_MAX)
  onset = _gm__sigmoid(surface, (max(v_ego, 0.0) - curvy_speed_min) / _gm_IONIQ_6_CURVY_SPEED_MIN_WIDTH)
  cutoff = _gm__sigmoid(surface, (curvy_speed_max - max(v_ego, 0.0)) / _gm_IONIQ_6_CURVY_SPEED_MAX_WIDTH)
  return onset * cutoff

def _gm__flm_full_surface_curvy_turn_in_trim_speed_weight(surface, profile_key: str, v_ego: float) -> float:
  curvy_turn_in_speed_min = surface.value(_flm_profile_symbol(profile_key, "curvy_turn_in_trim_speed_min"), _gm_IONIQ_6_CURVY_TURN_IN_TRIM_SPEED_MIN)
  curvy_turn_in_speed_max = surface.value(_flm_profile_symbol(profile_key, "curvy_turn_in_trim_speed_max"), _gm_IONIQ_6_CURVY_TURN_IN_TRIM_SPEED_MAX)
  onset = _gm__sigmoid(surface, (max(v_ego, 0.0) - curvy_turn_in_speed_min) / _gm_IONIQ_6_CURVY_TURN_IN_TRIM_SPEED_WIDTH)
  cutoff = _gm__sigmoid(surface, (curvy_turn_in_speed_max - max(v_ego, 0.0)) / _gm_IONIQ_6_CURVY_TURN_IN_TRIM_SPEED_WIDTH)
  return onset * cutoff

def _gm__flm_full_surface_low_speed_factor(surface, v_ego: float) -> float:
  return 1.0 / (1.0 + (max(v_ego, 0.0) / _gm_IONIQ_6_TRANSITION_SPEED) ** 2)

def _gm__flm_full_surface_side_value(surface, profile_key: str, desired_lateral_accel: float,
                                 suffix: str, left_default: float = 0.0, right_default: float = 0.0) -> float:
  if desired_lateral_accel >= 0.0:
    return surface.value(_flm_profile_symbol(profile_key, f"{suffix}_left"), left_default)
  return surface.value(_flm_profile_symbol(profile_key, f"{suffix}_right"), right_default)

def _gm__flm_full_surface_transition_envelope(surface, v_ego: float, desired_lateral_accel: float, desired_lateral_jerk: float) -> float:
  lat_factor = 1.0 - math.exp(-abs(desired_lateral_accel) / _gm_IONIQ_6_FRICTION_LAT_RISE)
  jerk_factor = 1.0 - math.exp(-abs(desired_lateral_jerk) / _gm_IONIQ_6_FRICTION_JERK_RISE)
  return _gm__flm_full_surface_low_speed_factor(surface, v_ego) * lat_factor * jerk_factor

def _gm__flm_full_surface_transition_phase(surface, desired_lateral_accel: float, desired_lateral_jerk: float) -> float:
  return math.tanh((desired_lateral_accel * desired_lateral_jerk) / _gm_IONIQ_6_PHASE_SCALE)

def _gm__sigmoid(surface, x: float) -> float:
  if x >= 0.0:
    z = math.exp(-x)
    return 1.0 / (1.0 + z)

  z = math.exp(x)
  return z / (1.0 + z)

def _gm_get_bolt_2022_2023_ff_scale(surface, desired_lateral_accel: float, desired_lateral_jerk: float, v_ego: float) -> float:
  if desired_lateral_accel == 0.0:
    return 1.0

  gain = _gm__bolt_2022_2023_side_value(surface,
    desired_lateral_accel,
    surface.value("gm_bolt_2022_2023.ff_gain_left", _gm_BOLT_2022_2023_FF_GAIN_LEFT),
    surface.value("gm_bolt_2022_2023.ff_gain_right", _gm_BOLT_2022_2023_FF_GAIN_RIGHT),
  )
  abs_lateral_accel = abs(desired_lateral_accel)
  onset = _gm__bolt_2022_2023_sigmoid(surface, (abs_lateral_accel - _gm_BOLT_2022_2023_FF_ONSET) / _gm_BOLT_2022_2023_FF_ONSET_WIDTH)
  cutoff = _gm__bolt_2022_2023_sigmoid(surface, (_gm_BOLT_2022_2023_FF_CUTOFF - abs_lateral_accel) / _gm_BOLT_2022_2023_FF_CUTOFF_WIDTH)
  extra_scale = gain * onset * cutoff
  speed_weight = _gm__bolt_2022_2023_sigmoid(surface, (v_ego - _gm_BOLT_2022_2023_CENTER_TAPER_SPEED) / _gm_BOLT_2022_2023_CENTER_TAPER_SPEED_WIDTH)
  center_weight = _gm__bolt_2022_2023_sigmoid(surface, (_gm_BOLT_2022_2023_CENTER_TAPER_LAT - abs_lateral_accel) / _gm_BOLT_2022_2023_CENTER_TAPER_LAT_WIDTH)
  center_taper = 1.0 - (surface.value("gm_bolt_2022_2023.center_taper_max", _gm_BOLT_2022_2023_CENTER_TAPER_MAX) * speed_weight * center_weight)
  low_speed_factor = _gm__bolt_2022_2023_low_speed_factor(surface, v_ego)
  transition_envelope = _gm__bolt_2022_2023_transition_envelope(surface, v_ego, desired_lateral_accel, desired_lateral_jerk)
  phase = _gm__bolt_2022_2023_transition_phase(surface, desired_lateral_accel, desired_lateral_jerk)
  turn_in_weight = max(phase, 0.0)
  unwind_weight = max(-phase, 0.0)
  turn_in_boost = 1.0 + (_gm__bolt_2022_2023_side_value(surface,
                          desired_lateral_accel,
                          surface.value("gm_bolt_2022_2023.turn_in_boost_left", _gm_BOLT_2022_2023_TURN_IN_BOOST_LEFT),
                          surface.value("gm_bolt_2022_2023.turn_in_boost_right", _gm_BOLT_2022_2023_TURN_IN_BOOST_RIGHT),
                        ) *
                          turn_in_weight * low_speed_factor)
  unwind_envelope = (0.25 + 0.75 * low_speed_factor) * (1.0 + 0.45 * transition_envelope)
  unwind_taper = 1.0 - (_gm__bolt_2022_2023_side_value(surface,
                         desired_lateral_accel,
                         surface.value("gm_bolt_2022_2023.unwind_taper_left", _gm_BOLT_2022_2023_UNWIND_TAPER_LEFT),
                         surface.value("gm_bolt_2022_2023.unwind_taper_right", _gm_BOLT_2022_2023_UNWIND_TAPER_RIGHT),
                       ) *
                         unwind_weight * unwind_envelope)
  return 1.0 + (extra_scale * center_taper * turn_in_boost * max(unwind_taper, 0.0))

def _gm_get_bolt_2022_2023_friction_threshold(surface, v_ego: float, desired_lateral_accel: float = 0.0, desired_lateral_jerk: float = 0.0) -> float:
  base_threshold = surface.base_threshold(v_ego)
  center_weight = _gm__bolt_2022_2023_sigmoid(surface,
    (_gm_BOLT_2022_2023_CENTER_FRICTION_THRESHOLD_LAT - abs(desired_lateral_accel)) /
    _gm_BOLT_2022_2023_CENTER_FRICTION_THRESHOLD_LAT_WIDTH
  )
  low_speed_weight = _gm__bolt_2022_2023_sigmoid(surface,
    (_gm_BOLT_2022_2023_CENTER_FRICTION_THRESHOLD_SPEED - v_ego) /
    _gm_BOLT_2022_2023_CENTER_FRICTION_THRESHOLD_SPEED_WIDTH
  )
  base_threshold += (_gm_BOLT_2022_2023_CENTER_FRICTION_THRESHOLD_BUMP * center_weight * low_speed_weight)
  transition_envelope = _gm__bolt_2022_2023_transition_envelope(surface, v_ego, desired_lateral_accel, desired_lateral_jerk)
  phase = _gm__bolt_2022_2023_transition_phase(surface, desired_lateral_accel, desired_lateral_jerk)
  turn_in_weight = max(phase, 0.0)
  unwind_weight = max(-phase, 0.0)
  threshold_scale = 1.0 - (_gm__bolt_2022_2023_side_value(surface,
                           desired_lateral_accel,
                           surface.value("gm_bolt_2022_2023.turn_in_threshold_reduction_left", _gm_BOLT_2022_2023_TURN_IN_THRESHOLD_REDUCTION_LEFT),
                           surface.value("gm_bolt_2022_2023.turn_in_threshold_reduction_right", _gm_BOLT_2022_2023_TURN_IN_THRESHOLD_REDUCTION_RIGHT),
                         ) *
                           transition_envelope * turn_in_weight)
  threshold_scale += (_gm__bolt_2022_2023_side_value(surface,
                      desired_lateral_accel,
                      surface.value("gm_bolt_2022_2023.unwind_threshold_increase_left", _gm_BOLT_2022_2023_UNWIND_THRESHOLD_INCREASE_LEFT),
                      surface.value("gm_bolt_2022_2023.unwind_threshold_increase_right", _gm_BOLT_2022_2023_UNWIND_THRESHOLD_INCREASE_RIGHT),
                    ) *
                      transition_envelope * unwind_weight)
  return base_threshold * min(max(threshold_scale, 0.84), 1.14)

def _gm_get_flm_full_surface_center_deadband_deg(surface, profile_key: str | None, v_ego: float) -> float:
  if not profile_key:
    return 0.0

  suffixes = (
    "center_deadband_crawl_deg",
    "center_deadband_low_deg",
    "center_deadband_mid_deg",
    "center_deadband_fast_deg",
    "center_deadband_highway_deg",
  )
  values = [
    surface.value(_flm_profile_symbol(profile_key, suffix), 0.0)
    for suffix in suffixes
  ]
  return float(np.interp(max(v_ego, 0.0), _gm_FLM_FRICTION_SPEED_KNOTS, values))

def _gm_get_flm_full_surface_center_taper_scale(surface, profile_key: str | None, desired_lateral_accel: float, v_ego: float,
                                            include_base_center: bool = False) -> float:
  if not profile_key:
    return 1.0

  reduction = 0.0
  if include_base_center and surface.supports(profile_key, "center_taper_max"):
    speed_weight = _gm__sigmoid(surface, (v_ego - _gm_IONIQ_6_CENTER_TAPER_SPEED) / _gm_IONIQ_6_CENTER_TAPER_SPEED_WIDTH)
    center_weight = _gm__sigmoid(surface, (_gm_IONIQ_6_CENTER_TAPER_LAT - abs(desired_lateral_accel)) / _gm_IONIQ_6_CENTER_TAPER_LAT_WIDTH)
    reduction += surface.value(_flm_profile_symbol(profile_key, "center_taper_max"), 0.0) * speed_weight * center_weight

  if surface.supports(profile_key, "highway_center_taper_max"):
    speed_weight = _gm__sigmoid(surface, (v_ego - _gm_IONIQ_6_HIGHWAY_CENTER_TAPER_SPEED) / _gm_IONIQ_6_HIGHWAY_CENTER_TAPER_SPEED_WIDTH)
    center_weight = _gm__sigmoid(surface, (_gm_IONIQ_6_HIGHWAY_CENTER_TAPER_LAT - abs(desired_lateral_accel)) / _gm_IONIQ_6_HIGHWAY_CENTER_TAPER_LAT_WIDTH)
    reduction += surface.value(_flm_profile_symbol(profile_key, "highway_center_taper_max"), 0.0) * speed_weight * center_weight

  return 1.0 - min(reduction, 0.20)

def _gm_get_flm_full_surface_ff_scale(surface, profile_key: str | None, desired_lateral_accel: float, desired_lateral_jerk: float, v_ego: float,
                                  include_base_ff: bool = False) -> float:
  if not profile_key or desired_lateral_accel == 0.0:
    return 1.0

  abs_lateral_accel = abs(desired_lateral_accel)
  phase = _gm__flm_full_surface_transition_phase(surface, desired_lateral_accel, desired_lateral_jerk)
  turn_in_weight = max(phase, 0.0)
  unwind_weight = max(-phase, 0.0)
  low_speed_factor = _gm__flm_full_surface_low_speed_factor(surface, v_ego)

  curvy_turn_in_speed_weight = _gm__flm_full_surface_curvy_turn_in_trim_speed_weight(surface, profile_key, v_ego)
  curvy_turn_in_lat_onset = _gm__sigmoid(surface,
    (abs_lateral_accel - _gm_IONIQ_6_CURVY_TURN_IN_TRIM_LAT_START) / _gm_IONIQ_6_CURVY_TURN_IN_TRIM_LAT_ONSET_WIDTH)
  curvy_turn_in_lat_cutoff = _gm__sigmoid(surface,
    (_gm_IONIQ_6_CURVY_TURN_IN_TRIM_LAT_END - abs_lateral_accel) / _gm_IONIQ_6_CURVY_TURN_IN_TRIM_LAT_CUTOFF_WIDTH)
  curvy_turn_in_trim_weight = curvy_turn_in_speed_weight * curvy_turn_in_lat_onset * curvy_turn_in_lat_cutoff * turn_in_weight

  curvy_unwind_speed_weight = _gm__flm_full_surface_curvy_speed_weight(surface, profile_key, v_ego)
  curvy_unwind_lat_onset = _gm__sigmoid(surface, (abs_lateral_accel - _gm_IONIQ_6_CURVY_UNWIND_LAT_START) / _gm_IONIQ_6_CURVY_UNWIND_LAT_ONSET_WIDTH)
  curvy_unwind_lat_cutoff = _gm__sigmoid(surface, (_gm_IONIQ_6_CURVY_UNWIND_LAT_END - abs_lateral_accel) / _gm_IONIQ_6_CURVY_UNWIND_LAT_CUTOFF_WIDTH)
  curvy_unwind_weight = curvy_unwind_speed_weight * curvy_unwind_lat_onset * curvy_unwind_lat_cutoff * unwind_weight

  scale = 1.0
  if include_base_ff and surface.supports(profile_key, "ff_gain_left"):
    gain = _gm__flm_full_surface_side_value(surface, profile_key, desired_lateral_accel, "ff_gain")
    onset = _gm__sigmoid(surface, (abs_lateral_accel - _gm_IONIQ_6_FF_ONSET) / _gm_IONIQ_6_FF_ONSET_WIDTH)
    cutoff = _gm__sigmoid(surface, (_gm_IONIQ_6_FF_CUTOFF - abs_lateral_accel) / _gm_IONIQ_6_FF_CUTOFF_WIDTH)
    extra_scale = gain * onset * cutoff
    turn_in_boost = 1.0 + (_gm__flm_full_surface_side_value(surface, profile_key, desired_lateral_accel, "turn_in_boost") * turn_in_weight * low_speed_factor)
    unwind_reduction = _gm__flm_full_surface_side_value(surface, profile_key, desired_lateral_accel,
      "unwind_taper") * unwind_weight * (0.30 + 0.70 * low_speed_factor)
    curvy_unwind_extra = _gm__flm_full_surface_side_value(surface, profile_key, desired_lateral_accel, "curvy_unwind_extra_reduction") * curvy_unwind_weight
    curvy_unwind_floor_relief = _gm__flm_full_surface_side_value(surface, profile_key, desired_lateral_accel, "curvy_unwind_floor_relief") * curvy_unwind_weight
    unwind_floor = 1.0 - (0.55 * unwind_reduction) - curvy_unwind_floor_relief
    unwind_scale = max(1.0 - unwind_reduction - curvy_unwind_extra, unwind_floor, 0.0)
    scale *= 1.0 + (extra_scale * turn_in_boost * unwind_scale)
  else:
    curvy_unwind_extra = _gm__flm_full_surface_side_value(surface, profile_key, desired_lateral_accel, "curvy_unwind_extra_reduction") * curvy_unwind_weight
    curvy_unwind_floor_relief = _gm__flm_full_surface_side_value(surface, profile_key, desired_lateral_accel, "curvy_unwind_floor_relief") * curvy_unwind_weight
    scale *= max(1.0 - curvy_unwind_extra - curvy_unwind_floor_relief, 0.55)

  if surface.supports(profile_key, "curvy_turn_in_trim_left"):
    curvy_trim = _gm__flm_full_surface_side_value(surface, profile_key, desired_lateral_accel, "curvy_turn_in_trim") * curvy_turn_in_trim_weight
    scale *= max(1.0 - curvy_trim, 0.55)

  if surface.supports(profile_key, "crawl_turn_in_ff_boost_left") and desired_lateral_accel * desired_lateral_jerk > 0.0:
    crawl_speed_weight = _gm__sigmoid(surface, (_gm_IONIQ_6_CRAWL_TURN_IN_FF_SPEED - max(v_ego, 0.0)) / _gm_IONIQ_6_CRAWL_TURN_IN_FF_SPEED_WIDTH)
    crawl_lat_weight = _gm__sigmoid(surface, (abs_lateral_accel - _gm_IONIQ_6_CRAWL_TURN_IN_FF_LAT) / _gm_IONIQ_6_CRAWL_TURN_IN_FF_LAT_WIDTH)
    scale += _gm__flm_full_surface_side_value(surface, profile_key, desired_lateral_accel, "crawl_turn_in_ff_boost") * crawl_speed_weight * crawl_lat_weight

  return scale

def _gm_get_flm_full_surface_friction_threshold(surface, profile_key: str | None, base_threshold: float, v_ego: float,
                                            desired_lateral_accel: float = 0.0, desired_lateral_jerk: float = 0.0,
                                            include_base_threshold: bool = False) -> float:
  if not profile_key or not include_base_threshold:
    return base_threshold

  transition_envelope = _gm__flm_full_surface_transition_envelope(surface, v_ego, desired_lateral_accel, desired_lateral_jerk)
  phase = _gm__flm_full_surface_transition_phase(surface, desired_lateral_accel, desired_lateral_jerk)
  turn_in_weight = max(phase, 0.0)
  unwind_weight = max(-phase, 0.0)
  unwind_speed_weight = _gm__sigmoid(surface, (v_ego - _gm_IONIQ_6_UNWIND_HIGH_SPEED_SPEED) / _gm_IONIQ_6_UNWIND_HIGH_SPEED_SPEED_WIDTH)
  threshold_scale = 1.0
  threshold_scale -= (_gm__flm_full_surface_side_value(surface, profile_key, desired_lateral_accel, "turn_in_threshold_reduction") *
                      transition_envelope * turn_in_weight)
  threshold_scale += (_gm__flm_full_surface_side_value(surface, profile_key, desired_lateral_accel, "unwind_threshold_increase") *
                      transition_envelope * unwind_weight * unwind_speed_weight)
  return base_threshold * min(max(threshold_scale, 0.82), 1.18)

def _gm_get_flm_full_surface_low_speed_angle_assist_torque(surface, profile_key: str | None, desired_angle_deg: float, actual_angle_deg: float,
                                                       current_output_torque: float, v_ego: float) -> float:
  if not profile_key or not surface.supports(profile_key, "low_speed_angle_assist_max_torque"):
    return current_output_torque

  max_torque = surface.value(_flm_profile_symbol(profile_key, "low_speed_angle_assist_max_torque"), 0.0)
  if max_torque <= 1e-4:
    return current_output_torque

  angle_error = desired_angle_deg - actual_angle_deg
  if desired_angle_deg * angle_error > 0.0:
    speed_weight = _gm__sigmoid(surface, (_gm_IONIQ_6_LOW_SPEED_ANGLE_ASSIST_SPEED - max(v_ego, 0.0)) / _gm_IONIQ_6_LOW_SPEED_ANGLE_ASSIST_SPEED_WIDTH)
    error_weight = _gm__sigmoid(surface, (abs(angle_error) - _gm_IONIQ_6_LOW_SPEED_ANGLE_ASSIST_ERROR) / _gm_IONIQ_6_LOW_SPEED_ANGLE_ASSIST_ERROR_WIDTH)
    desired_angle_weight = _gm__sigmoid(surface,
      (abs(desired_angle_deg) - _gm_IONIQ_6_LOW_SPEED_ANGLE_ASSIST_DESIRED_ANGLE) / _gm_IONIQ_6_LOW_SPEED_ANGLE_ASSIST_DESIRED_ANGLE_WIDTH)
    tracking_ratio = abs(actual_angle_deg) / max(abs(desired_angle_deg), 1e-3)
    tracking_taper = _gm__sigmoid(surface,
      (tracking_ratio - _gm_IONIQ_6_LOW_SPEED_ANGLE_ASSIST_TRACK_RATIO_START) / _gm_IONIQ_6_LOW_SPEED_ANGLE_ASSIST_TRACK_RATIO_WIDTH)
    tracking_scale = max(1.0 - tracking_taper, _gm_IONIQ_6_LOW_SPEED_ANGLE_ASSIST_TRACK_RATIO_FLOOR)
    assist_torque = math.copysign(max_torque * speed_weight * error_weight * desired_angle_weight * tracking_scale, -angle_error)
    if abs(assist_torque) < 1e-4:
      return current_output_torque
    if current_output_torque * assist_torque >= 0.0:
      add_scale = float(np.interp(abs(current_output_torque), _gm_IONIQ_6_LOW_SPEED_ANGLE_ASSIST_ADD_BP, _gm_IONIQ_6_LOW_SPEED_ANGLE_ASSIST_ADD_V))
      return float(np.clip(current_output_torque + (assist_torque * add_scale), -1.0, 1.0))
    return float(np.clip(current_output_torque + assist_torque, -1.0, 1.0))

  speed_weight = _gm__sigmoid(surface, (_gm_IONIQ_6_LOW_SPEED_UNWIND_ASSIST_SPEED - max(v_ego, 0.0)) / _gm_IONIQ_6_LOW_SPEED_UNWIND_ASSIST_SPEED_WIDTH)
  error_weight = _gm__sigmoid(surface, (abs(angle_error) - _gm_IONIQ_6_LOW_SPEED_UNWIND_ASSIST_ERROR) / _gm_IONIQ_6_LOW_SPEED_UNWIND_ASSIST_ERROR_WIDTH)
  actual_angle_weight = _gm__sigmoid(surface,
    (abs(actual_angle_deg) - _gm_IONIQ_6_LOW_SPEED_UNWIND_ASSIST_ACTUAL_ANGLE) / _gm_IONIQ_6_LOW_SPEED_UNWIND_ASSIST_ACTUAL_ANGLE_WIDTH)
  assist_torque = math.copysign(_gm_IONIQ_6_LOW_SPEED_UNWIND_ASSIST_MAX_TORQUE * speed_weight * error_weight * actual_angle_weight, -angle_error)
  if abs(assist_torque) < 1e-4:
    return current_output_torque
  if current_output_torque * assist_torque >= 0.0:
    assist_torque *= _gm_IONIQ_6_LOW_SPEED_UNWIND_ASSIST_BLEND
  return float(np.clip(current_output_torque + assist_torque, -1.0, 1.0))

_GM_BOUNDS = {'ff_gain_left': (0.0, 0.6),
 'ff_gain_right': (0.0, 0.6),
 'turn_in_boost_left': (-0.1, 2.8),
 'turn_in_boost_right': (-0.1, 2.8),
 'unwind_taper_left': (0.0, 12.0),
 'unwind_taper_right': (0.0, 12.0),
 'center_taper_max': (0.0, 0.18),
 'highway_center_taper_max': (0.0, 0.18),
 'center_deadband_crawl_deg': (0.0, 0.3),
 'center_deadband_low_deg': (0.0, 0.3),
 'center_deadband_mid_deg': (0.0, 0.2),
 'center_deadband_fast_deg': (0.0, 0.12),
 'center_deadband_highway_deg': (0.0, 0.08),
 'turn_in_threshold_reduction_left': (0.0, 2.0),
 'turn_in_threshold_reduction_right': (0.0, 2.0),
 'unwind_threshold_increase_left': (0.0, 12.0),
 'unwind_threshold_increase_right': (0.0, 12.0),
 'crawl_turn_in_ff_boost_left': (0.0, 0.5),
 'crawl_turn_in_ff_boost_right': (0.0, 0.5),
 'low_speed_angle_assist_max_torque': (0.0, 0.8),
 'curvy_speed_min': (4.0, 12.0),
 'curvy_speed_max': (14.0, 25.0),
 'curvy_turn_in_trim_speed_min': (8.0, 16.0),
 'curvy_turn_in_trim_speed_max': (14.0, 25.0),
 'curvy_turn_in_trim_left': (0.0, 0.2),
 'curvy_turn_in_trim_right': (0.0, 0.2),
 'curvy_unwind_floor_relief_left': (0.0, 0.45),
 'curvy_unwind_floor_relief_right': (0.0, 0.45),
 'curvy_unwind_extra_reduction_left': (0.0, 0.45),
 'curvy_unwind_extra_reduction_right': (0.0, 0.45)}
_GM_RICH_BOUNDS = {'ff_gain_left': (0.0, 0.4),
 'ff_gain_right': (0.0, 0.4),
 'turn_in_boost_left': (-0.1, 0.5),
 'turn_in_boost_right': (-0.1, 0.5),
 'unwind_taper_left': (0.0, 0.8),
 'unwind_taper_right': (0.0, 0.8),
 'center_taper_max': (0.0, 0.25),
 'turn_in_threshold_reduction_left': (0.0, 0.4),
 'turn_in_threshold_reduction_right': (0.0, 0.4),
 'unwind_threshold_increase_left': (0.0, 0.6),
 'unwind_threshold_increase_right': (0.0, 0.6)}
_GM_NEUTRAL = {'ff_gain_left': 0.0, 'ff_gain_right': 0.0, 'turn_in_boost_left': 0.0, 'turn_in_boost_right': 0.0, 'unwind_taper_left': 0.0,
  'unwind_taper_right': 0.0, 'center_taper_max': 0.0, 'highway_center_taper_max': 0.0, 'center_deadband_crawl_deg': 0.0,
    'center_deadband_low_deg': 0.0, 'center_deadband_mid_deg': 0.0, 'center_deadband_fast_deg': 0.0, 'center_deadband_highway_deg': 0.0,
      'turn_in_threshold_reduction_left': 0.0, 'turn_in_threshold_reduction_right': 0.0, 'unwind_threshold_increase_left': 0.0,
        'unwind_threshold_increase_right': 0.0, 'crawl_turn_in_ff_boost_left': 0.0, 'crawl_turn_in_ff_boost_right': 0.0,
          'low_speed_angle_assist_max_torque': 0.0, 'curvy_speed_min': _gm_IONIQ_6_CURVY_SPEED_MIN,
            'curvy_speed_max': _gm_IONIQ_6_CURVY_SPEED_MAX, 'curvy_turn_in_trim_speed_min': _gm_IONIQ_6_CURVY_TURN_IN_TRIM_SPEED_MIN,
              'curvy_turn_in_trim_speed_max': _gm_IONIQ_6_CURVY_TURN_IN_TRIM_SPEED_MAX, 'curvy_turn_in_trim_left': 0.0,
                'curvy_turn_in_trim_right': 0.0, 'curvy_unwind_floor_relief_left': 0.0, 'curvy_unwind_floor_relief_right': 0.0,
                  'curvy_unwind_extra_reduction_left': 0.0, 'curvy_unwind_extra_reduction_right': 0.0}
_GM_RICH_DEFAULTS = {'ff_gain_left': _gm_BOLT_2022_2023_FF_GAIN_LEFT, 'ff_gain_right': _gm_BOLT_2022_2023_FF_GAIN_RIGHT,
  'turn_in_boost_left': _gm_BOLT_2022_2023_TURN_IN_BOOST_LEFT, 'turn_in_boost_right': _gm_BOLT_2022_2023_TURN_IN_BOOST_RIGHT,
    'unwind_taper_left': _gm_BOLT_2022_2023_UNWIND_TAPER_LEFT, 'unwind_taper_right': _gm_BOLT_2022_2023_UNWIND_TAPER_RIGHT,
      'center_taper_max': _gm_BOLT_2022_2023_CENTER_TAPER_MAX,
        'turn_in_threshold_reduction_left': _gm_BOLT_2022_2023_TURN_IN_THRESHOLD_REDUCTION_LEFT,
          'turn_in_threshold_reduction_right': _gm_BOLT_2022_2023_TURN_IN_THRESHOLD_REDUCTION_RIGHT,
            'unwind_threshold_increase_left': _gm_BOLT_2022_2023_UNWIND_THRESHOLD_INCREASE_LEFT,
              'unwind_threshold_increase_right': _gm_BOLT_2022_2023_UNWIND_THRESHOLD_INCREASE_RIGHT}

# Appended GM live surface API; existing Ioniq functions and symbols stay exact.
def _gm_finite(value):
  try:
    return type(value) in (int, float) and math.isfinite(value)
  except OverflowError:
    return False


@dataclass(frozen=True, init=False)
class GmSurface:
  profile: str
  knobs: Mapping[str, float]
  base_values: tuple[float, ...] | None

  def __init__(self, profile, knobs, base_values=None):
    if profile not in ('torque_universal', 'gm_bolt_2022_2023') or type(knobs) is not dict:
      raise ValueError('Unsupported GM surface')
    defaults = dict(_GM_NEUTRAL)
    limits = dict(_GM_BOUNDS)
    if profile == 'gm_bolt_2022_2023':
      defaults.update(_GM_RICH_DEFAULTS)
      limits.update(_GM_RICH_BOUNDS)
    else:
      limits.update({'ff_gain_left': (-.40, .60), 'ff_gain_right': (-.40, .60)})
    for name, value in knobs.items():
      if name not in limits or type(value) not in (float, int):
        raise ValueError('Unknown or nonnumeric GM surface knob')
      low, high = limits[name]
      if not _gm_finite(value) or not low <= value <= high:
        raise ValueError('Out-of-range GM surface knob')
      defaults[name] = float(value)
    for low, high in (('curvy_speed_min', 'curvy_speed_max'),
                      ('curvy_turn_in_trim_speed_min', 'curvy_turn_in_trim_speed_max')):
      if defaults[low] >= defaults[high]:
        raise ValueError('Inverted GM surface speed window')
    if profile == 'torque_universal':
      for side in ('left', 'right'):
        # Analytic envelope: onset/cutoff/phase/low-speed weights are in[0,1],
        # unwind multipliers cannot enlarge a negative extra term. Historical
        # independent bounds alone allow -0.4*(1+2.8) to reverse FF.
        if 1. + min(defaults['ff_gain_'+side], 0.) * (1. + max(defaults['turn_in_boost_'+side], 0.)) <= 0.:
          raise ValueError('Sign-inverting composed GM feedforward')
    curve = None
    if base_values is not None:
      if type(base_values) not in (tuple, list) or len(base_values) != 5:
        raise ValueError('Malformed GM friction curve')
      # Original suggestion floor is0.05; original parser supplies no upper
      # threshold cap. Require complete positive finite values and validate
      # interpolation/composition at the frame rather than inventing a tune cap.
      if any(type(v) not in (int, float) or not _gm_finite(v) or v < .05 for v in base_values):
        raise ValueError('Invalid GM friction threshold')
      curve = tuple(float(v) for v in base_values)
    object.__setattr__(self, 'profile', profile)
    object.__setattr__(self, 'knobs', MappingProxyType(defaults))
    object.__setattr__(self, 'base_values', curve)

  def value(self, symbol, default):
    prefix, suffix = symbol.rsplit('.', 1)
    return self.knobs[suffix] if prefix == self.profile and suffix in self.knobs else default

  def supports(self, profile, suffix):
    return profile == self.profile and suffix in self.knobs

  def base_threshold(self, speed):
    from openpilot.starpilot.lateral.bolt_shaping import get_gm_base_friction_threshold
    value = (get_gm_base_friction_threshold(speed) if self.base_values is None else
             float(np.interp(speed, _gm_FLM_FRICTION_SPEED_KNOTS, self.base_values)))
    if not _gm_finite(value) or value <= 0.:
      raise ValueError('Unsafe GM friction composition')
    return value

  def deadband(self, speed):
    return _gm_get_flm_full_surface_center_deadband_deg(self, self.profile, speed)

  def stages(self, sample, feedforward, threshold, *, rich=False):
    # Reuse complete immutable input validation; this is a stage computation,
    # never a native permission or final torque request.
    if not isinstance(sample, SurfaceInput) or not math.isfinite(feedforward) or not math.isfinite(threshold) or threshold <= 0.:
      raise ValueError('Invalid GM surface frame')
    universal = self.profile == 'torque_universal'
    if rich:
      if universal:
        raise ValueError('Rich surface does not match selected Bolt path')
      feedforward *= _gm_get_bolt_2022_2023_ff_scale(self, sample.setpoint, sample.jerk, sample.speed)
      threshold = _gm_get_bolt_2022_2023_friction_threshold(self, sample.speed, sample.setpoint, sample.jerk)
    scale = _gm_get_flm_full_surface_ff_scale(self, self.profile, sample.setpoint, sample.jerk, sample.speed, universal)
    center = _gm_get_flm_full_surface_center_taper_scale(self, self.profile, sample.setpoint, sample.speed, universal)
    threshold = _gm_get_flm_full_surface_friction_threshold(self, self.profile, threshold, sample.speed,
                                                          sample.setpoint, sample.jerk, universal)
    if not math.isfinite(scale) or scale <= 0. or not math.isfinite(center) or center <= 0. or not math.isfinite(threshold) or threshold <= 0.:
      raise ValueError('Unsafe composed GM surface')
    output = feedforward * scale * center
    if not math.isfinite(output):
      raise ValueError('Nonfinite GM feedforward')
    return output, threshold

  def angle_assist(self, sample):
    return _gm_get_flm_full_surface_low_speed_angle_assist_torque(self, self.profile, sample.desired_angle_deg,
        sample.actual_angle_deg, sample.output_torque, sample.speed)

  def document(self):
    return {'profile': self.profile, 'knobs': dict(self.knobs),
            'baseValues': None if self.base_values is None else list(self.base_values)}

  @classmethod
  def from_document(cls, value):
    if type(value) is not dict or set(value) != {'profile', 'knobs', 'baseValues'}:
      raise ValueError('Malformed GM surface')
    return cls(value['profile'], value['knobs'], value['baseValues'])
