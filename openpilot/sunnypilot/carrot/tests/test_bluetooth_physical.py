"""physical.py hold-lease tests (cp parity, PC-runnable).

PYTHONPATH="/data/openpilot" python -m unittest openpilot.sunnypilot.carrot.tests.test_bluetooth_physical
"""
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path

if 'fcntl' not in sys.modules or not hasattr(sys.modules.get('fcntl'), 'flock'):
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

    def get_int(self, key, *args, **kwargs):
      try:
        return int(self._store.get(key, "0"))
      except (TypeError, ValueError):
        return 0

    def put_int(self, key, value, *args, **kwargs):
      self._store[key] = str(int(value))

  _m = types.ModuleType('openpilot.common.params')
  _m.Params = Params
  sys.modules['openpilot.common.params'] = _m

from openpilot.sunnypilot.carrot.bluetooth.physical import (
  FINGERPRINT, HoldReader, lease_value,
)


def lease(stamp, mode=1, direction='left', override=True, fingerprint=FINGERPRINT):
  return {'stamp': stamp, 'mode': mode, 'direction': direction, 'override': override,
          'fingerprint': fingerprint}


class TestLeaseValue(unittest.TestCase):
  def test_fresh_lease_maps_direction(self):
    self.assertEqual(lease_value(lease(stamp=10.0), 10.1), 2)  # left hold
    self.assertEqual(lease_value(lease(stamp=10.0, direction='right'), 10.1), 3)

  def test_stale_lease_releases_then_expires(self):
    """cp semantics: an override lease past its 0.35 s freshness still yields a
    short release(1) window (1.35 s), then fully expires."""
    self.assertEqual(lease_value(lease(stamp=10.0), 10.5), 1)
    self.assertEqual(lease_value(lease(stamp=10.0), 11.5), 0)

  def test_wrong_fingerprint_still_honors_override_release(self):
    """Fingerprint mismatch falls through to the override-release fallback."""
    self.assertEqual(lease_value(lease(stamp=10.0, fingerprint='OTHER'), 10.1), 1)

  def test_override_release_window(self):
    """The release fallback is bounded: 1.35 s after the stamp it is gone."""
    self.assertEqual(lease_value(lease(stamp=10.0), 11.34), 1)
    self.assertEqual(lease_value(lease(stamp=10.0), 11.36), 0)

  def test_no_override_is_plain_release(self):
    self.assertEqual(lease_value(lease(stamp=10.0, override=False), 10.1), 0)

  def test_garbage_stamp(self):
    self.assertEqual(lease_value({'stamp': 'x'}, 10.0), 0)


class TestHoldReader(unittest.TestCase):
  def setUp(self):
    self.tmp = tempfile.TemporaryDirectory()
    self.path = Path(self.tmp.name) / 'physical-hold.json'
    self.params = Params()

  def tearDown(self):
    self.tmp.cleanup()

  def _reader(self, fingerprint='HYUNDAI_IONIQ_5_PE'):
    return HoldReader(fingerprint, self.params, path=self.path)

  def test_unsupported_fingerprint_never_holds(self):
    reader = self._reader(fingerprint='toyota')
    self.assertEqual(reader.read(True, now=10.0), 0)

  def test_feature_off_preserves_existing_hold(self):
    self.params.put_int('AutoBlinkerControl', 0)
    self.path.write_text(json.dumps(lease(stamp=10.0)))
    reader = self._reader()
    self.assertEqual(reader.read(True, now=10.1), 0)

  def test_feature_on_reads_fresh_lease(self):
    self.params.put_int('AutoBlinkerControl', 1)
    self.path.write_text(json.dumps(lease(stamp=10.0)))
    reader = self._reader()
    self.assertEqual(reader.read(True, now=10.1), 2)

  def test_invalid_can_releases(self):
    self.params.put_int('AutoBlinkerControl', 1)
    reader = self._reader()
    self.assertEqual(reader.read(False, now=10.1), 1)

  def test_missing_lease_file(self):
    self.params.put_int('AutoBlinkerControl', 1)
    reader = self._reader()
    self.assertEqual(reader.read(True, now=10.1), 0)


if __name__ == "__main__":
  unittest.main()
