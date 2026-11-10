"""Direct contract for the default-OFF moving-red preparation transport.

carrot_functions.py wraps SignalPrepareRuntime() in a bare
``try/except Exception: self._prepare_runtime = None`` — any construction or
transport failure is swallowed and the feature silently vanishes. These tests
are the only alarm for that path, so they must cover the constructor and the
observation writer, not just the happy path.
"""
import json
import shutil
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import mock

from openpilot.sunnypilot.carrot.signal_stop_prepare import PrepareDecision, SignalStopPrepare
from openpilot.sunnypilot.carrot.signal_stop_prepare_runtime import (
  ENABLE_PATH,
  SignalPrepareRuntime,
  publish_prepare_observation,
)

RECORD = {'session': 's', 'frame_id': 1, 'timestamp_eof': 1_000_000_000, 'tracks': []}


def _cloudlog_calls(calls):
  fake = types.ModuleType('openpilot.common.swaglog')
  fake.cloudlog = NS(event=lambda *args, **kw: calls.append(kw))
  patcher = mock.patch.dict(sys.modules, {'openpilot.common.swaglog': fake})
  patcher.start()
  return patcher


class TestSignalStopPrepareRuntime(unittest.TestCase):

  def setUp(self):
    tmp = tempfile.mkdtemp(prefix="signal_prepare_rt_test_")
    self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
    self.tmp_path = Path(tmp)

  def patch_mode(self, mode):
    patcher = mock.patch('openpilot.sunnypilot.carrot.signal_mode.signal_mode', lambda: mode)
    patcher.start()
    self.addCleanup(patcher.stop)

  def test_runtime_constructs_cleanly(self):
    """The alarm test: carrot_functions swallows construction errors into None."""
    with mock.patch('openpilot.sunnypilot.carrot.signal_mode.signal_mode', lambda: 0):
      runtime = SignalPrepareRuntime()
    self.assertIsInstance(runtime.prepare, SignalStopPrepare)
    self.assertIs(runtime.enabled, False)  # mode 0 is the shipped default
    self.assertIsNone(runtime.mode)
    self.assertEqual(runtime.mode_since, float('-inf'))
    self.assertIsNone(runtime.extra)
    self.assertIsNone(runtime.last_prepare_log)

  def test_construction_does_not_touch_the_device_flag_files(self):
    """Construction is constant-path only; /data must stay untouched."""
    with mock.patch('openpilot.sunnypilot.carrot.signal_mode.signal_mode', lambda: 0):
      runtime = SignalPrepareRuntime()
    self.assertEqual(runtime.enable_path, ENABLE_PATH)
    self.assertFalse(runtime.enable_path.exists())

  def test_mode_zero_publishes_nothing(self):
    path = self.tmp_path / 'obs.json'
    with mock.patch('openpilot.sunnypilot.carrot.signal_mode.signal_mode', lambda: 0):
      publish_prepare_observation(RECORD, path=path)
    self.assertFalse(path.exists())
    self.assertFalse(path.with_suffix('.tmp').exists())

  def test_active_modes_publish_atomically(self):
    for mode in [1, 2]:
      with self.subTest(mode=mode):
        path = self.tmp_path / 'obs.json'
        with mock.patch('openpilot.sunnypilot.carrot.signal_mode.signal_mode', lambda mode=mode: mode):
          publish_prepare_observation(RECORD, path=path)
        data = json.loads(path.read_text())
        self.assertEqual(data['version'], 1)
        self.assertEqual(data['size'], [1344, 760])
        self.assertEqual(data['frame_id'], 1)
        self.assertEqual(data['session'], 's')
        self.assertEqual(data['timestamp'], 1.0)
        # the tmp hand-off file is gone: readers never observe a partial write
        self.assertFalse(path.with_suffix('.tmp').exists())

  def test_oversized_observation_is_rejected_without_touching_the_last_good_one(self):
    path = self.tmp_path / 'obs.json'
    with mock.patch('openpilot.sunnypilot.carrot.signal_mode.signal_mode', lambda: 2):
      publish_prepare_observation(RECORD, path=path)
      good = path.read_text()

      huge = {**RECORD, 'tracks': [{'id': 'x' * 2000} for _ in range(20)]}
      with self.assertRaisesRegex(ValueError, 'prepare observation too large'):
        publish_prepare_observation(huge, path=path)

    self.assertEqual(path.read_text(), good)
    self.assertFalse(path.with_suffix('.tmp').exists())

  def test_nan_tracks_are_rejected_by_allow_nan_false(self):
    path = self.tmp_path / 'obs.json'
    with mock.patch('openpilot.sunnypilot.carrot.signal_mode.signal_mode', lambda: 2):
      with self.assertRaises(ValueError):
        publish_prepare_observation({**RECORD, 'tracks': [{'distance': float('nan')}]}, path=path)
    self.assertFalse(path.exists())

  def test_observation_is_capped_at_twenty_tracks(self):
    path = self.tmp_path / 'obs.json'
    tracks = [{'id': i} for i in range(40)]
    with mock.patch('openpilot.sunnypilot.carrot.signal_mode.signal_mode', lambda: 1):
      publish_prepare_observation({**RECORD, 'tracks': tracks}, path=path)
    self.assertEqual(len(json.loads(path.read_text())['tracks']), 20)

  def test_record_prepare_is_silent_while_disabled_and_unlogged(self):
    """Disabled + never logged: the early return must not touch swaglog."""
    calls = []
    patcher = _cloudlog_calls(calls)
    patcher.start()
    self.addCleanup(patcher.stop)
    with mock.patch('openpilot.sunnypilot.carrot.signal_mode.signal_mode', lambda: 0):
      SignalPrepareRuntime().record_prepare(PrepareDecision())
    self.assertEqual(calls, [])

  def test_record_prepare_logs_each_distinct_decision_once(self):
    calls = []
    patcher = _cloudlog_calls(calls)
    patcher.start()
    self.addCleanup(patcher.stop)
    with mock.patch('openpilot.sunnypilot.carrot.signal_mode.signal_mode', lambda: 2):
      runtime = SignalPrepareRuntime()
    self.assertIs(runtime.enabled, True)
    runtime.mode = 2  # read() records the active mode; record_prepare trusts it

    decision = PrepareDecision(active=True, reason='housing', track_id=7)
    runtime.record_prepare(decision)
    runtime.record_prepare(decision)  # identical: deduplicated
    self.assertEqual(len(calls), 1)
    self.assertEqual(calls[0]['reason'], 'housing')
    self.assertIs(calls[0]['control_active'], True)  # active and mode == 2

    runtime.record_prepare(PrepareDecision(active=True, reason='housing', track_id=8))
    self.assertEqual(len(calls), 2)

  def test_record_prepare_control_active_requires_control_mode(self):
    calls = []
    patcher = _cloudlog_calls(calls)
    patcher.start()
    self.addCleanup(patcher.stop)
    with mock.patch('openpilot.sunnypilot.carrot.signal_mode.signal_mode', lambda: 1):
      runtime = SignalPrepareRuntime()
    runtime.mode = 1
    runtime.record_prepare(PrepareDecision(active=True, reason='housing'))
    self.assertIs(calls[0]['control_active'], False)  # shadow mode never claims control


if __name__ == "__main__":
  unittest.main()
