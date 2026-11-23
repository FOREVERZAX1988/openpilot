import math
import time
import numpy as np
from collections import deque

from openpilot.cereal import log
from opendbc.car.lateral import FRICTION_THRESHOLD, get_friction
from openpilot.common.constants import ACCELERATION_DUE_TO_GRAVITY
from openpilot.common.filter_simple import FirstOrderFilter
from openpilot.common.params import Params
from openpilot.selfdrive.controls.lib.latcontrol import LatControl
from openpilot.common.pid import PIDController

from openpilot.sunnypilot.common.param_read import read_bool
from openpilot.sunnypilot.selfdrive.controls.lib.latcontrol_torque_ext import LatControlTorqueExt
from openpilot.sunnypilot.selfdrive.controls.lib.vehicle_tune_dispatch import resolve_vehicle_tune
from openpilot.selfdrive.controls.lib.latcontrol_vehicle_tunes import (
  FLM_FRICTION_SPEED_KNOTS,
  RAV4_TSS2_CARS,
  flm_low_speed_angle_assist,
  flm_runtime_overrides_active,
  get_flm_control_effects,
  get_rav4_tss2_pid_output,
  get_standard_friction_threshold,
  set_flm_runtime_overrides,
)
from openpilot.sunnypilot.flm.runtime_overrides import (
  FlmOverrideOwner,
  identity_for_fingerprint,
)

# At higher speeds (25+mph) we can assume:
# Lateral acceleration achieved by a specific car correlates to
# torque applied to the steering rack. It does not correlate to
# wheel slip, or to speed.

# This controller applies torque to achieve desired lateral
# accelerations. To compensate for the low speed effects the
# proportional gain is increased at low speeds by the PID controller.
# Additionally, there is friction in the steering wheel that needs
# to be overcome to move it at all, this is compensated for too.

KP = 0.8
KI = 0.15

INTERP_SPEEDS = [1, 1.5, 2.0, 3.0, 5, 7.5, 10, 15, 30]
KP_INTERP = [250, 120, 65, 30, 11.5, 5.5, 3.5, 2.0, KP]

LP_FILTER_CUTOFF_HZ = 1.2
JERK_LOOKAHEAD_SECONDS = 0.19
JERK_GAIN = 0.3
LAT_ACCEL_REQUEST_BUFFER_SECONDS = 1.0
VERSION = 1

# User Kp scale (StarPilot Advanced Lateral Tuning "SteerKP" equivalent).
# A multiplier over the stock speed-interpolated Kp curve; 1.0 = stock.
# Same params refresh cadence as the torque params override extension.
CUSTOM_KP_REFRESH_FRAMES = 300
CUSTOM_KP_SCALE_LIMITS = (0.5, 2.0)

# FLM (friction learning machine) runtime injection.
#
# The FLM analyzer in flm_workspace.py writes an override bundle into the
# FLMActiveOverrides param; latcontrol_vehicle_tunes.set_flm_runtime_overrides
# publishes it to the process-wide override table. Without this call the
# analyzer's output is computed and then discarded - the learned friction
# curve never reaches the controller.
#
# The refresh cadence is slow because the bundle only changes when the user
# applies a new FLM profile.
FLM_OVERRIDE_REFRESH_FRAMES = 150

# T2: LateralTorque* manual microtuning consumption (carrot reference
# /e/cp/openpilot/selfdrive/controls/lib/latcontrol_torque.py:144-162):
# refresh every 10 frames (cp :144); AccelFactor/Friction scale 0.001
# (cp :147-148); Kp/Ki/Kf/Kd scale 0.01 (cp :149-152).
# LateralTorqueCustom is read WITHOUT return_default so an unset param means
# off (cp params_keys.h:389 default "0"). sp registers it as BOOL "1"
# (params_keys.h:1037), so honoring the registry default would silently flip
# every existing car into manual gains at the next boot.
MANUAL_TORQUE_REFRESH_FRAMES = 10
MANUAL_TORQUE_PARAM_SCALE = 0.001
MANUAL_TORQUE_GAIN_SCALE = 0.01


def _flm_baseline_curves() -> dict:
  """Stock friction curves sampled at the FLM speed knots.

  The FLM override owner works in relative deltas against the stock
  baseline, so the baseline has to be expressed as a curve over the same
  speed knots the override bundle uses. Each family is sampled with its own
  default function, which is what the controller falls back to when no
  override is active.
  """
  from openpilot.selfdrive.controls.lib.latcontrol_vehicle_tunes import (
    _gm_base_friction_threshold_default,
    _hkg_canfd_base_friction_threshold_default,
    _standard_friction_threshold_default,
  )

  curves = {}
  for family, fn in (
    ("gm", _gm_base_friction_threshold_default),
    ("standard", _standard_friction_threshold_default),
    ("hkg_canfd", _hkg_canfd_base_friction_threshold_default),
  ):
    try:
      curves[family] = [float(fn(float(knot))) for knot in FLM_FRICTION_SPEED_KNOTS]
    except Exception:
      continue
  return curves

class LatControlTorque(LatControl):
  def __init__(self, CP, CP_SP, CI, dt):
    super().__init__(CP, CP_SP, CI, dt)
    self.torque_params = CP.lateralTuning.torque.as_builder()
    self.torque_from_lateral_accel = CI.torque_from_lateral_accel()
    self.lateral_accel_from_torque = CI.lateral_accel_from_torque()
    self.params = Params()
    self._custom_kp_scale = self._read_custom_kp_scale()
    self._kp_frame = -1
    self.pid = PIDController([INTERP_SPEEDS, [k * self._custom_kp_scale for k in KP_INTERP]], KI, rate=1/self.dt)
    self.update_limits()
    self.steering_angle_deadzone_deg = self.torque_params.steeringAngleDeadzoneDeg
    self.lat_accel_request_buffer_len = int(LAT_ACCEL_REQUEST_BUFFER_SECONDS / self.dt)
    self.lat_accel_request_buffer = deque([0.] * self.lat_accel_request_buffer_len , maxlen=self.lat_accel_request_buffer_len)
    self.lookahead_frames = int(JERK_LOOKAHEAD_SECONDS / self.dt)
    self.jerk_filter = FirstOrderFilter(0.0, 1 / (2 * np.pi * LP_FILTER_CUTOFF_HZ), self.dt)

    self.extension = LatControlTorqueExt(self, CP, CP_SP, CI)
    self.update_limits()  # the call above ran before the extension existed

    # Per-vehicle tunes (StarPilot port): resolved once per drive cycle from the
    # fingerprint, gated by VehicleTunesEnabled (default off = stock behavior).
    self.vehicle_tune = resolve_vehicle_tune(CP)
    self.vehicle_tunes_enabled = self.params.get_bool("VehicleTunesEnabled")
    self._flm_frame = -1
    self._flm_enabled = read_bool(self.params, "FlmRuntimeOverridesEnabled")
    # The FLM override admission owner. It binds the bundle to this car's
    # fingerprint identity and slews the friction curve toward the learned
    # profile instead of applying it in one frame.
    self._flm_owner = FlmOverrideOwner(
      identity=identity_for_fingerprint(getattr(CP, "carFingerprint", None)),
      baselines=_flm_baseline_curves(),
    )
    self._refresh_flm_overrides()

    # T2: manual LateralTorque* microtuning state. Defaults captured from the
    # stock CP torque params before any live/FLM application, used to restore
    # stock when the user turns the custom switch off (cp :158-161).
    self._manual_frame = -1
    self.lateral_torque_custom = 0
    self._manual_kf = None
    self._manual_applied = None
    self._manual_defaults = (
      self.torque_params.latAccelFactor,
      self.torque_params.latAccelOffset,
      self.torque_params.friction,
    )

    # T4: RAV4_TSS2 (威兰达同源) low-speed center-reversal damping.
    # get_rav4_tss2_pid_output existed in latcontrol_vehicle_tunes.py with zero
    # call sites; wiring it needs one frame of output state for its alpha
    # smoothing, tracked only while the gate below holds.
    self._rav4_tss2_output = getattr(CP, 'carFingerprint', None) in RAV4_TSS2_CARS
    self._rav4_prev_output = 0.0

  def _refresh_flm_overrides(self) -> None:
    """Publish the FLM override bundle to the process-wide override table.

    The bundle lives in the FLMActiveOverrides param as JSON. It is empty
    unless the user applied an FLM profile, in which case it carries a
    friction curve and per-vehicle knobs.

    The bundle is not published directly. It is admitted through the FLM
    ProfileOwner (controls-safety-engineer Seam B adjudication), which adds
    the three properties the direct read path lacked:

    - slew limiting, so the friction curve can never step in one frame
    - fail-closed zeroing, so an invalid or stale bundle restores the stock
      friction curve instead of staying active
    - identity binding, so a bundle produced for another car is refused

    Failures are swallowed on purpose: an unparsable bundle must not take
    down the lateral controller.
    """
    self._flm_frame += 1
    now_ns = time.monotonic_ns()

    if not self._flm_enabled:
      self._flm_owner.withdraw()
      set_flm_runtime_overrides({})
      return

    if self._flm_frame % FLM_OVERRIDE_REFRESH_FRAMES == 0:
      try:
        # NOTE: sp Params.get(key, block, return_default) takes no encoding
        # kwarg; an encoding= call raised TypeError and was silently swallowed
        # here, so the bundle never reached the owner. Read without it.
        raw = self.params.get("FLMActiveOverrides") or ""
      except Exception:
        raw = ""

      overrides = {}
      if raw:
        try:
          import json
          parsed = json.loads(raw)
          if isinstance(parsed, dict):
            overrides = parsed
        except Exception:
          overrides = {}

      # The owner only accepts a curve that is inside the conservative band
      # around the stock baseline; a rejected bundle leaves the owner
      # slewing back to stock instead of applying it.
      self._flm_owner.admit(overrides, now_ns=now_ns)

    bundle = self._flm_owner.tick(now_ns=now_ns, enabled=True)
    set_flm_runtime_overrides(bundle)

  def _read_custom_kp_scale(self) -> float:
    scale = float(self.params.get("CustomKp", return_default=True))
    if not math.isfinite(scale):
      return 1.0
    return float(np.clip(scale, *CUSTOM_KP_SCALE_LIMITS))

  def _apply_custom_kp_scale(self, scale: float) -> None:
    # Rebuilds the proportional lookup; the integrator resets, so this only
    # happens when the user actually moved the value between refreshes.
    self.pid = PIDController([INTERP_SPEEDS, [k * scale for k in KP_INTERP]], KI, rate=1/self.dt)
    self.update_limits()

  def refresh_custom_kp_scale(self) -> None:
    self._kp_frame += 1
    if self._kp_frame % CUSTOM_KP_REFRESH_FRAMES != 0:
      return
    scale = self._read_custom_kp_scale()
    if abs(scale - self._custom_kp_scale) > 1e-6:
      self._custom_kp_scale = scale
      self._apply_custom_kp_scale(scale)
    self.vehicle_tunes_enabled = self.params.get_bool("VehicleTunesEnabled")

  def update_torque_parameters(self, latAccelFactor, latAccelOffset, friction):
    # T2: cp latcontrol_torque.py:134-136 — while LateralTorqueCustom is on,
    # live-tuned params (controlsd/torqued) must not overwrite the user's
    # manual values. The extension call site in update() re-asserts the manual
    # values on the same flag.
    if self.lateral_torque_custom > 0:
      return
    self.torque_params.latAccelFactor = latAccelFactor
    self.torque_params.latAccelOffset = latAccelOffset
    self.torque_params.friction = friction
    self.update_limits()

  def _manual_param(self, key: str) -> float:
    """Registry-defaulted numeric read for the manual LateralTorque* params.

    Unset params fall back to their registered defaults (AccelFactor 2500,
    Friction 100, KpV/Kf 100, KiV 10, Kd 0 — params_keys.h:1038-1042,1109),
    matching cp's defaults when the user enables custom without touching the
    sliders.
    """
    try:
      value = float(self.params.get(key, return_default=True))
    except (TypeError, ValueError):
      value = float("nan")
    return value if math.isfinite(value) else 0.0

  def _refresh_manual_torque_tune(self) -> None:
    """T2: apply the LateralTorque* manual microtuning (cp :144-162 formulas).

    Priority: a published FLM runtime override sits ABOVE the manual tune.
    While flm_runtime_overrides_active() the manual application is skipped
    wholesale (no partial mixing: FLM owns the shaping, manual values are
    parked). When FLM deactivates the manual values resume at the next
    refresh; when the user turns LateralTorqueCustom off, stock params and
    PID tables are restored (cp :158-161).
    """
    self._manual_frame += 1
    if self._manual_frame % MANUAL_TORQUE_REFRESH_FRAMES != 0:
      return
    try:
      custom = int(self.params.get("LateralTorqueCustom") or 0)
    except (TypeError, ValueError):
      custom = 0

    if custom > 0 and flm_runtime_overrides_active():
      # FLM wins: leave both the manual params and the PID gains parked.
      self.lateral_torque_custom = custom
      return

    if custom > 0:
      # cp :147-148 — accel factor and friction in milli-units.
      lat_accel_factor = self._manual_param("LateralTorqueAccelFactor") * MANUAL_TORQUE_PARAM_SCALE
      friction = self._manual_param("LateralTorqueFriction") * MANUAL_TORQUE_PARAM_SCALE
      offset = self._manual_defaults[1]  # cp :157 — stock roll-bias offset while custom is on
      self.torque_params.latAccelFactor = lat_accel_factor
      self.torque_params.friction = friction
      self.torque_params.latAccelOffset = offset
      self._manual_applied = (lat_accel_factor, offset, friction)
      # cp :149-156 — constant PID gains replace the speed-interpolated tables.
      kp = self._manual_param("LateralTorqueKpV") * MANUAL_TORQUE_GAIN_SCALE
      ki = self._manual_param("LateralTorqueKiV") * MANUAL_TORQUE_GAIN_SCALE
      kd = self._manual_param("LateralTorqueKd") * MANUAL_TORQUE_GAIN_SCALE
      self.pid._k_p = [[0], [kp]]
      self.pid._k_i = [[0], [ki]]
      self.pid._k_d = [[0], [kd]]
      # cp :155 sets pid.k_f; the sp PIDController has no separate k_f field,
      # so the Kf knob maps to a feedforward multiplier applied in update().
      self._manual_kf = self._manual_param("LateralTorqueKf") * MANUAL_TORQUE_GAIN_SCALE
      self.update_limits()
    elif self.lateral_torque_custom > 0:
      # Manual -> off: restore stock params and the speed-interpolated PID
      # tables (cp :158-161 restore semantics; the custom-Kp scale the user
      # chose independently is preserved).
      (self.torque_params.latAccelFactor,
       self.torque_params.latAccelOffset,
       self.torque_params.friction) = self._manual_defaults
      self._apply_custom_kp_scale(self._custom_kp_scale)
      self._manual_kf = None
      self._manual_applied = None
      self.update_limits()
    self.lateral_torque_custom = custom

  def update_limits(self):
    self.pid.set_limits(self.lateral_accel_from_torque(self.steer_max, self.torque_params),
                        self.lateral_accel_from_torque(-self.steer_max, self.torque_params))
    if hasattr(self, 'extension'):  # torque-space override controllers re-assert +-steer_max
      self.extension.update_limits()

  def update(self, active, CS, VM, params, steer_limited_by_safety, desired_curvature, calibrated_pose, curvature_limited, lat_delay):
    self.refresh_custom_kp_scale()
    self._refresh_flm_overrides()
    self._refresh_manual_torque_tune()
    # Override torque params from extension. The call always runs — it also
    # owns the steer_max rail-schedule update — but while the T2 manual tune
    # is active its TorqueParamsOverride knobs are re-asserted over by the
    # manual values (manual LateralTorque* wins, same precedence as
    # update_torque_parameters, cp :134-136).
    ext_changed = self.extension.update_override_torque_params(self.torque_params)
    if self.lateral_torque_custom > 0 and self._manual_applied is not None:
      (self.torque_params.latAccelFactor,
       self.torque_params.latAccelOffset,
       self.torque_params.friction) = self._manual_applied
      ext_changed = True
    if ext_changed:
      self.update_limits()

    pid_log = log.ControlsState.LateralTorqueState.new_message()
    pid_log.version = VERSION
    desired_curvature = self.extension.adjust_desired_curvature(desired_curvature, CS, active)
    measured_curvature = -VM.calc_curvature(math.radians(CS.steeringAngleDeg - params.angleOffsetDeg), CS.vEgo, params.roll)
    measurement = measured_curvature * CS.vEgo ** 2
    future_desired_lateral_accel = desired_curvature * CS.vEgo ** 2
    self.lat_accel_request_buffer.append(future_desired_lateral_accel)

    roll_compensation = params.roll * ACCELERATION_DUE_TO_GRAVITY
    # F1: FLM control-surface effects. Gated on active, no driver override, no
    # safety limiting and no extension output override — the same baseline
    # invariance StarPilot enforces (torque_stages.py:64-66: inactive /
    # driver_override / limited frames emit the unchanged baseline). A bundle
    # without controlEffects yields {} here, i.e. exactly the pre-F1 behavior.
    flm_effects = {}
    if (active and not CS.steeringPressed and not steer_limited_by_safety
        and not self.extension.overrides_output and flm_runtime_overrides_active()):
      flm_effects = get_flm_control_effects()
    flm_deadband_deg = float(flm_effects.get("deadbandDeg", 0.0))
    flm_ff_delta = float(flm_effects.get("ffDelta", 0.0))
    flm_assist_max = float(flm_effects.get("angleAssistMaxTorque", 0.0))
    # F1 deadzone: added to the steering angle deadzone the same way StarPilot
    # composes it (latcontrol_torque.py:126: self.steering_angle_deadzone_deg +
    # flm.deadband(surface, CS.vEgo)); envelope [0, 0.01] deg (torque_stages.py:107).
    curvature_deadzone = abs(VM.calc_curvature(math.radians(self.steering_angle_deadzone_deg + flm_deadband_deg), CS.vEgo, 0.0))
    lateral_accel_deadzone = curvature_deadzone * CS.vEgo ** 2

    delay_frames = int(np.clip(lat_delay / self.dt + 1, 1, self.lat_accel_request_buffer_len))
    expected_lateral_accel = self.lat_accel_request_buffer[-delay_frames]
    setpoint = expected_lateral_accel
    error = setpoint - measurement

    lookahead_idx = int(np.clip(-delay_frames + self.lookahead_frames, -self.lat_accel_request_buffer_len+1, -2))
    raw_lateral_jerk = (self.lat_accel_request_buffer[lookahead_idx+1] - self.lat_accel_request_buffer[lookahead_idx-1]) / (2 * self.dt)
    desired_lateral_jerk = self.jerk_filter.update(raw_lateral_jerk)
    gravity_adjusted_future_lateral_accel = future_desired_lateral_accel - roll_compensation
    ff = gravity_adjusted_future_lateral_accel
    # latAccelOffset corrects roll compensation bias from device roll misalignment relative to car roll
    ff -= self.torque_params.latAccelOffset
    if self._manual_kf is not None and self.lateral_torque_custom > 0 and not flm_runtime_overrides_active():
      # T2: cp :155 pid.k_f semantics as a feedforward multiplier (sp's
      # PIDController has no separate k_f field). Inactive while an FLM
      # override is published (FLM sits above the manual tune).
      ff *= self._manual_kf
    if flm_ff_delta != 0.0:
      # F1 FF residual: ff * (1 + delta_ff), StarPilot torque_stages.py:81-82;
      # |delta| <= 0.03 envelope (torque_stages.py:79), slewed by the owner.
      ff *= (1.0 + flm_ff_delta)

    vehicle_tune = self.vehicle_tune if self.vehicle_tunes_enabled else None
    # Base friction threshold: the speed-dependent standard curve. When an FLM
    # profile is active it overrides this per speed knot, so the learned
    # friction profile actually reaches the controller.
    friction_threshold = get_standard_friction_threshold(CS.vEgo) if flm_runtime_overrides_active() else FRICTION_THRESHOLD
    friction_scale = 1.0
    if vehicle_tune is not None:
      if vehicle_tune.ff_scale is not None:
        ff *= vehicle_tune.ff_scale(setpoint, measurement, desired_lateral_jerk, CS.vEgo)
      if vehicle_tune.friction_threshold is not None:
        friction_threshold = vehicle_tune.friction_threshold(setpoint, measurement, desired_lateral_jerk, CS.vEgo)
      if vehicle_tune.friction_scale is not None:
        friction_scale = vehicle_tune.friction_scale(setpoint, measurement, desired_lateral_jerk, CS.vEgo)
    ff += friction_scale * get_friction(error + JERK_GAIN * desired_lateral_jerk, lateral_accel_deadzone, friction_threshold, self.torque_params)

    if not active:
      output_torque = 0.0
      pid_log.active = False
    else:
      # do error correction in lateral acceleration space, convert at end to handle non-linear torque responses correctly
      pid_log.error = float(error)

      freeze_integrator = steer_limited_by_safety or CS.steeringPressed or CS.vEgo < 5
      if self.extension.overrides_output:  # the extension runs its own pid.update on the shared PID
        output_torque = 0.0
      else:
        output_lataccel = self.pid.update(pid_log.error, speed=CS.vEgo, feedforward=ff, freeze_integrator=freeze_integrator)
        output_torque = self.torque_from_lateral_accel(output_lataccel, self.torque_params)

      # Lateral acceleration torque controller extension updates
      # Overrides pid_log.error and output_torque
      pid_log, output_torque = self.extension.update(CS, VM, self.pid, params, ff, pid_log, setpoint, measurement, calibrated_pose, roll_compensation,
                                                     future_desired_lateral_accel, measurement, lateral_accel_deadzone, gravity_adjusted_future_lateral_accel,
                                                     desired_curvature, measured_curvature, steer_limited_by_safety, output_torque)

      if vehicle_tune is not None and vehicle_tune.output_scale is not None:
        output_torque *= vehicle_tune.output_scale(setpoint, measurement, desired_lateral_jerk, CS.vEgo)

      # T4: RAV4_TSS2 damping sits between the vehicle tune and the FLM assist
      # (the assist stays the last shaping step, StarPilot ordering). Same
      # baseline invariance gate family as the F1 effects: skip driver-override
      # / safety-limited / extension-overridden frames so stock behavior is
      # untouched exactly where the assist is untouched.
      if (self._rav4_tss2_output and self.steer_max > 0 and not CS.steeringPressed
              and not steer_limited_by_safety and not self.extension.overrides_output):
        rav4_angle_deg = math.degrees(VM.get_steer_from_curvature(-desired_curvature, CS.vEgo, params.roll))
        output_torque = get_rav4_tss2_pid_output(
          output_torque, self._rav4_prev_output, rav4_angle_deg, CS.vEgo)
      self._rav4_prev_output = output_torque

      if flm_assist_max > 1e-4 and self.steer_max > 0:
        # F1 low-speed angle assist, StarPilot latcontrol_torque.py:183 ordering
        # (last shaping step on the output). Applied in the normalized torque
        # space StarPilot's GM surface assumes; the ported formula clips to
        # [-1.0, 1.0] (torque_surface.py:406-407/:418), which maps back to
        # [-steer_max, steer_max] here — the stock actuator limit is untouched.
        desired_angle_deg = math.degrees(VM.get_steer_from_curvature(-desired_curvature, CS.vEgo, params.roll))
        actual_angle_deg = CS.steeringAngleDeg - params.angleOffsetDeg
        assisted_norm = flm_low_speed_angle_assist(
          flm_assist_max, float(np.clip(output_torque / self.steer_max, -1.0, 1.0)),
          desired_angle_deg, actual_angle_deg, CS.vEgo, setpoint, desired_lateral_jerk,
          bool(CS.steeringPressed))
        output_torque = float(np.clip(assisted_norm, -1.0, 1.0)) * self.steer_max

      pid_log.active = True
      pid_log.p = float(self.pid.p)
      pid_log.i = float(self.pid.i)
      pid_log.d = float(self.pid.d)
      pid_log.f = float(self.pid.f)
      pid_log.output = float(-output_torque) # TODO: log lat accel?
      pid_log.actualLateralAccel = float(measurement)
      pid_log.desiredLateralAccel = float(setpoint)
      pid_log.desiredLateralJerk = float(desired_lateral_jerk)
      pid_log.saturated = bool(self._check_saturation(self.steer_max - abs(output_torque) < 1e-3, CS, steer_limited_by_safety, curvature_limited))

    # TODO left is positive in this convention
    return -output_torque, 0.0, pid_log
