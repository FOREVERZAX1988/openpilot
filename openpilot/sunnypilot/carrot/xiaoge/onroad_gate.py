#!/usr/bin/env python3
"""When may the xiaoge ONNX models run?

Policy (decided 2026-09-29, "plan A"): both xiaoge pipelines are gated by *onroad only*.

  * onroad  -> run.  Onroad includes standstill: red lights, idling, traffic jams, ACC
    stop-and-go.  The car is on and the driver is there, so the auxiliary signals must
    stay fresh -- exactly the case a speed gate would have broken.
  * offroad -> skip the inference entirely (ignition off / parked / in the garage):
    nobody is in the car, so we stop burning CPU on it.

Applies to both threads of ``v_asm_server.py``, but it is a *necessary*, not a sufficient,
condition:

  * the blind-spot (V-ASM) pipeline keeps its own, much stricter gate on top of this one
    (30-120 km/h + lane-change direction + target-lane width >= 3 m), so it only ever
    produced a signal during a lane change anyway;
  * the lane model runs whenever onroad, i.e. also at a standstill.

This only concerns our auxiliary signals -- ``carStateSP.xiaogeLeftLaneLine`` /
``xiaogeRightLaneLine`` and the xiaoge blind-spot hints in ``carState.left/rightBlindspot``.
The car's own lane keeping, localisation and factory blind-spot detection do not come from
these pipelines and are untouched.

``deviceState.started`` is the same onroad flag the manager uses to decide which processes
run (``system/manager/manager.py``: ``started = sm['deviceState'].started`` and
``IsOffroad = not started``), so "onroad" here means exactly what the rest of openpilot
means by it.
"""

# Reasons are surfaced verbatim in the v_asm_server /status payload, so keep them short,
# stable strings: the on-device debug page and the carrot tests read them.
REASON_ONROAD = ""
REASON_OFFROAD = "offroad (deviceState.started=False): xiaoge inference paused"
REASON_UNKNOWN = "deviceState unavailable: xiaoge inference not gated"


def xiaoge_inference_allowed(*, device_state_available: bool, started: bool) -> tuple[bool, str]:
  """Return ``(allowed, reason)`` for the onroad-only gate.

  ``device_state_available`` must come from SubMaster liveness/validity checks, not from a
  first-message read: a stale deviceState is not a trustworthy "offroad".

  Fail **open** when we cannot tell: silently disabling a driving feature is worse than
  spending a little CPU when parked, and that silent disable is a failure mode this fork
  has already hit once (an AttributeError that killed the wide-road camera thread without
  saying so).  The caller still reports the reason in /status, so an ungated run is visible
  instead of hidden.
  """
  if not device_state_available:
    return True, REASON_UNKNOWN
  if started:
    return True, REASON_ONROAD
  return False, REASON_OFFROAD
