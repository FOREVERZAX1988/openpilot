#!/usr/bin/env python3

import os
import unittest

from openpilot.common.test import OpenpilotTestCase
from openpilot.common.params import Params
import openpilot.system.manager.manager as manager
from openpilot.system.manager.process_config import managed_processes, procs
from openpilot.common.hardware import COMMA_HARDWARE, HARDWARE

os.environ['FAKEUPLOAD'] = "1"


# Running this suite on a comma device fights the live manager: manager.main() and
# manager_cleanup() (teardown) start/stop the real managed processes, so a device run
# can kill onroad processes mid-drive. The params store itself is already isolated by
# OpenpilotTestCase (OpenpilotPrefix -> /data/params/<prefix>), so clear_all() is safe;
# it is the process management that is not. Keep it to PC/CI.
@unittest.skipIf(COMMA_HARDWARE, "starts/stops the real manager stack: PC/CI only")
class TestManager(OpenpilotTestCase):
  def setup_method(self):
    HARDWARE.set_power_save(False)

    # ensure clean CarParams
    params = Params()
    params.clear_all()

  def teardown_method(self):
    manager.manager_cleanup()

  def test_duplicate_procs(self):
    assert len(procs) == len(managed_processes), "Duplicate process names"

  def test_set_params_with_default_value(self):
    params = Params()
    params.clear_all()

    os.environ['PREPAREONLY'] = '1'
    manager.main()
    for k in params.all_keys():
      default_value = params.get_default_value(k)
      if default_value is not None:
        assert params.get(k) == default_value
    assert params.get("OpenpilotEnabledToggle")
    assert params.get("RouteCount") == 0


if __name__ == "__main__":
  unittest.main()
