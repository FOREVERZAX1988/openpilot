#!/usr/bin/env python3
"""What an invalid cameraOdometry message costs.

modeld marks cameraOdometry invalid when a VIPC frame was dropped
(fill_pose_msg: valid = calibration_seen & dropped_frames < 1). On a loaded
device that shows up as an isolated single frame with the stream otherwise
continuous -- a transport hiccup, the same class as a late sensor frame, and it
must not reach the camodo budget. Route 00000014 seg 95 is the reference: two
isolated drops 6.4 s apart (frameId 114404 and 114532, 60 km/h straight) pushed
the counter to 1.83 >= 1.5 and latched inputsOK=false for exactly the 7 s that
selfdrived needed to raise locationdTemporaryError. A run of consecutive
invalid frames -- modeld actually starving -- must still latch at once.
"""
from collections import defaultdict
import unittest

from openpilot.common.test import OpenpilotTestCase
from openpilot.selfdrive.locationd.locationd import (
  CAM_ODO_DROP_RUN_GRACE, INPUT_INVALID_LIMIT, calculate_invalid_input_decay, update_camodo_drop)

LIMIT = round(INPUT_INVALID_LIMIT * 20. / 20.)   # cameraOdometry
THRESHOLD = LIMIT - 0.5
DECAY = calculate_invalid_input_decay(LIMIT, 10.0, 20.0)


def drive(sequence):
  """Feed 'ok'/'bad' frames through the counter; return (bucket, index it crossed threshold)."""
  bucket, run, latched = defaultdict(float), 0, None
  for i, s in enumerate(sequence):
    if s == "bad":
      run = update_camodo_drop(run, bucket, defaultdict(float, cameraOdometry=LIMIT))
    else:
      run = 0
      bucket["cameraOdometry"] *= DECAY
    if bucket["cameraOdometry"] >= THRESHOLD and latched is None:
      latched = i
  return bucket["cameraOdometry"], latched


class TestCamodoDropGrace(OpenpilotTestCase):
  def test_an_isolated_dropped_frame_is_free(self):
    res = ["ok"] * 100 + ["bad"] + ["ok"] * 400
    bucket, latched = drive(res)
    self.assertIsNone(latched, "a single VIPC drop must not move the counter")

  def test_two_isolated_drops_six_seconds_apart_never_latch(self):
    # the exact seg-95 pattern: drop, 6.4 s of healthy frames at 20 Hz, drop
    res = ["ok"] * 100 + ["bad"] + ["ok"] * 128 + ["bad"] + ["ok"] * 400
    _, latched = drive(res)
    self.assertIsNone(latched, f"residual {DECAY ** 128:.3f} + one drop must stay under {THRESHOLD}")

  def test_alternating_drops_never_accumulate(self):
    res = ["ok", "bad"] * 400
    _, latched = drive(res)
    self.assertIsNone(latched, "runs broken by a healthy frame must not build up")

  def test_a_consecutive_drop_run_latches_at_once(self):
    res = ["ok"] * 100 + ["bad"] * 2 + ["ok"] * 400
    _, latched = drive(res)
    self.assertIsNotNone(latched, "modeld actually starving is a fault, not a hiccup")
    self.assertLess(latched, 102, "must latch within the run, not after recovery")

  def test_a_sustained_outage_still_latches(self):
    res = ["ok"] * 100 + ["bad"] * 400
    _, latched = drive(res)
    self.assertIsNotNone(latched)

  def test_the_counter_is_capped_and_recovers(self):
    res = ["ok"] * 100 + ["bad"] * 100 + ["ok"] * 2000
    bucket, latched = drive(res)
    self.assertIsNotNone(latched)
    self.assertLess(bucket, THRESHOLD, "the counter must fall once healthy frames return")
    self.assertLessEqual(bucket, LIMIT, "the cap must hold")

  def test_grace_is_two(self):
    # contract: one free frame, the second consecutive one pays
    self.assertEqual(CAM_ODO_DROP_RUN_GRACE, 2)


if __name__ == "__main__":
  unittest.main()
