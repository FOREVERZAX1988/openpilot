"""Stored and runtime lower bound for the planner's stop-speed threshold.

Ported from CarrotPilot (common/stopping_params.py). cp's default is 50
(0.5 m/s); this fork keeps its historical STOPPING_SPEED of 0.25 m/s as the
default so enabling the knob does not change behavior until the user tunes it.
The minimum and the repair-on-read semantics are cp verbatim.
"""
import math


STOPPING_SPEED_MIN = 10  # hundredths of m/s
STOPPING_SPEED_DEFAULT = 25  # hundredths of m/s; sp's historical 0.25 m/s


def get_stopping_speed(params, *, blocking=False):
  try:
    stored = params.get_float("VEgoStopping")
  except (TypeError, ValueError, OverflowError):
    stored = float("nan")
  value = max(STOPPING_SPEED_MIN, stored) if math.isfinite(stored) else STOPPING_SPEED_DEFAULT
  if value != stored:
    # Startup repairs persistent values before settings are shown. During driving,
    # enforce the bound immediately and repair external writes without blocking.
    write = params.put_int if blocking else params.put_int_nonblocking
    write("VEgoStopping", int(value))
  return value * 0.01
