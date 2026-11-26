#!/usr/bin/env python3
"""The standstill exemption of the gyro<->camodo yaw-rate cross-check.

Route 00000003--37ada6fd6a--0 (C3, staging 07634dda): while the friend's car
sat at vEgo=0.00 with ~60 deg of steering in a parking lot, the IMU honestly
reported body twist (|gyro z| ~ 0.025 rad/s) while the model reported yaw=0
with a tiny std. The cross-check tripped 12 times in 2.2 s, the gyro budget
latched, inputsOK went false and locationdTemporaryError soft-disabled
repeatedly while engaged. Below walking speed the check must be exempt; while
moving it must still catch genuine IMU/vision divergence.
"""
import unittest

from openpilot.common.test import OpenpilotTestCase
from openpilot.selfdrive.locationd.gyro_crosscheck import (
  YAWRATE_CROSSCHECK_MIN_SPEED,
  YAWRATE_CROSS_ERR_CHECK_FACTOR,
  gyro_yawrate_crosscheck_valid)

# Route 00000003 worst trip: gyro z=-0.0254, KF bias=0, camodo mean=0.0094,
# camodo yaw std=0.00101 -> err 0.0348 vs threshold 0.0303 rad/s.
TRIP_GYRO = -0.0254
TRIP_BIAS = 0.0
TRIP_MEAN = 0.0094
TRIP_STD = 0.00101


def _valid(gyro, bias, mean, std, speed):
  return gyro_yawrate_crosscheck_valid(gyro, bias, mean, std, speed)


class TestStandstillExemption(OpenpilotTestCase):
  def test_route_00000003_standstill_steering_trip_is_exempt(self):
    """The exact route condition (vEgo=0, steering 60 deg) no longer trips."""
    assert _valid(TRIP_GYRO, TRIP_BIAS, TRIP_MEAN, TRIP_STD, 0.0)

  def test_a_wild_standstill_reading_is_still_exempt_here(self):
    """Even a large standstill mismatch passes: the magnitude sanity gate
    (ROTATION_SANITY_CHECK, applied by the caller) is what catches garbage."""
    assert _valid(-1.0, 0.0, 0.0, TRIP_STD, 0.0)

  def test_exemption_boundary_is_the_min_speed(self):
    """0.99 m/s exempt, exactly MIN_SPEED (crawling) the check applies."""
    assert _valid(TRIP_GYRO, TRIP_BIAS, TRIP_MEAN, TRIP_STD, YAWRATE_CROSSCHECK_MIN_SPEED - 0.01)
    assert not _valid(TRIP_GYRO, TRIP_BIAS, TRIP_MEAN, TRIP_STD, YAWRATE_CROSSCHECK_MIN_SPEED)


class TestMovingStillChecked(OpenpilotTestCase):
  def test_same_divergence_while_moving_still_trips(self):
    """Low-speed exemption must not weaken the check while actually driving."""
    assert not _valid(TRIP_GYRO, TRIP_BIAS, TRIP_MEAN, TRIP_STD, 2.0)

  def test_agreement_while_moving_passes(self):
    assert _valid(0.0100, 0.0005, 0.0090, TRIP_STD, 2.0)

  def test_tolerance_is_factor_times_std(self):
    """err just under/over factor*std: the tripwire keeps its calibration."""
    std = 0.004
    mean, bias, gyro = 0.05, 0.0, 0.05 + YAWRATE_CROSS_ERR_CHECK_FACTOR * std
    assert not _valid(gyro + 1e-6, bias, mean, std, 10.0)
    assert _valid(gyro - 1e-6, bias, mean, std, 10.0)

  def test_bias_is_subtracted_before_comparison(self):
    std, mean = 0.004, 0.0
    bias = -0.02
    gyro = bias  # sensor reads exactly the bias: zero true yaw
    assert _valid(gyro, bias, mean, std, 10.0)


if __name__ == "__main__":
  unittest.main()
