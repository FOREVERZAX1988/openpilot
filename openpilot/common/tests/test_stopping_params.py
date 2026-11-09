"""stopping_params tests (cp parity, PC-runnable).

PYTHONPATH="/data/openpilot" python -m unittest openpilot.common.tests.test_stopping_params
"""
import unittest

try:
  from openpilot.common.params import Params
except (OSError, ModuleNotFoundError):
  # PC: no native libparams. Use the shared stub so every suite in a combined
  # unittest run sees identical Params behavior regardless of load order.
  from openpilot.common.tests import params_pc_stub
  params_pc_stub.register()
  Params = params_pc_stub.Params

from openpilot.common.stopping_params import (
  STOPPING_SPEED_DEFAULT, STOPPING_SPEED_MIN, get_stopping_speed,
)


class TestStoppingParams(unittest.TestCase):
  def setUp(self):
    self.params = Params()
    self.params.remove("VEgoStopping")

  def test_missing_key_returns_sp_default(self):
    """No key -> the fork's historical 0.25 m/s, and the default materializes."""
    self.assertAlmostEqual(get_stopping_speed(self.params), 0.25)
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
