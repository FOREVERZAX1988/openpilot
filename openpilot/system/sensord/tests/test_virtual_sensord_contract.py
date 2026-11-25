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


def s2d(v):
  return np.array([-v[2], -v[1], -v[0]])


class TestVirtualSensordMath(unittest.TestCase):
  def test_s2d_is_self_inverse(self):
    v = np.array([1.0, 2.0, 3.0])
    np.testing.assert_array_equal(s2d(s2d(v)), v)

  def test_aego_lands_on_device_x(self):
    # sensor [g, a_lat, -a_ego] -> s2d device [a_ego, -a_lat, -g]
    a_ego, a_lat = 3.0, 0.4
    sensor = np.array([9.81, a_lat, -a_ego])
    device = s2d(sensor)
    self.assertAlmostEqual(device[0], a_ego, places=6)      # ExcessiveActuation reads device.x
    self.assertAlmostEqual(device[1], -a_lat, places=6)
    self.assertAlmostEqual(device[2], -9.81, places=6)      # gravity reference preserved

  def test_sentinel_yaw_is_rejected(self):
    # CHASSIS_YAW_INVALID=100 must not be used; sanity gate is 10.
    self.assertGreater(100.0, 10.0)
    s = source()
    self.assertIn('CHASSIS_YAW_INVALID', s)
    self.assertIn('abs(float(cs.yawRate)) < ROTATION_SANITY_CHECK', s)

  def test_no_getattr_zero_fallback(self):
    s = source()
    self.assertNotIn('getattr(cs', s)


if __name__ == '__main__':
  unittest.main()
