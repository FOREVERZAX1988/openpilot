#!/usr/bin/env python3
"""Static contract tests for virtual_sensord.

These do NOT import virtual_sensord (that pulls in msgq, Windows cannot load it).
They lock the safety-critical contract by inspecting the source text and by
re-deriving the pure math, so they run on a PC without scons/Linux. The runtime
behaviour still requires device-side tests (G1-G7, see reports).
"""
import os
import unittest

import numpy as np

from openpilot.system.sensord.sensor_synth import (
  build_gyro, build_accel, can_yaw_ok, s2d_inv, CHASSIS_YAW_INVALID,
)

SRC = os.path.join(os.path.dirname(__file__), '..', 'virtual_sensord.py')


def source():
  with open(SRC, encoding='utf-8') as f:
    return f.read()


class TestVirtualSensordContract(unittest.TestCase):
  def test_timestamp_uses_logmono_not_wallclock(self):
    s = source()
    self.assertIn('payload.timestamp = msg.logMonoTime', s)
    # Wall-clock time would be off by uptime and fail _validate_sensor_time.
    # Check executable lines only (the docstring mentions time_ns as a warning).
    code_lines = [ln for ln in s.splitlines() if not ln.strip().startswith('#')]
    timestamp_assigns = [ln for ln in code_lines if '.timestamp =' in ln]
    self.assertTrue(timestamp_assigns)
    self.assertTrue(all('logMonoTime' in ln for ln in timestamp_assigns))

  def test_source_is_velodyne_not_impact_whitelist(self):
    s = source()
    self.assertIn('SensorSource.velodyne', s)
    self.assertNotIn('SensorSource.lsm6ds3', s)
    self.assertNotIn('SensorSource.lsm6ds3trc', s)

  def test_both_union_names_present(self):
    s = source()
    self.assertIn("'acceleration'", s)
    self.assertIn("'gyroUncalibrated'", s)  # not 'gyro' @7
    self.assertIn("payload.init(union_name)", s)

  def test_unregistered_param_falls_back_off(self):
    # manager gate must catch UnknownKeyName before so rebuild
    pcfg = os.path.join(os.path.dirname(__file__), '..', '..', 'manager', 'process_config.py')
    with open(pcfg, encoding='utf-8') as f:
      g = f.read()
    self.assertIn('def _virtual_sensord_wanted', g)
    self.assertIn('except Exception:', g)

  def test_mutually_exclusive_gates(self):
    pcfg = os.path.join(os.path.dirname(__file__), '..', '..', 'manager', 'process_config.py')
    with open(pcfg, encoding='utf-8') as f:
      g = f.read()
    self.assertIn('def virtual_sensord(', g)
    self.assertIn('def real_sensord(', g)
    self.assertIn('not imu_present()', g)
    self.assertIn('imu_present() or not _virtual_sensord_wanted', g)


class FakeCS:
  def __init__(self, yaw_rate):
    self.yawRate = yaw_rate


class FakeCP:
  def __init__(self, brand, ext_flags):
    self.brand = brand
    self.extFlags = ext_flags


class TestVirtualSensordMath(unittest.TestCase):
  def test_s2d_is_self_inverse(self):
    v = np.array([1.0, 2.0, 3.0])
    np.testing.assert_array_equal(s2d_inv(s2d_inv(v)), v)

  def test_aego_lands_on_device_x(self):
    # Call the real build_accel, then apply the same s2d that locationd does.
    a_ego, a_lat = 3.0, 0.4
    sensor = build_accel(10.0, a_lat / 10.0, a_ego, np.eye(3), True)
    device = s2d_inv(sensor)
    self.assertAlmostEqual(device[0], a_ego, places=6)      # ExcessiveActuation reads device.x
    self.assertAlmostEqual(device[1], -a_lat, places=6)
    self.assertAlmostEqual(device[2], -9.81, places=6)      # gravity reference preserved

  def test_gyro_z_sign_matches_stage2(self):
    # D3: left turn +0.3 rad/s must land on device z as -0.3 (vehicle yaw-up
    # is -z in the calib frame; stage-2 chassis_yaw.py:24 uses [0,0,-yaw]).
    sensor = build_gyro(0.3, [9.9, 9.9, 9.9], np.eye(3), True)
    device = s2d_inv(sensor)
    self.assertAlmostEqual(device[2], -0.3, places=6)
    self.assertAlmostEqual(device[0], 0.0, places=6)
    self.assertAlmostEqual(device[1], 0.0, places=6)

  def test_gyro_rotated_by_mount_angle(self):
    # With a non-unit device_from_calib the yaw must be rotated, not raw.
    rpy = np.array([0.0, 0.02682, 0.00483])
    from openpilot.common.transformations.orientation import rot_from_euler
    D = rot_from_euler(rpy)
    sensor = build_gyro(0.3, [0.0, 0.0, 0.0], D, True)
    device = s2d_inv(sensor)
    self.assertAlmostEqual(np.linalg.norm(device), 0.3, places=5)  # rotation preserves norm
    self.assertAlmostEqual(device[2], -0.29989, places=4)          # matches stage-2 value

  def test_gyro_falls_back_to_camodo_when_no_can(self):
    camodo = [0.1, 0.2, 0.3]
    sensor = build_gyro(9.9, camodo, np.eye(3), False)  # CAN invalid -> camodo
    device = s2d_inv(sensor)
    np.testing.assert_allclose(device, camodo, atol=1e-6)

  def test_sentinel_yaw_is_rejected(self):
    bit = 2 ** 20
    self.assertFalse(can_yaw_ok(FakeCS(CHASSIS_YAW_INVALID), FakeCP('hyundai', bit), bit))
    self.assertFalse(can_yaw_ok(FakeCS(50.0), FakeCP('hyundai', bit), bit))  # > sanity
    self.assertTrue(can_yaw_ok(FakeCS(0.3), FakeCP('hyundai', bit), bit))
    # Toyota has no decoded yaw -> must be rejected, never getattr(...,0).
    self.assertFalse(can_yaw_ok(FakeCS(0.0), FakeCP('toyota', 0), bit))

  def test_no_getattr_zero_fallback(self):
    s = source()
    self.assertNotIn('getattr(cs', s)


if __name__ == '__main__':
  unittest.main()
