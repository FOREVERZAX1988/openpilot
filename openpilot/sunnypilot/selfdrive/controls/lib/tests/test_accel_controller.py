#!/usr/bin/env python3
"""Unit tests for the acceleration controller stub."""
from __future__ import annotations

from openpilot.common.params import Params
from openpilot.common.test import OpenpilotTestCase
from openpilot.sunnypilot.selfdrive.controls.lib.accel_controller.accel_controller import AccelController


class TestAccelController(OpenpilotTestCase):
  def test_stub_is_disabled(self) -> None:
    # NOTE: this used to be a bare unittest.TestCase reading the *real* params store, so the
    # result depended on whatever AccelPersonality happened to be on the host (the registered
    # default is 1/normal, so the old assertion `profile == 0` failed everywhere). Use the
    # harness (isolated Params) and make the expected state explicit instead.
    params = Params()
    params.put("AccelPersonality", 0, block=True)
    params.put_bool("AccelPersonalityEnabled", False, block=True)

    controller = AccelController()
    controller.update()
    self.assertFalse(controller.is_enabled())
    self.assertEqual(controller.profile, 0)


if __name__ == "__main__":
  unittest.main()
