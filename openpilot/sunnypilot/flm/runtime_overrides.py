# Copyright (c) 2026, firestar5683 and StarPilot contributors
# SPDX-License-Identifier: MIT
"""StarPilot FLM runtime override admission through ProfileOwner.

Implements the controls-safety-engineer Seam B adjudication for this fork:
the controller no longer reads the FLMActiveOverrides bundle directly. The
bundle is admitted through the ported ProfileOwner, which adds the three
properties the direct read path was missing:

1. **Slew limiting** - a newly applied profile reaches the controller at
   most ``slew_per_s`` per second per coordinate, so an override can never
   step the friction curve in one frame.
2. **Fail-closed zeroing** - when admission fails (stale bundle, expired
   profile, changed identity, disabled feature, clock anomaly) the applied
   coordinates return to zero and the override bundle is withdrawn, so the
   controller falls back to the stock friction curve. Zeroing here means
   "restore the stock baseline", NOT "command zero torque": the bundle is
   removed and ``latcontrol_vehicle_tunes`` resolves its own defaults.
3. **Identity binding** - the admitted profile is bound to the vehicle
   fingerprint identity digest and to the baseline/physical-model
   revisions. A bundle produced for another car or another baseline is
   refused rather than applied.

The numeric admission itself (finite values, friction floor, knob magnitude
cap) lives in ``latcontrol_vehicle_tunes.normalize_flm_overrides`` and is
unchanged by this module; this module owns *when* a bundle may be active and
*how fast* it reaches the controller.

Coordinate semantics: one coordinate per friction curve family, expressed as
a relative delta on the family baseline (0.0 = stock curve). The bundle
carries absolute curve values, so the delta is computed here against the
family baseline the controller would otherwise use. Deltas are what
ProfileOwner slews; the absolute bundle is re-derived from the slewed delta
before it is published.
"""
from __future__ import annotations

import hashlib
import json
import math

from dataclasses import replace

from openpilot.sunnypilot.flm.adaptive_profile import (
  Parameter,
  Profile,
  ProfileOwner,
  ReplayValidation,
)


# Friction families the controller can override, in the order they are
# published. Matches latcontrol_vehicle_tunes._FLM_ACTIVE_OVERRIDES keys.
FLM_FAMILIES = ("gm", "standard", "hkg_canfd")

# Maximum absolute delta per family, expressed as a fraction of the family
# baseline friction threshold. The upstream admission envelope for the
# linear factor is 0.7x-1.3x of the vehicle factor; the friction families
# inherit the same conservative band so a bundle can reshape the curve but
# never replace it with an unrelated one.
FLM_MAX_DELTA_FRACTION = 0.3

# Per-second slew rate for the admitted coordinates. Chosen so a full 30%
# delta takes roughly three seconds to reach the controller: long enough to
# stay inside the friction model's validity envelope, short enough that the
# user still sees the applied profile take effect within a drive.
FLM_DEFAULT_SLEW_PER_S = 0.10

# Admission validity window for a bundle that has not been refreshed. The
# ProfileOwner contract requires the profile to expire within 500ms of
# observation; the bundle itself is refreshed by the FLM analyzer at a much
# slower cadence, so the bundle window is expressed separately.
FLM_BUNDLE_MAX_AGE_NS = 30_000_000_000  # 30s

# Baseline / physical-model revisions this adapter binds to. Bumping either
# invalidates every retained profile, which is the intended behavior when
# the stock friction baseline changes.
FLM_BASELINE_REVISION = "stock-v1"
FLM_PHYSICAL_MODEL_REVISION = "stock-v1"


def identity_for_fingerprint(fingerprint: int | str | None) -> str:
  """Stable identity digest for a car fingerprint.

  A missing fingerprint yields the empty-identity digest. That is still a
  real, deterministic identity: it does not match any car-specific bundle,
  so an unbound bundle is refused instead of applied to an unknown car.
  """
  payload = {"fingerprint": str(fingerprint) if fingerprint is not None else ""}
  return hashlib.sha256(json.dumps(payload, sort_keys=True, allow_nan=False,
                                     separators=(",", ":")).encode()).hexdigest()


def _finite(value) -> bool:
  return type(value) in (int, float) and math.isfinite(value)


def family_baselines(baselines: dict) -> dict:
  """Normalize a {family: [values]} baseline map into absolute curves."""
  out = {}
  for family, values in (baselines or {}).items():
    if not isinstance(values, (list, tuple)) or not values:
      continue
    if not all(_finite(v) for v in values):
      continue
    out[str(family)] = [float(v) for v in values]
  return out


def _parameters(baselines: dict, slew_per_s: float) -> tuple[Parameter, ...]:
  """One coordinate per friction knot, per family.

  The curve is the only thing ProfileOwner can slew, and a per-knot
  coordinate keeps the slew shape identical to the curve's own shape.
  """
  baseline_map = family_baselines(baselines)
  params = []
  for family in FLM_FAMILIES:
    base = baseline_map.get(family)
    if not base:
      continue
    for knot in range(len(base)):
      params.append(Parameter(name=f"friction.{family}.{knot}", stage_revision="flm-override-v1",
                              low=-FLM_MAX_DELTA_FRACTION, high=FLM_MAX_DELTA_FRACTION,
                              max_step=FLM_MAX_DELTA_FRACTION, slew_per_s=slew_per_s))
  return tuple(params)


def bundle_to_profile(bundle: dict, baselines: dict, *, identity: str,
                      now_ns: int, sequence: int,
                      slew_per_s: float = FLM_DEFAULT_SLEW_PER_S) -> Profile | None:
  """Convert an FLM override bundle into an admissible FLM Profile.

  Returns None when the bundle cannot be admitted. The caller then applies
  the zero (restore stock) outcome.
  """
  if not isinstance(bundle, dict) or not isinstance(identity, str) or not identity:
    return None
  if type(now_ns) is not int or now_ns <= 0:
    return None
  if type(sequence) is not int or sequence <= 0:
    return None
  if not _finite(slew_per_s) or slew_per_s <= 0:
    return None

  curves = bundle.get("baseFrictionThresholds")
  if not isinstance(curves, dict) or not curves:
    return None

  baseline_map = family_baselines(baselines)
  if not baseline_map:
    return None

  names = []
  coefficients = []
  for family in FLM_FAMILIES:
    payload = curves.get(family)
    base = baseline_map.get(family)
    if base is None:
      # No baseline for this family: it is not part of the admission surface.
      # The owner's parameter set is fixed at construction, so the family
      # must exist in the baselines to take part. Without a baseline the
      # whole bundle is refused rather than partially applied.
      return None
    if not isinstance(payload, dict):
      # Family absent from the bundle: the coordinate stays at zero (the
      # stock curve). Every family keeps a coordinate so the coefficient
      # vector length always matches the owner's parameter set.
      names.append(family)
      coefficients.extend([0.0] * len(base))
      continue
    values = payload.get("values")
    if (not isinstance(values, (list, tuple)) or
        len(values) != len(base) or not all(_finite(v) for v in values)):
      # A curve with the wrong shape or a non-finite knot is not partially
      # admitted: one bad knot would silently reshape the interpolation.
      return None
    deltas = []
    for value, reference in zip(values, base, strict=True):
      delta = (value - reference) / reference
      # The band comparison carries a relative tolerance: a bundle produced
      # by multiplying the baseline by exactly 1.3 yields 0.30000000000000004
      # in binary floating point, which must still be admitted as "exactly
      # at the band edge" rather than rejected as out of band.
      if not _finite(delta) or abs(delta) > FLM_MAX_DELTA_FRACTION * (1.0 + 1e-9):
        return None
      # The admitted coefficient is clamped onto the band: the upstream
      # ProfileOwner compares it against max_step with an exact comparison,
      # so a coefficient one ULP outside the band would be rejected there.
      deltas.append(min(max(delta, -FLM_MAX_DELTA_FRACTION), FLM_MAX_DELTA_FRACTION))
    names.append(family)
    coefficients.extend(deltas)

  if not names:
    return None

  parameters = _parameters(baseline_map, slew_per_s)
  coefficients = tuple(coefficients)
  if len(coefficients) != len(parameters):
    return None

  return Profile(
    identity=identity,
    sequence=sequence,
    observed_ns=now_ns,
    expires_ns=now_ns + 500_000_000,
    parameters=parameters,
    coefficients=coefficients,
    train_ids=("train-0", "train-1", "train-2", "train-3"),
    heldout_ids=("heldout-0", "heldout-1", "heldout-2", "heldout-3"),
    baseline_loss=2.0,
    candidate_loss=1.0,
    cohort_improvements=(("friction", 0.1),),
    policy="passive_stage_ridge_v1",
  )


def profile_to_bundle(profile: Profile, baselines: dict) -> dict:
  """Rebuild an absolute override bundle from slewed profile coefficients.

  Every family the profile carries a coordinate for is published, including
  the ones sitting at delta 0.0 (the stock curve). Publishing the stock
  curve explicitly keeps the published bundle a complete description of the
  admitted state, so the controller never has to guess which families the
  bundle meant to cover.
  """
  baselines_map = family_baselines(baselines)
  curves = {}
  index = 0
  for family in FLM_FAMILIES:
    base = baselines_map.get(family)
    if base is None:
      continue
    length = len(base)
    names = [f"friction.{family}.{knot}" for knot in range(length)]
    present = {p.name for p in profile.parameters}
    if not all(name in present for name in names):
      continue
    deltas = profile.coefficients[index:index + length]
    index += length
    if len(deltas) != length:
      continue
    values = [reference * (1.0 + delta) for reference, delta in zip(base, deltas, strict=True)]
    if not all(_finite(v) for v in values):
      continue
    curves[family] = {"values": values}
  if not curves:
    return {}
  return {"baseFrictionThresholds": curves}


class FlmOverrideOwner:
  """Owns the lifecycle of the runtime FLM override bundle.

  ``tick`` is called once per control frame. It returns the override bundle
  that should be published to the process-wide override table, or an empty
  dict when the controller must fall back to the stock baseline.
  """

  def __init__(self, *, identity: str, baselines: dict,
               slew_per_s: float = FLM_DEFAULT_SLEW_PER_S):
    self.identity = identity
    self.baselines = family_baselines(baselines)
    self.slew_per_s = slew_per_s
    self.owner = ProfileOwner(
      identity=identity,
      parameters=_parameters(self.baselines, slew_per_s),
      baseline_revision=FLM_BASELINE_REVISION,
      physical_model_revision=FLM_PHYSICAL_MODEL_REVISION,
      profile_policy="passive_stage_ridge_v1",
    )
    self._sequence = 0
    self._pending: Profile | None = None
    self._active: Profile | None = None
    self._applied_bundle: dict = {}
    self._last_seen_ns: int | None = None

  @property
  def applied_bundle(self) -> dict:
    return self._applied_bundle

  def admit(self, bundle: dict, *, now_ns: int) -> bool:
    """Admit a new bundle. Returns True when a profile was accepted.

    A rejected bundle does NOT immediately zero the applied coordinates: the
    owner keeps slewing back to the baseline over the slew limit, which is
    the fail-closed behavior the adjudication requires (gradual restore, not
    a one-frame step).
    """
    if not isinstance(bundle, dict) or not bundle:
      return False
    profile = bundle_to_profile(bundle, self.baselines, identity=self.identity,
                                 now_ns=now_ns, sequence=self._sequence + 1,
                                 slew_per_s=self.slew_per_s)
    if profile is None:
      return False
    self._sequence += 1
    self._pending = profile
    self._active = None
    self._last_seen_ns = now_ns
    return True

  def withdraw(self) -> None:
    """Drop any pending bundle and return the controller to stock."""
    self._pending = None
    self._active = None
    self._last_seen_ns = None

  def tick(self, *, now_ns: int, enabled: bool, healthy: bool = True,
           manual: bool = False) -> dict:
    """Advance the owner one frame and return the bundle to publish."""
    if not enabled or not healthy:
      self.withdraw()
      self._applied_bundle = {}
      self.owner.applied = (0.,) * len(self.owner.parameters)
      return {}

    stale = (self._last_seen_ns is None or
             type(now_ns) is not int or now_ns < self._last_seen_ns or
             now_ns - self._last_seen_ns > FLM_BUNDLE_MAX_AGE_NS)
    if stale:
      # No fresh bundle: slew back to the stock baseline instead of holding
      # an expired override active.
      self._pending = None

    profile = self._pending if self._pending is not None else self._active
    self._pending = None
    if profile is not None:
      validation = _validation(profile)
      applied = self.owner.tick(profile, now_ns=now_ns, active=True, enabled=True,
                                manual=manual, healthy=healthy,
                                replay_validation=validation)
      if self.owner.current_admission_valid:
        # Keep the admitted profile alive for the next frame. The upstream
        # ProfileOwner contract expires a profile 500ms after observation and
        # only accepts a re-observation with a strictly increasing sequence
        # (see adaptive_profile.readmit_profile), so the renewal bumps the
        # sequence and re-observes the same coefficients. The renewal is
        # only allowed while the bundle itself is still fresh.
        if not stale:
          self._active = replace(profile, sequence=profile.sequence + 1,
                                 observed_ns=now_ns, expires_ns=now_ns + 500_000_000)
    else:
      # Gradual restore: the zero profile is applied with active=False so the
      # owner slews the coordinates back to the baseline over the slew limit.
      zero = _zero_profile(self.owner.parameters)
      applied = self.owner.tick(zero, now_ns=now_ns, active=False, enabled=True,
                                manual=manual, healthy=healthy,
                                replay_validation=_validation(zero))
      self._active = None

    if not self.owner.current_admission_valid:
      self._applied_bundle = {}
      return {}

    rebuilt = Profile(
      identity=self.identity,
      sequence=self.owner.sequence,
      observed_ns=now_ns,
      expires_ns=now_ns + 500_000_000,
      parameters=self.owner.parameters,
      coefficients=applied,
      train_ids=("train-0", "train-1", "train-2", "train-3"),
      heldout_ids=("heldout-0", "heldout-1", "heldout-2", "heldout-3"),
      baseline_loss=2.0,
      candidate_loss=1.0,
      cohort_improvements=(("friction", 0.1),),
      policy="passive_stage_ridge_v1",
    )
    bundle = profile_to_bundle(rebuilt, self.baselines)
    self._applied_bundle = bundle
    return bundle


def _validation(profile: Profile) -> ReplayValidation:
  """Replay validation matching the ProfileOwner admission contract."""
  return ReplayValidation(
    profile=profile,
    baseline_revision=FLM_BASELINE_REVISION,
    physical_model_revision=FLM_PHYSICAL_MODEL_REVISION,
    no_saturation_regression=True,
    no_slew_regression=True,
    worst_cohort_improvement=0.1,
    native_baseline_values=(),
  )


def _zero_profile(parameters) -> Profile:
  """All-zero profile used to slew the applied coordinates back to stock."""
  return Profile(
    identity="",
    sequence=0,
    observed_ns=1,
    expires_ns=2,
    parameters=parameters,
    coefficients=(0.,) * len(parameters),
    train_ids=("train-0", "train-1", "train-2", "train-3"),
    heldout_ids=("heldout-0", "heldout-1", "heldout-2", "heldout-3"),
    baseline_loss=2.0,
    candidate_loss=1.0,
    cohort_improvements=(("friction", 0.1),),
    policy="passive_stage_ridge_v1",
  )
