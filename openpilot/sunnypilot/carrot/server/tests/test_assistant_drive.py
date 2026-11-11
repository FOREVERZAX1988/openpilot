import tempfile
import unittest
from pathlib import Path
from unittest import mock

from openpilot.sunnypilot.carrot.bluetooth.model import atomic_json, read_json
from openpilot.sunnypilot.carrot.server.services.assistant_drive import AssistantDrive
from openpilot.sunnypilot.carrot.assistant_speed import AssistantSpeed
from openpilot.selfdrive.controls.lib.desire_lib.assistant_lane import AssistantLane

REJECTED_FIELDS = [('valid', False), ('lateral_active', False), ('drive', False), ('trailer', True), ('speed', 0), ('speed', float('nan')),
                   ('driver_busy', True), ('other_request', True), ('phase', 'laneChangeStarting')]
SPEED_VALUES = [('speed_set', 100, 100), ('speed_down', 10, 70), ('speed_up', None, 81)]
SPEED_RANGES = [(False, 100), (True, 199), (True, 1)]


class TestAssistantDrive(unittest.TestCase):
  def setUp(self):
    self.build()

  def build(self):
    # Each parametrized case in the original suite ran against a fresh fixture; rebuild per case.
    directory = tempfile.TemporaryDirectory()
    self.addCleanup(directory.cleanup)
    root = Path(directory.name)
    self.now = [100.]
    self.service = AssistantDrive(root / 'grants.json', lambda: True, root / 'runtime', lambda: self.now[0])
    self.lane = AssistantLane(self.service.root, lambda: self.now[0])
    self.speed = AssistantSpeed(self.service.root / 'speed', lambda: self.now[0])
    self.token = self.service.enable('http://carrot:7000')
    self.state = {'valid': True, 'lateral_active': True, 'drive': True, 'trailer': False, 'speed': 20., 'phase': 'off',
                  'driver_busy': False, 'driver_override': False, 'other_request': False,
                  'left': {'available': True, 'blindspot': False}, 'right': {'available': True, 'blindspot': False}}

  def send(self, **fields):
    return self.service.execute(self.token, 'http://carrot:7000', {'id': 'x' * 43, 'operation': 'execute', 'action': 'lane_left', **fields})

  def test_only_crossing_and_finished_state_confirm_completion(self):
    for side in ('left', 'right'):
      with self.subTest(side=side):
        self.build()
        now, service, lane, state = self.now, self.service, self.lane, self.state
        self.assertEqual(self.send(action='lane_' + side)['status'], 'waiting')
        self.assertEqual(lane.before(state), (side, False))
        lane.after('preLaneChange', side)
        self.assertEqual(self.send()['status'], 'waiting')
        lane.after('laneChangeStarting', side, crossed=True)
        self.assertEqual(self.send()['status'], 'running')
        lane.after('laneChangeFinishing', side, crossed=True)
        lane.after('off', 'none')
        self.assertEqual(self.send()['status'], 'completed')
        self.assertEqual(lane.before(state), (None, False))
        self.assertEqual(read_json(service.root / 'request.json')['time'], now[0])

  def test_rejected_intent_never_runs_after_condition_recovers(self):
    for field, value in REJECTED_FIELDS:
      with self.subTest(field=field, value=value):
        self.build()
        lane, state = self.lane, self.state
        self.send()
        original = state[field]
        state[field] = value
        self.assertIsNone(lane.before(state)[0])
        self.assertEqual(self.send()['status'], 'rejected')
        state[field] = original
        self.assertEqual(lane.before(state), (None, False))

  def test_obstacle_while_preparing_cancels_only_pending_intent(self):
    for reason in ('blindspot', 'available'):
      with self.subTest(reason=reason):
        self.build()
        lane, state = self.lane, self.state
        self.send()
        self.assertEqual(lane.before(state)[0], 'left')
        state['left'][reason] = reason == 'blindspot'
        self.assertEqual(lane.before(state), (None, True))
        state['left'][reason] = reason != 'blindspot'
        self.assertEqual(lane.before(state), (None, False))

  def test_reset_without_crossing_is_not_success_and_running_is_not_forced_off(self):
    lane, state = self.lane, self.state
    self.send()
    lane.before(state)
    lane.after('laneChangeStarting', 'left')
    lane.after('laneChangeFinishing', 'left')
    lane.after('off', 'none')
    self.assertEqual(self.send()['status'], 'unverified')

  def test_stale_delivery_never_runs(self):
    for delay in (1.01, 50):
      with self.subTest(delay=delay):
        self.build()
        now, lane, state = self.now, self.lane, self.state
        self.send()
        now[0] += delay
        self.assertEqual(lane.before(state), (None, False))
        self.assertEqual(self.send()['status'], 'expired')

  def test_model_stall_and_revocation_cancel_pending_only(self):
    now, service, lane, token, state = self.now, self.service, self.lane, self.token, self.state
    self.send()
    lane.before(state)
    now[0] += .4
    self.assertEqual(lane.before(state), (None, True))
    now[0] += .1
    self.send(id='y' * 43)
    lane.before(state)
    service.revoke(token, 'http://carrot:7000')
    self.assertEqual(lane.before(state), (None, True))
    with self.assertRaises(PermissionError):
      self.send()

  def test_speed_value_readback_and_dedup(self):
    for action, value, target in SPEED_VALUES:
      with self.subTest(action=action, value=value, target=target):
        self.build()
        speed = self.speed
        self.send(action=action, value=value)
        command = speed.read(allowed=True, current=80, minimum=5, maximum=145)
        self.assertEqual(command['action'], action)
        if action != 'speed_up':
          self.assertEqual(command['target'], target)
        speed.finish(target)
        self.assertEqual(self.send()['current'], target)
        self.assertIsNone(speed.read(allowed=True, current=target, minimum=5, maximum=145))

  def test_speed_conditions_and_range_reject_without_changes(self):
    for allowed, target in SPEED_RANGES:
      with self.subTest(allowed=allowed, target=target):
        self.build()
        speed = self.speed
        self.send(action='speed_set', value=target)
        self.assertIsNone(speed.read(allowed=allowed, current=80, minimum=5, maximum=145))
        self.assertEqual(self.send()['status'], 'rejected')

  def test_separate_permissions_ownership_and_one_request(self):
    service, token = self.service, self.token
    self.send()
    with self.assertRaises(ValueError):
      self.send(id='y' * 43, action='speed_up')
    with self.assertRaises(PermissionError):
      service.execute(token, 'http://other:7000', {'id': 'x' * 43})
    another = service.enable('http://carrot:7000')
    with self.assertRaises(PermissionError):
      service.execute(another, 'http://carrot:7000', {'id': 'x' * 43})
    restarted = AssistantDrive(Path(service.permissions.path), lambda: True, service.root, service.clock)
    with self.assertRaises(ValueError):
      restarted.execute(token, 'http://carrot:7000', {'id': 'x' * 43, 'operation': 'status'})

  def test_consumer_restart_and_cancel_never_replay(self):
    now, service, state = self.now, self.service, self.state
    self.send()
    now[0] += .01
    restarted = AssistantLane(service.root, lambda: now[0])
    self.assertIsNone(restarted.before(state)[0])
    self.assertEqual(self.send()['status'], 'expired')
    atomic_json(service.root / 'request.json', {'id': 'z' * 43, 'time': now[0], 'direction': 'right'})
    atomic_json(service.root / 'cancel.json', {'id': 'z' * 43})
    self.assertEqual(restarted.before(state), (None, True))

  def test_feedback_write_failure_cannot_restore_rejected_intent(self):
    lane, speed, state = self.lane, self.speed, self.state

    def unavailable(*args, **kwargs):
      raise OSError('unavailable')

    self.send()
    with mock.patch('openpilot.selfdrive.controls.lib.desire_lib.assistant_lane.atomic_json', unavailable):
      state['left']['blindspot'] = True
      self.assertEqual(lane.before(state), (None, False))
      self.assertIsNone(lane.active)
      state['left']['blindspot'] = False
      self.assertEqual(lane.before(state), (None, False))
    atomic_json(speed.root / 'request.json', {'id': 'z' * 43, 'time': 100., 'action': 'speed_up'})
    with mock.patch('openpilot.sunnypilot.carrot.assistant_speed.atomic_json', unavailable):
      self.assertIsNone(speed.read(allowed=False, current=80, minimum=30, maximum=160))
      self.assertIsNone(speed.active)
      self.assertIsNone(speed.read(allowed=True, current=80, minimum=30, maximum=160))

  def test_revocation_after_web_restart_cancels_pending_intent(self):
    service, lane, token, state = self.service, self.lane, self.token, self.state
    self.send()
    self.assertEqual(lane.before(state)[0], 'left')
    restarted = AssistantDrive(service.permissions.path, lambda: True, service.root, service.clock)
    restarted.revoke(token, 'http://carrot:7000')
    self.assertEqual(lane.before(state), (None, True))
    self.assertIsNone(lane.active)
