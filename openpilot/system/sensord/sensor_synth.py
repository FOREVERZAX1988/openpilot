#!/usr/bin/env python3
"""Pure synthesis math for virtual_sensord, kept capnp-free so it is
unit-testable on a PC without msgq/Linux (like locationd/chassis_yaw.py).

All inputs/outputs follow the device/calib frame conventions already reviewed
in the C3XL reports. Nothing here has been run on a device.
"""
import numpy as np

from openpilot.common.transformations.orientation import sensor_to_device_frame

GRAVITY = 9.81
CHASSIS_YAW_INVALID = 100.0   # opendbc hyundai/carstate.py:37
ACCEL_LIMIT = 100.0           # below locationd ACCEL_SANITY_CHECK=100


def s2d_inv(v):
  """sensor_to_device_frame is self-inverse; call the canonical implementation."""
  return sensor_to_device_frame(v)


def build_gyro(yaw_rate: float, camodo_rot, device_from_calib: np.ndarray, chassis_yaw_ok: bool) -> np.ndarray:
  """Return gyroUncalibrated.v (sensor frame).

  Frame chain (reviewed, matches stage-2 chassis_yaw.py:24 and reports):
    vehicle yaw-up  -> calib frame [0, 0, -yaw]   (device z points down)
    -> device frame via device_from_calib
    -> sensor frame via s2d inverse (s2d is self-inverse)

  locationd applies only s2d() to gyro (locationd.py:195); cameraOdometry is
  rotated by device_from_calib first (:246). So we must pre-rotate by D and
  invert s2d to land the independent CAN yaw on the correct device axis.
  Roll/pitch fall back to camodo (rot is already in the calib frame).
  """
  gyro_calib = np.asarray(camodo_rot, dtype=float).copy()
  if chassis_yaw_ok:
    # Only override the yaw axis; keep camodo roll/pitch (D4: zeroing them
    # would feed a tight-variance false-zero to PHONE_GYRO and distort attitude).
    gyro_calib[2] = -yaw_rate
  return s2d_inv(np.asarray(device_from_calib, dtype=float) @ gyro_calib)


def build_accel(v_ego: float, yaw_rate: float, a_ego: float,
                device_from_calib: np.ndarray, chassis_yaw_ok: bool) -> np.ndarray:
  """Return acceleration.v (sensor frame).

  Gravity on sensor x maps to device z (absolute roll/pitch reference).
  a_ego goes on sensor z NEGATED so s2d puts +a_ego on device x, which is what
  ExcessiveActuationCheck reads (selfdrived/helpers.py:29,45).
  a_lat = v_ego*yaw_rate on sensor y (device y = -a_lat).

  TODO(device-verify): accel is built directly in device convention (no D
  multiply) and is exact only for near-zero mount angles. Legacy calibrationd
  clamps rpyCalib to +-0.5 rad (calibrationd.py:54-59), so the target car
  (~0.02 rad) is within validity. A left/right route must confirm a_lat sign.
  """
  a_lat = v_ego * yaw_rate if chassis_yaw_ok else 0.0
  sensor = np.array([GRAVITY, a_lat, -a_ego], dtype=float)
  return np.clip(sensor, -ACCEL_LIMIT, ACCEL_LIMIT)


def can_yaw_ok(cs, CP, hyundai_bit: int, sanity_check: float = 10.0) -> bool:
  """Only trust carState.yawRate where a fingerprint proves it is decoded.

  No getattr(...,0) fallback: a Toyota reports yawRate=0 forever, which would
  silently zero a_lat while tests stay green (fork-port-audit hard rule).
  """
  if CP.brand == 'hyundai' and (int(CP.extFlags) & hyundai_bit):
    yaw = abs(float(cs.yawRate))
    return yaw < sanity_check and yaw != CHASSIS_YAW_INVALID
  return False
