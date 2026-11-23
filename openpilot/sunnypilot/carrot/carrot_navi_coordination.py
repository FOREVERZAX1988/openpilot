#!/usr/bin/env python3
"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""


# Navigation-driven lane-change coordination (P3, constraint-only v1).
#
# This module implements the "导航与超车统一协调" family of the Tencent-probe
# lane fusion feature set. Design constraints (agreed with the safety review):
#
#   * It may only BLOCK lane changes; it never initiates one. Initiating stays
#     with the driver / existing ATC machinery.
#   * Every effect is gated behind the ``CarrotNavLaneCoordination`` param
#     (default off) and silently inert without a live navigation guidance.
#   * The HD lane-match blocking (probe leftBlocked/rightBlocked) already joins
#     the additive pipeline through carrot_navi_fusion.merge_carrot_navi_lanes;
#     this module adds the guidance-side constraints that the lane-availability
#     data cannot express.
#
# Rules (v1):
#   1. "出口前停止超车、提前收敛" — while an exit / fork / turn maneuver is
#      being guided within EXIT_CONSTRAINT_RANGE_M, lane changes AWAY from the
#      exit side are blocked. Lane changes toward the exit side stay allowed
#      (the driver still needs to get onto the ramp lane).
#   2. "路线变化后自动撤销旧任务" — an absent / changed atcType clears the
#      constraint on the next update; no state is retained across maneuvers.
#
# "超车后有条件回到路线所需车道" and "分阶段跨多条车道" are NOT implemented
# here on purpose: both require initiating lane changes from navigation data,
# which is a control-law change that must go through a dedicated safety review.

# The guidance distance at which away-from-exit lane changes start being
# blocked. Beyond this the maneuver is too far to justify constraining the
# driver's overtaking choices.
EXIT_CONSTRAINT_RANGE_M = 800

# Safety review C3: the constraint must die when the navigation stream stalls.
# The publish heartbeat runs at ~2 Hz; this window covers a full heartbeat
# dropout, after which the coordinator goes inert until fresh data arrives.
NAV_COORD_MAX_AGE_S = 2.0

# atcType is published on carrotManSP by carrot_serv (carrot_serv.py
# update_auto_turn): raw types carry a " prepare" suffix while armed-but-not-
# active, and active turns get an "atc " prefix ("atc left" / "atc right").
_ATC_TYPE_SUFFIX = " prepare"
_ATC_TYPE_PREFIX = "atc "


def normalize_atc_direction(atc_type: str) -> str:
  """Reduce an atcType string to 'left' / 'right' / '' (no lateral intent)."""
  text = str(atc_type or "").strip().lower()
  if not text or text in ("none", "straight"):
    return ""
  if text.endswith(_ATC_TYPE_SUFFIX):
    text = text[: -len(_ATC_TYPE_SUFFIX)]
  if text.startswith(_ATC_TYPE_PREFIX):
    text = text[len(_ATC_TYPE_PREFIX):]
  if "left" in text:
    return "left"
  if "right" in text:
    return "right"
  return ""


import time


class CarrotNaviLaneCoordinator:
  """Pure function object: navigation guidance -> (block_left, block_right).

  ``update`` runs at the modeld DH.update rate (20 Hz, DT_MDL) and must stay
  cheap: it reads at most two capnp attributes plus the cached param state.
  Param refresh is throttled internally to 1 Hz.
  """

  def __init__(self, params=None):
    self._params = params
    self._enabled = False
    self._param_read_t = 0.0
    # Safety review C3: track the navigation stream's publish heartbeat. The
    # publisher emits at ~2 Hz (PUBLISH_HEARTBEAT_SECONDS); if no new publish
    # timestamp is seen for NAV_COORD_MAX_AGE_S the stream is considered dead
    # and the constraint goes inert until fresh data resumes.
    self._last_publish_ns = 0
    self._last_publish_mono = 0.0

  def _read_param(self) -> bool:
    if self._params is None:
      try:
        from openpilot.common.params import Params
        self._params = Params()
      except Exception:
        return False
    try:
      return bool(self._params.get_bool("CarrotNavLaneCoordination"))
    except Exception:
      return False

  def update_params(self) -> None:
    self._enabled = self._read_param()

  def update(self, carrot_navi, atc_type: str, dt: float) -> tuple[bool, bool]:
    """Return (block_left, block_right) for the current guidance state.

    Args:
      carrot_navi: ``carrotNaviSP`` reader (or None) — provides the guidance
        distance used to scope the constraint window.
      atc_type: ``carrotManSP.atcType`` (or "" when carrot_man is absent).
      dt: seconds since the previous update, used to throttle param reads.
    """
    self._param_read_t += dt
    if self._param_read_t >= 1.0:
      self._param_read_t = 0.0
      self.update_params()
    if not self._enabled:
      return False, False

    direction = normalize_atc_direction(atc_type)
    if not direction:
      return False, False

    # C3 freshness gate: a stalled carrotNaviSP publisher must not keep
    # feeding lane-change constraints after its stream died mid-route.
    publish_ns = int(getattr(carrot_navi, "publishMonoTimeNanos", 0) or 0)
    if publish_ns <= 0:
      return False, False
    now_mono = time.monotonic()
    if publish_ns != self._last_publish_ns:
      self._last_publish_ns = publish_ns
      self._last_publish_mono = now_mono
    elif now_mono - self._last_publish_mono > NAV_COORD_MAX_AGE_S:
      return False, False

    distance_m = self._guidance_distance(carrot_navi)
    if distance_m is None or distance_m > EXIT_CONSTRAINT_RANGE_M:
      return False, False

    # Block the side away from the exit; the exit side stays open.
    return direction == "right", direction == "left"

  @staticmethod
  def _guidance_distance(carrot_navi) -> float | None:
    """Closest upcoming guided-maneuver distance, or None when unknown."""
    if carrot_navi is None:
      return None
    distances = []
    for name in ("guidanceNext", "guidanceCurrent"):
      guidance = getattr(carrot_navi, name, None)
      if guidance is None:
        continue
      meta = getattr(guidance, "meta", None)
      if meta is None or not bool(getattr(meta, "present", False)):
        continue
      distance_m = int(getattr(guidance, "distanceM", 0) or 0)
      if distance_m > 0:
        distances.append(distance_m)
    return min(distances) if distances else None
