#!/usr/bin/env python3
"""Unit tests for the chassis-yaw KF observation helpers.

These are pure-function tests: they do not need a built pose_kf / capnp
generated code, so they run on a PC without scons. They lock the three things
that can silently break: vehicle->device axis mapping, the yaw-only R mask, and
the mount-angle (rpyCalib) rotation.
"""
import unittest

import numpy as np

from openpilot.common.transformations.orientation import rot_from_euler
from openpilot.selfdrive.locationd.chassis_yaw import (
  chassis_yaw_to_device,
  chassis_yaw_R,
  CHASSIS_YAW_OBS_MASK_R,
  CHASSIS_YAW_OBS_STD,
)


class TestChassisYawToDevice(unittest.TestCase):
  def test_identity_mount_maps_yaw_to_negative_device_z(self):
    # Device z points down, vehicle yaw-up is therefore -z in the calib frame.
    got = chassis_yaw_to_device(0.3, np.eye(3))
    np.testing.assert_allclose(got, [0.0, 0.0, -0.3], atol=1e-9)

  def test_zero_yaw_is_zero_vector(self):
    np.testing.assert_allclose(chassis_yaw_to_device(0.0, np.eye(3)), np.zeros(3), atol=1e-9)

  def test_mount_angle_rotates_into_roll_component(self):
    # Legacy Custin rpyCalib (rad): small pitch/yaw. A pure vehicle yaw must
    # pick up a small roll component after device_from_calib rotation.
    rpy = np.array([-8.3e-6, 0.02682, 0.00483])
    D = rot_from_euler(rpy)
    got = chassis_yaw_to_device(0.3, D)
    self.assertAlmostEqual(got[0], -0.00804, places=4)  # roll component appears
    self.assertAlmostEqual(got[2], -0.29989, places=4)  # yaw dominates
    self.assertAlmostEqual(np.linalg.norm(got), 0.3, places=6)  # norm preserved


class TestChassisYawRMask(unittest.TestCase):
  def test_roll_pitch_are_masked_yaw_is_tight(self):
    R = chassis_yaw_R()
    self.assertEqual(R.shape, (3, 3))
    self.assertEqual(R[0, 0], CHASSIS_YAW_OBS_MASK_R)
    self.assertEqual(R[1, 1], CHASSIS_YAW_OBS_MASK_R)
    self.assertAlmostEqual(R[2, 2], CHASSIS_YAW_OBS_STD ** 2)
    # off-diagonals must stay zero (diagonal R avoids inversion pathology)
    self.assertTrue(np.all(R - np.diag(np.diag(R)) == 0))

  def test_kalman_gain_is_yaw_only(self):
    # A 1-DOF-equivalent update: with a large roll/pitch R, the gain on those
    # axes collapses to ~0 while yaw stays finite. This is the L2 proof that
    # the chassis source cannot impose a false-zero roll/pitch constraint.
    P = np.eye(3)
    H = np.eye(3)
    R = chassis_yaw_R()
    K = P @ H.T @ np.linalg.inv(H @ P @ H.T + R)
    self.assertLess(K[0, 0], 1e-5)
    self.assertLess(K[1, 1], 1e-5)
    self.assertGreater(K[2, 2], 1e-4)
    self.assertLess(K[2, 2], 1.0)


if __name__ == "__main__":
  unittest.main()
