"""assistant_lane / assistant_speed FSM tests (cp parity, PC-runnable).

PYTHONPATH="/data/openpilot" python -m unittest openpilot.selfdrive.controls.lib.tests.test_assistant_lane
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
  _m = types.ModuleType('openpilot.common.params')

  class Params:
    _store: dict[str, str] = {}
    def __init__(self, *args, **kwargs): pass
  _m.Params = Params
  sys.modules['openpilot.common.params'] = _m

from openpilot.selfdrive.controls.lib.desire_lib.assistant_lane import (
  IDENTITY, AssistantLane,
)
from openpilot.sunnypilot.carrot.assistant_speed import AssistantSpeed

VALID_ID = 'a' * 43


def ok_state(speed=36 / 3.6, phase='off', **overrides):
  state = {
    'valid': True, 'lateral_active': True, 'drive': True, 'trailer': False,
    'speed': speed, 'driver_busy': False, 'other_request': False,
    'phase': phase, 'indicator_driver_busy': False,
    'left': {'blindspot': False, 'available': True},
    'right': {'blindspot': False, 'available': True},
  }
  state.update(overrides)
  return state


class AssistantCase(unittest.TestCase):
  def setUp(self):
    self.tmp = tempfile.TemporaryDirectory()
    self.root = Path(self.tmp.name)

  def tearDown(self):
    self.tmp.cleanup()

  def _write(self, name, value):
    target = self.root / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value))


class TestAssistantLane(AssistantCase):
  def _lane(self, clock=lambda: 100.0, **kw):
    lane = AssistantLane(root=self.root, clock=clock, **kw)
    lane.started = 0.0
    return lane

  def test_valid_identity_format(self):
    self.assertRegex(VALID_ID, IDENTITY)

  def test_rejects_when_not_lateral_active(self):
    lane = self._lane()
    self._write('request.json', {'id': VALID_ID, 'direction': 'left', 'time': 99.5})
    self.assertEqual(lane.before(ok_state(lateral_active=False)), (None, False))
    self.assertEqual(lane.result['status'], 'rejected')
    self.assertEqual(lane.result['reason'], 'lateral_control_inactive')

  def test_rejects_below_lane_change_speed(self):
    lane = self._lane()
    self._write('request.json', {'id': VALID_ID, 'direction': 'left', 'time': 99.5})
    self.assertEqual(lane.before(ok_state(speed=20 / 3.6)), (None, False))
    self.assertEqual(lane.result['reason'], 'below_lane_change_speed')

  def test_rejects_blindspot(self):
    lane = self._lane()
    self._write('request.json', {'id': VALID_ID, 'direction': 'right', 'time': 99.5})
    self.assertEqual(lane.before(ok_state(right={'blindspot': True, 'available': True})), (None, False))
    self.assertEqual(lane.result['reason'], 'blindspot')

  def test_expired_stale_request(self):
    lane = self._lane()
    self._write('request.json', {'id': VALID_ID, 'direction': 'left', 'time': 10.0})
    self.assertEqual(lane.before(ok_state()), (None, False))
    self.assertEqual(lane.result['status'], 'expired')

  def test_accepted_request_returns_direction(self):
    lane = self._lane()
    self._write('request.json', {'id': VALID_ID, 'direction': 'left', 'time': 99.5})
    direction, _ = lane.before(ok_state())
    self.assertEqual(direction, 'left')
    self.assertEqual(lane.result['status'], 'waiting')

  def test_cancel_before_begin_is_cancelled(self):
    lane = self._lane()
    self._write('request.json', {'id': VALID_ID, 'direction': 'left', 'time': 99.5})
    lane.before(ok_state())
    self._write('cancel.json', {'id': VALID_ID})
    result, _ = lane.before(ok_state())
    self.assertIsNone(result)
    self.assertEqual(lane.result['status'], 'cancelled')

  def test_completion_requires_crossed_and_finishing(self):
    """completed publishes only after the FSM leaves the lane-change phases
    with began + finishing + crossed all true (cp after() semantics)."""
    lane = self._lane()
    self._write('request.json', {'id': VALID_ID, 'direction': 'left', 'time': 99.5})
    lane.before(ok_state())
    lane.after('laneChangeStarting', 'left', crossed=True)
    self.assertEqual(lane.result['status'], 'running')
    lane.after('laneChangeFinishing', 'left', crossed=True)
    self.assertEqual(lane.result['status'], 'running')
    lane.after('off', 'left')
    self.assertEqual(lane.result['status'], 'completed')

  def test_finish_without_crossing_is_unverified(self):
    lane = self._lane()
    self._write('request.json', {'id': VALID_ID, 'direction': 'left', 'time': 99.5})
    lane.before(ok_state())
    lane.after('laneChangeStarting', 'left', crossed=False)
    lane.after('laneChangeFinishing', 'left', crossed=False)
    lane.after('off', 'left')
    self.assertEqual(lane.result['status'], 'unverified')


class TestAssistantSpeed(AssistantCase):
  def _speed(self, clock=lambda: 100.0):
    svc = AssistantSpeed(root=self.root / 'speed', clock=clock)
    svc.started = 0.0
    return svc

  def test_speed_set_applies(self):
    svc = self._speed()
    self._write('speed/request.json', {'id': VALID_ID, 'action': 'speed_set', 'value': 90, 'time': 99.5})
    command = svc.read(allowed=True, current=100.0, minimum=30, maximum=160)
    self.assertIsNotNone(command)
    self.assertEqual(command['target'], 90)
    svc.finish(90.0)
    self.assertEqual(svc.active, None)
    result = json.loads((self.root / 'speed/result.json').read_text())
    self.assertEqual(result['status'], 'applied')

  def test_speed_out_of_range_rejected(self):
    svc = self._speed()
    self._write('speed/request.json', {'id': VALID_ID, 'action': 'speed_set', 'value': 250, 'time': 99.5})
    self.assertIsNone(svc.read(allowed=True, current=100.0, minimum=30, maximum=160))
    result = json.loads((self.root / 'speed/result.json').read_text())
    self.assertEqual(result['status'], 'rejected')

  def test_driver_override_rejected(self):
    svc = self._speed()
    self._write('speed/request.json', {'id': VALID_ID, 'action': 'speed_up', 'time': 99.5})
    self.assertIsNone(svc.read(allowed=False, current=100.0, minimum=30, maximum=160))
    result = json.loads((self.root / 'speed/result.json').read_text())
    self.assertEqual(result['reason'], 'cruise_inactive_or_driver_override')

  def test_target_overridden_reports_unverified(self):
    svc = self._speed()
    self._write('speed/request.json', {'id': VALID_ID, 'action': 'speed_set', 'value': 90, 'time': 99.5})
    svc.read(allowed=True, current=100.0, minimum=30, maximum=160)
    svc.finish(95.0)  # driver changed it
    result = json.loads((self.root / 'speed/result.json').read_text())
    self.assertEqual(result['status'], 'unverified')


if __name__ == "__main__":
  unittest.main()
