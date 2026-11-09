"""stopping_params tests (cp parity, PC-runnable).

PYTHONPATH="/data/openpilot" python -m unittest openpilot.common.tests.test_stopping_params
"""
import sys
import types
import unittest

if 'fcntl' not in sys.modules:
  # PC stub: the native params backend needs fcntl; the dict store below is enough.
  _fcntl = types.ModuleType('fcntl')
  for _name in ('flock', 'lockf', 'ioctl'):
    setattr(_fcntl, _name, lambda *a, **k: None)
  _fcntl.LOCK_EX, _fcntl.LOCK_SH, _fcntl.LOCK_UN, _fcntl.LOCK_NB = 2, 1, 8, 4
  sys.modules['fcntl'] = _fcntl

try:
  from openpilot.common.params import Params
except (OSError, ModuleNotFoundError):
  class Params:
    _store: dict[str, str] = {}

    def __init__(self, *args, **kwargs):
      pass

    def get_float(self, key, *args, **kwargs):
      value = self._store.get(key)
      try:
        return float(value) if value is not None else float("nan")
      except (TypeError, ValueError):
        return float("nan")

    def put_int(self, key, value, *args, **kwargs):
      self._store[key] = str(int(value))

    put_int_nonblocking = put_int

    def remove(self, key, *args, **kwargs):
      self._store.pop(key, None)

  _m = types.ModuleType('openpilot.common.params')
  _m.Params = Params
  sys.modules['openpilot.common.params'] = _m

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
    self.assertEqual(self.params._store.get("VEgoStopping"), str(STOPPING_SPEED_DEFAULT))

  def test_below_minimum_is_repaired(self):
    self.params._store["VEgoStopping"] = "5"  # 0.05 m/s: below the 0.10 floor
    self.assertAlmostEqual(get_stopping_speed(self.params), STOPPING_SPEED_MIN * 0.01)
    self.assertEqual(self.params._store.get("VEgoStopping"), str(STOPPING_SPEED_MIN))

  def test_valid_value_passes_through(self):
    self.params._store["VEgoStopping"] = "50"
    self.assertAlmostEqual(get_stopping_speed(self.params), 0.5)
    self.assertEqual(self.params._store.get("VEgoStopping"), "50")

  def test_garbage_falls_back_to_default(self):
    self.params._store["VEgoStopping"] = "abc"
    self.assertAlmostEqual(get_stopping_speed(self.params), STOPPING_SPEED_DEFAULT * 0.01)
    self.assertEqual(self.params._store.get("VEgoStopping"), str(STOPPING_SPEED_DEFAULT))


if __name__ == "__main__":
  unittest.main()
