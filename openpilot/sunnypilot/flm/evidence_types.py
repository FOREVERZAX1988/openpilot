# Copyright (c) 2018, Comma.ai, Inc.
# Copyright (c) 2026, firestar5683 and StarPilot contributors
# SPDX-License-Identifier: MIT
"""Verbatim FLMSample evidence record from StarPilot starpilot/flm/gm_evidence.py.

gm_evidence.py's remaining ~1350 lines (live 100 Hz collection, symptom
classification, gm_recommend vehicle knobs) belong to the live collection
wiring batch and are intentionally not ported here. This module carries only
the frozen sample contract consumed by automatic.evaluate_linear_factor, so
the fit/acceptance math stays byte-identical to upstream.
"""
from dataclasses import dataclass


@dataclass(slots=True)
class FLMSample:
  route: str
  segment: int
  t: float
  v_ego: float
  lat_active: bool
  steering_pressed: bool
  saturated: bool
  actual_la: float
  desired_la: float
  desired_jerk: float
  error: float | None
  error_rate: float | None
  p: float | None
  i: float | None
  d: float | None
  f: float | None
  output: float
  steering_angle_deg: float
  steering_torque: float | None
  cmd_torque: float | None
  out_torque: float | None
  roll_deg: float | None
