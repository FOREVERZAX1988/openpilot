"""stopping_params tests (cp parity, PC-runnable).

PYTHONPATH="/data/openpilot" python -m unittest openpilot.common.tests.test_stopping_params

This suite pins get_stopping_speed()'s pure read/repair logic, so it always uses
the shared in-memory Params stub. Going through the real backend here used to
write /data/params on a live device (and race the running manager over the same
key), which made four tests fail for reasons unrelated to the function. The
fork's *registered* VEgoStopping default is a Macan tuning value in
openpilot/common/params_keys.h (50 = 0.5 m/s); that table is not what this
suite measures, so expectations below use the module constants rather than a
hard-coded 0.25.
"""
import unittest

from openpilot.common.tests.params_pc_stub import Params

from openpilot.common.stopping_params import (
  STOPPING_SPEED_DEFAULT, STOPPING_SPEED_MIN, get_stopping_speed,
)


class TestStoppingParams(unittest.TestCase):
  def setUp(self):
    Params._reset()
    self.params = Params()

  def test_missing_key_returns_sp_default(self):
    """No key -> the module default materializes in the store."""
    self.assertAlmostEqual(get_stopping_speed(self.params), STOPPING_SPEED_DEFAULT * 0.01)
    self.assertEqual(self.params.get_int("VEgoStopping"), STOPPING_SPEED_DEFAULT)

  def test_below_minimum_is_repaired(self):
    self.params.put_int("VEgoStopping", 5)  # 0.05 m/s: below the 0.10 floor
    self.assertAlmostEqual(get_stopping_speed(self.params), STOPPING_SPEED_MIN * 0.01)
    self.assertEqual(self.params.get_int("VEgoStopping"), STOPPING_SPEED_MIN)

  def test_valid_value_passes_through(self):
    self.params.put_int("VEgoStopping", 50)
    self.assertAlmostEqual(get_stopping_speed(self.params), 0.5)

  def test_garbage_falls_back_to_default(self):
    self.params.put("VEgoStopping", "abc")
    self.assertAlmostEqual(get_stopping_speed(self.params), STOPPING_SPEED_DEFAULT * 0.01)
    self.assertEqual(self.params.get_int("VEgoStopping"), STOPPING_SPEED_DEFAULT)


if __name__ == "__main__":
  unittest.main()
