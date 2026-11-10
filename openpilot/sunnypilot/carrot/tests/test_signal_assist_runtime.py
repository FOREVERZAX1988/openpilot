import json
from pathlib import Path
from types import SimpleNamespace as NS
import unittest

from openpilot.common.repo_tools import load
from openpilot.sunnypilot.carrot.signal_assist_runtime import SignalAssistRuntime, publish_observation


class SM(dict):
  def __init__(self):
    super().__init__(carState=NS(canValid=True, gearShifter='drive'), selfdriveState=NS(enabled=True), carControl=NS(longActive=True))
    names = ['carState', 'modelV2', 'radarState', 'selfdriveState', 'carControl']
    self.seen = dict.fromkeys(names, True)
    self.valid = dict.fromkeys(names, True)
    self.alive = dict.fromkeys(names, True)
    self.recv_time = dict.fromkeys(names, 10.)


class TestSignalAssistRuntime(unittest.TestCase):

  def setUp(self):
    import tempfile
    import shutil
    tmp = tempfile.mkdtemp(prefix="signal_assist_rt_test_")
    self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
    self.tmp_path = Path(tmp)

  def test_default_does_not_enable_control(self):
    runtime = SignalAssistRuntime(self.tmp_path / 'enable', self.tmp_path / 'obs')
    self.assertIsNone(runtime.assist)

  def test_revalidation_requires_both_explicit_flags(self):
    # assist_enabled is retired (requested() forces False); use a plain flag file
    for assist, trial in [(False, False), (False, True), (True, False), (True, True)]:
      with self.subTest(assist=assist, trial=trial):
        flag = self.tmp_path / 'enable'
        flag.write_text('1' if assist else '0')
        (self.tmp_path / 'revalidated_enabled').write_text('1' if trial else '0')
        runtime = SignalAssistRuntime(flag, self.tmp_path / 'obs')
        self.assertEqual(runtime.assist is not None, assist)
        if assist:
          self.assertIs(runtime.assist.producer_red_history, trial)

  def test_atomic_round_trip_and_disable(self):
    flag, path = self.tmp_path / 'enable', self.tmp_path / 'obs'
    flag.write_text('1')
    runtime = SignalAssistRuntime(flag, path)
    publish_observation({'tracks': []}, 1, 10., 'worker', path)
    obs, context = runtime.read(SM(), 10.1)
    self.assertEqual(obs['timestamp'], 10.)
    self.assertTrue(context['enabled'])
    self.assertTrue(context['valid'])
    flag.write_text('0')
    obs, context = runtime.read(SM(), 10.7)
    self.assertIsNone(obs)
    self.assertFalse(context['enabled'])

  def test_bad_transport_is_unknown(self):
    for payload in ['invalid', '[]', '{}', 'x' * 40000,
                    json.dumps({'version': 2, 'stream': 'road', 'size': [1344, 760]})]:
      with self.subTest(payload=payload[:20]):
        flag, path = self.tmp_path / 'enable', self.tmp_path / 'obs'
        flag.write_text('1')
        path.write_text(payload)
        obs, _ = SignalAssistRuntime(flag, path).read(SM(), 10.1)
        self.assertIsNone(obs)

  def test_runtime_gates_vehicle_context(self):
    for condition in ['stale', 'unseen', 'invalid', 'dead', 'park', 'inactive']:
      with self.subTest(condition=condition):
        flag = self.tmp_path / 'enable'
        flag.write_text('1')
        sm = SM()
        if condition == 'stale':
          sm.recv_time['carState'] = 9.
        elif condition == 'unseen':
          sm.seen['modelV2'] = False
        elif condition == 'invalid':
          sm.valid['carState'] = False
        elif condition == 'dead':
          sm.alive['radarState'] = False
        elif condition == 'park':
          sm['carState'].gearShifter = 'park'
        elif condition == 'inactive':
          sm['carControl'].longActive = False
        _, context = SignalAssistRuntime(flag, self.tmp_path / 'absent').read(sm, 10.1)
        self.assertFalse(all(context[x] for x in ('valid', 'enabled', 'drive')))

  def test_producer_history_survives_transport_and_fresh_consumer_release(self):
    SignalTracker = load('signal_analysis/signal_tracker.py').SignalTracker
    from openpilot.sunnypilot.carrot.tests.test_signal_assist import step
    flag, path = self.tmp_path / 'enable', self.tmp_path / 'obs'
    flag.write_text('1')
    runtime = SignalAssistRuntime(flag, path)
    tracker = SignalTracker()

    def consume(now):
      sm = SM()
      sm.recv_time = dict.fromkeys(sm.recv_time, now)
      obs, context = runtime.read(sm, now)
      context.pop('now')
      return step(runtime.assist, now, obs, **context)

    dec = None
    for i in range(11):
      t = 9. + i * .1
      result = tracker.update(t, [{'box': [640, 250, 680, 270], 'raw': 'red', 'quality': .8}])
      publish_observation(result, i, t, 'worker', path)
      dec = consume(t + .1)
    self.assertTrue(dec.hold)
    for i in range(3):
      t = 10.2 + i * .2
      result = tracker.update(t, [{'box': [640, 250, 680, 270], 'raw': 'green', 'quality': .8}])
      publish_observation(result, 11 + i, t, 'worker', path)
    dec = consume(10.79)
    self.assertTrue(dec.released)
    self.assertFalse(dec.hold)


class SelfdrivedSM(dict):
  """selfdrived hosts the longitudinal planner on this fork and publishes (does
  not subscribe to) selfdriveState, so the runtime must gate on carControl."""
  def __init__(self, long_active=True):
    super().__init__(carState=NS(canValid=True, gearShifter='drive'),
                     carControl=NS(longActive=long_active))
    names = ['carState', 'modelV2', 'radarState', 'carControl']
    self.seen = dict.fromkeys(names, True)
    self.valid = dict.fromkeys(names, True)
    self.alive = dict.fromkeys(names, True)
    self.recv_time = dict.fromkeys(names, 10.)


class TestSelfdrivedGating(unittest.TestCase):

  def setUp(self):
    import tempfile
    import shutil
    tmp = tempfile.mkdtemp(prefix="signal_assist_rt_test_")
    self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
    self.tmp_path = Path(tmp)

  def test_selfdrived_without_selfdrivestate_gates_on_carcontrol(self):
    flag, path = self.tmp_path / 'enable', self.tmp_path / 'absent'
    flag.write_text('1')
    runtime = SignalAssistRuntime(flag, path)
    _, context = runtime.read(SelfdrivedSM(long_active=True), 10.1)
    self.assertTrue(context['enabled'])
    self.assertTrue(context['valid'])
    self.assertTrue(context['drive'])
    # Long control inactive -> supervision must not engage.
    _, context_off = runtime.read(SelfdrivedSM(long_active=False), 10.2)
    self.assertFalse(context_off['enabled'])


if __name__ == "__main__":
  unittest.main()
