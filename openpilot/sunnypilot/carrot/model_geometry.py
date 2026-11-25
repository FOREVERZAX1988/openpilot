"""
Copyright (c) 2026-, sunnypilot and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
"""Validated shared model geometry (StarPilot starpilot/model_geometry.py port).

Only the helpers lead_tracking.py needs are ported; no control authority or mutable state.
Evidence anchors refer to /e/StarPilot/openpilot/starpilot/model_geometry.py.
"""

import math

ORIGIN_ROUNDOFF_M = 1e-6           # model_geometry.py:5
STANDSTILL_SPEED_NOISE_MPS = 0.01  # model_geometry.py:6
STANDSTILL_RELEASE_SPEED_MPS = 0.05  # model_geometry.py:7
STANDSTILL_MODEL_PREFIX_NOISE_M = 0.01  # model_geometry.py:8


def normalized_origin(distances: tuple) -> tuple:
  """Only remove sub-micrometre model-origin roundoff; callers validate all geometry.
  (model_geometry.py:11-15)"""
  if distances and _finite(distances[0], low=-ORIGIN_ROUNDOFF_M, high=ORIGIN_ROUNDOFF_M) is not None and distances[0] != 0:
    return (0.0, *distances[1:])
  return distances


def _finite(value: object, *, low: float, high: float) -> float | None:
  if isinstance(value, bool) or not isinstance(value, (int, float)):
    return None
  try:
    result = float(value)
  except (OverflowError, ValueError):
    return None
  return result if math.isfinite(result) and low <= result <= high else None


def _launch_prefix_noise(model) -> tuple[float, ...] | None:
  # Only a complete forward launch may use the existing near-zero velocity budget (model_geometry.py:63-85).
  try:
    from openpilot.selfdrive.modeld.constants import ModelConstants

    if model.action.shouldStop is not False or _finite(model.action.desiredAcceleration, low=0.3, high=10.0) is None:
      return None
    times, velocity_times, velocities = tuple(model.position.t), tuple(model.velocity.t), tuple(model.velocity.x)
    if not len(times) == len(velocity_times) == len(velocities) == len(ModelConstants.T_IDXS):
      return None
    if any(
      _finite(t, low=0.0, high=10.0) is None or abs(t - expected) > 1e-5 or _finite(vt, low=0.0, high=10.0) is None or abs(vt - expected) > 1e-5
      for t, vt, expected in zip(times, velocity_times, ModelConstants.T_IDXS, strict=True)
    ):
      return None
    if any(_finite(v, low=-STANDSTILL_RELEASE_SPEED_MPS, high=100.0) is None for v in velocities):
      return None
    tail = tuple(v for v, t in zip(velocities, times, strict=True) if t >= 2.0)
    if not tail or min(tail) < 0.3 or tail[-1] < 5.0 or any(b < a for a, b in zip(tail, tail[1:], strict=False)):
      return None
    return tuple(max(STANDSTILL_MODEL_PREFIX_NOISE_M, STANDSTILL_RELEASE_SPEED_MPS * t) if t < 2.0 else STANDSTILL_MODEL_PREFIX_NOISE_M for t in times)
  except (AttributeError, TypeError, ValueError, OverflowError):
    return None


def standstill_clear_horizon(model) -> float | None:
  """Stop-release endpoint only; this never qualifies full spatial geometry (model_geometry.py:88-112)."""
  try:
    distances = normalized_origin(tuple(model.position.x))
    if len(distances) != 33 or distances[0] != 0.0:
      return None
    noise = _launch_prefix_noise(model) or (STANDSTILL_MODEL_PREFIX_NOISE_M,) * 33
    parsed = tuple(_finite(value, low=-limit, high=500.0) for value, limit in zip(distances, noise, strict=True))
    if any(value is None for value in parsed):
      return None
    finite = tuple(value for value in parsed if value is not None)
    forward_tail = False
    backtrack = 0.0
    for previous, current, limit in zip(finite[:-1], finite[1:], noise[1:], strict=True):
      if current < previous:
        if forward_tail or max(abs(previous), abs(current)) > limit:
          return None
        backtrack += previous - current
        if backtrack > limit:
          return None
      if current > STANDSTILL_MODEL_PREFIX_NOISE_M:
        forward_tail = True
    return finite[-1] if forward_tail else None
  except (AttributeError, TypeError, ValueError, OverflowError):
    return None
