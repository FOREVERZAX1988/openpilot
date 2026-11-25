#!/usr/bin/env python3
"""Pure helpers for the chassis-yaw KF observation.

Kept in a capnp-free module so the coordinate transform and covariance mask
are unit-testable on a PC without scons / generated KF code. No process imports
this module at runtime except locationd, which re-exports the helpers.
"""
import numpy as np

# Vehicle yaw-up is -z in the calib frame (device z points down).
# CHASSIS_YAW_OBS_MASK_R ~= 1000 rad/s effective sigma: masks roll/pitch without
# conditioning problems (cond(S) ~ 1e9, safe in float64).
CHASSIS_YAW_OBS_MASK_R = 1e6
CHASSIS_YAW_OBS_STD = 0.05  # rad/s, effective chassis yaw noise (needs L3 tuning)


def chassis_yaw_to_device(yaw_rate: float, device_from_calib: np.ndarray) -> np.ndarray:
  """Chassis yaw rate (vehicle-frame yaw-up, rad/s) -> device-frame ang. velocity.

  Positive vehicle yaw-up is negative z in the calib frame; the resulting
  vector is rotated by device_from_calib into the device frame. Unit-norm is
  preserved so ROTATION_SANITY_CHECK applies unchanged.
  """
  yaw_rate_calib = np.array([0.0, 0.0, -yaw_rate])
  return np.matmul(np.asarray(device_from_calib), yaw_rate_calib)


def chassis_yaw_R() -> np.ndarray:
  """Per-call measurement covariance making the chassis source yaw-only."""
  return np.diag([CHASSIS_YAW_OBS_MASK_R, CHASSIS_YAW_OBS_MASK_R, CHASSIS_YAW_OBS_STD ** 2])
