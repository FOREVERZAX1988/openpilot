"""
Copyright (c) 2026-, sunnypilot and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
"""Session-local learning runtime for the carrot curve-speed baseline.

Adapted from StarPilot ``starpilot/curve_speed/runtime.py`` + ``preferences.py`` to this fork's
layering: the carrot ``curve_speed`` envelope stays the baseline and the learned comfort curve
is applied only as a *per-point lateral-acceleration budget* through ``comfort_fn()``. When the
master switch is off, the saved document is invalid, or no sample has been collected yet,
``comfort_fn()`` returns ``None`` and the caller runs the baseline byte-for-byte unchanged
(baseline invariance).

Numeric anchors are starpilot/curve_speed line numbers ("/e/StarPilot/openpilot/starpilot/"):
runtime.py:11 TRAINING_QUIET_NS 5 s, :12 TRAINING_SETTLE_NS 2 s, :13 LEAD_CLEAR_NS 1 s,
:16 PERSIST_INTERVAL_NS 30 s, :17 CRUISING_SPEED 5 m/s, :20 IN_CURVE_ACCEL 1.3, :21 NUDGE 0.15,
runtime.py:347-352 trainable gate, :354-359 observe, :336-339 brake nudge; target.py:19
MAX_STEP_SECONDS 0.2; learning.py:160-163 nudge clamp [1.2, 3.2] weight 20.
"""
from openpilot.common.params import Params
from openpilot.selfdrive.controls.lib.curve_speed_persistence import LearningPersistence

from openpilot.sunnypilot.carrot.curve_speed_learning.learning import LearnedCurve, finite_number

DOCUMENT_KEY = 'CurveComfortData'       # starpilot/curve_speed/preferences.py:17
MASTER_KEY = 'CurveSpeedLearning'       # this fork's master switch (default off -> baseline)
FEEDBACK_KEY = 'CurveSpeedFeedback'     # driver nudge channel; consumed and cleared by refresh_params()
FEEDBACK_VALUES = ('up', 'down')

TRAINING_QUIET_S = 5.0      # runtime.py:11 TRAINING_QUIET_NS
TRAINING_SETTLE_S = 2.0     # runtime.py:12 TRAINING_SETTLE_NS
LEAD_CLEAR_S = 1.0          # runtime.py:13 LEAD_CLEAR_NS
PERSIST_INTERVAL_S = 30.0   # runtime.py:16 PERSIST_INTERVAL_NS
CRUISING_SPEED = 5.0        # runtime.py:17 CRUISING_SPEED
IN_CURVE_ACCEL = 1.3        # runtime.py:20 IN_CURVE_ACCEL
NUDGE = 0.15                # runtime.py:21 NUDGE
MAX_STEP_S = 0.2            # target.py:19 MAX_STEP_SECONDS
PARAMS_REFRESH_S = 1.0      # matches ConditionalExperimentalMode.PARAMS_READ_PERIOD cadence


class CurveSpeedLearningRuntime:
  """Owns permission to learn and persist; the learned curve never reaches a planner directly."""

  def __init__(self, params: Params | None = None):
    self.params = params or Params()
    # A params backend without get_param_path (PC stubs, exotic hosts) cannot own the
    # learning document: degrade to a sample-less, unpersisted runtime, which keeps
    # comfort_fn() None and the caller on the baseline.
    try:
      self.persistence = LearningPersistence(self.params, key=DOCUMENT_KEY)
      loaded = LearnedCurve.load(self._wrap_v1(self.persistence.load_data()))
      self.document_valid = loaded.valid
      self.document_reason = loaded.reason
    except (AttributeError, OSError, ValueError):
      self.persistence = None
      loaded = LearnedCurve.load(None)
      self.document_valid = False
      self.document_reason = 'unavailable_params'
    self.curve: LearnedCurve = loaded.curve
    self.enabled = False
    self._last_refresh = None
    self._last_now = None
    self._training_timer = 0.0
    self._quiet_until = 0.0
    self._last_lead_seen = None
    self._last_persist = None
    self._pending = None  # (persistence revision, LearnedCurve revision) in flight
    self._has_samples = bool(self.curve.document()['buckets'])
    self._was_brake = False
    self._last_scene = (0.0, 0.0, False)  # (|curvature|, v_ego, in_curve) for the feedback channel

  @staticmethod
  def _wrap_v1(buckets) -> dict | None:
    """LearningPersistence yields the raw bucket dict of a v1/legacy document; rewrap for LearnedCurve.load()."""
    if not isinstance(buckets, dict) or not buckets:
      return None
    return {'version': 1, 'buckets': buckets}

  # ---- permission ---------------------------------------------------------

  def refresh_params(self, now: float) -> None:
    """1 s cadence caller-side; also drains the driver feedback channel."""
    if self._last_refresh is not None and 0.0 <= now - self._last_refresh < PARAMS_REFRESH_S:
      return
    self._last_refresh = now
    self.enabled = self.params.get_bool(MASTER_KEY)
    self._poll_persistence()
    self._poll_feedback()

  def _poll_persistence(self) -> None:
    if self.persistence is None:
      return
    for revision, status in self.persistence.poll():
      if status == 'saved' and self._pending is not None and revision == self._pending[0]:
        try:
          self.curve.acknowledge_saved(self._pending[1])
        except ValueError:
          pass
        self._pending = None

  def _poll_feedback(self) -> None:
    """Driver nudge via Params (no UI wiring in this change; see report).

    'up' raises the learned comfort at the current curvature, 'down' lowers it -
    the starpilot curve_speed/actions.py button semantics reduced to the one
    channel a Params key can carry. Consumed on read: the key is cleared so a
    stale value cannot repeat every refresh.
    """
    try:
      raw = self.params.get(FEEDBACK_KEY)
    except Exception:
      return
    if raw not in FEEDBACK_VALUES:
      return
    self.params.put(FEEDBACK_KEY, '')
    if not self.enabled or not self.document_valid:
      return
    curvature, v_ego, in_curve = self._last_scene
    if not in_curve or not finite_number(curvature) or v_ego <= CRUISING_SPEED:
      return
    base = self.curve.comfort(abs(curvature))
    sample = base + NUDGE if raw == 'up' else base - NUDGE
    try:
      self.curve.nudge(abs(curvature), sample)
      self._has_samples = True
    except ValueError:
      pass

  # ---- correction ---------------------------------------------------------

  def comfort_fn(self):
    """Per-point lateral-acceleration budget for ``curve_speed()``, or None for baseline.

    None when disabled, the document is invalid, or no sample exists yet: an
    unlearned fit is prior-only (1.5..2.9 m/s^2) and would silently retune the
    baseline, so readiness requires at least one observed sample.
    """
    if not self.enabled or not self.document_valid or not self._has_samples:
      return None
    curve = self.curve

    def budget(curvature: float):
      try:
        value = curve.comfort(curvature)
      except ValueError:
        return None
      return value if finite_number(value) and value > 0.0 else None

    return budget

  # ---- sampling -----------------------------------------------------------

  def update(self, sm, cs, now: float) -> None:
    """One planner tick of sampling + persistence. Defensive: bad inputs only pause learning."""
    self.refresh_params(now)
    if not self.enabled:
      self._session_reset()
      return
    dt = 0.0
    if self._last_now is not None:
      dt = now - self._last_now
      if not 0.0 < dt <= MAX_STEP_S:
        self._session_reset()
        dt = 0.0
    self._last_now = now

    try:
      v_ego = float(cs.vEgo)
      blinker = bool(cs.leftBlinker) or bool(cs.rightBlinker)
      gas_pressed = bool(cs.gasPressed)
      brake_pressed = bool(cs.brakePressed)
      long_active = bool(sm['selfdriveState'].active)
      curvature = float(sm['controlsState'].desiredCurvature)
      tracking_lead = bool(sm['radarState'].leadOne.present)
    except (AttributeError, KeyError, TypeError, ValueError):
      self._last_scene = (0.0, 0.0, False)
      return
    if not finite_number(v_ego) or v_ego < 0.0 or not finite_number(curvature):
      self._last_scene = (0.0, 0.0, False)
      return
    curvature = abs(curvature)
    measured_accel = curvature * v_ego * v_ego
    in_curve = measured_accel >= IN_CURVE_ACCEL
    self._last_scene = (curvature, v_ego, in_curve)

    if long_active:
      # Openpilot owning the speed silences sampling for TRAINING_QUIET_S after it ends
      # (starpilot runtime.py:301, 348 via the manual/quiet gates; sp's
      # selfdrive/controls/lib/curve_speed_learning.py:229-230 uses the same shape).
      self._quiet_until = now + TRAINING_QUIET_S
    if tracking_lead:
      self._last_lead_seen = now
    last_lead = self._last_lead_seen if self._last_lead_seen is not None else now

    manual = (not long_active) or gas_pressed or brake_pressed  # runtime.py:347
    trainable = (manual and v_ego > CRUISING_SPEED and not tracking_lead and
                 now - last_lead >= LEAD_CLEAR_S and not blinker and now >= self._quiet_until)  # runtime.py:348-352
    if trainable:
      self._training_timer += dt
      if self._training_timer >= TRAINING_SETTLE_S and in_curve:  # runtime.py:354-359
        try:
          self.curve.observe(curvature, measured_accel)
          self._has_samples = True
        except ValueError:
          pass
    else:
      self._training_timer = 0.0

    if brake_pressed and not self._was_brake and in_curve and trainable:  # runtime.py:336-339
      try:
        self.curve.nudge(curvature, self.curve.comfort(curvature) - NUDGE)
        self._has_samples = True
      except ValueError:
        pass
    self._was_brake = brake_pressed

    self._maybe_persist(now)

  def _maybe_persist(self, now: float) -> None:
    """Throttled async write; at most one in flight, retried on the next cadence when rejected."""
    if self.persistence is None or not self.curve.dirty or self._pending is not None or not self.document_valid:
      return
    if self._last_persist is not None and now - self._last_persist < PERSIST_INTERVAL_S:
      return
    curve_revision = self.curve.revision
    revision = self.persistence.submit(self.curve.document()['buckets'])
    if revision is not None:
      self._pending = (revision, curve_revision)
      self._last_persist = now

  def _session_reset(self) -> None:
    self._last_now = None
    self._training_timer = 0.0
    self._was_brake = False

  def close(self) -> None:
    if self.persistence is not None:
      self.persistence.close()
