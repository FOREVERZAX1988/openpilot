"""TeslaTurnJourney / turn_signal_context 测试（sp 适配版）。

cp 同名测试在 controls/tests/test_tesla_turn_journey.py（pytest）。本文件把其中
不依赖 openpilot.cereal capnp 绑定与 cp modeld.py AST 的用例移植为 unittest：

- turn_signal_context 的 pose 新鲜度/有效性/权限门（cp test_native_pose_and_permission...、
  test_always_lateral... 的全部 invalid 分支，鸭子 sm/state 替代 capnp 消息）。
- TeslaTurnJourney 的几何生命周期（cp test_pose_discontinuity...、
  test_heading_wrap...、test_opposite_torque...、test_following_turn...、
  test_journey_timeout... 全量移植）。

未适配项（如实记录）：cp test_modeld_passes_validated_pose_and_hold_permission...
针对 cp modeld.py 的 AST 摘取执行，验证 modeld→DH.update 的接线；sp 的等价接线在
selfdrived/indicator_layer.py（livePose 订阅 + yaw_rate 计算），由
selfdrived/tests/test_indicator_layer_manual_turn.py 的接线测试覆盖。

在 Windows/非设备环境无需 POSIX 桩：不导入 openpilot.cereal（capnp 绑定）。
"""
import math
import unittest
from types import SimpleNamespace as NS

from openpilot.selfdrive.controls.lib.desire_lib.tesla_turn import TeslaTurnJourney, turn_signal_context

N = 10_000_000_000


def messages():
  pose = NS(inputsOK=True, sensorsOK=True, posenetOK=True, orientationNED=NS(valid=True, z=.5))
  sm = {'livePose': pose, 'selfdriveState': NS(active=True), 'carControl': NS()}
  sm['seen'] = dict.fromkeys(sm, True)
  sm['valid'] = dict.fromkeys(sm, True)
  sm['alive'] = dict.fromkeys(sm, True)
  sm['recv_time'] = dict.fromkeys(sm, 10.)
  sm['logMonoTime'] = dict.fromkeys(sm, N)

  class Messages(dict):
    pass
  result = Messages(sm)
  result.seen, result.valid, result.alive = [dict.fromkeys(result, True) for _ in range(3)]
  result.recv_time = dict.fromkeys(result, 10.)
  result.logMonoTime = dict.fromkeys(result, N)
  return result


def context_state(**kwargs):
  values = {'latEnabled': True, 'steerFaultTemporary': False, 'steerFaultPermanent': False}
  values.update(kwargs)
  return NS(**values)


class TestTurnSignalContext(unittest.TestCase):
  def test_native_pose_and_permission_require_original_fresh_valid_samples(self):
    for invalid in ('', 'unseen', 'stale_arrival', 'stale_source', 'future_source', 'invalid_message', 'dead',
                    'inputs', 'sensors', 'posenet', 'orientation', 'nan', 'disabled', 'fault', 'inactive',
                    'stale_permission'):
      with self.subTest(invalid=invalid):
        sm = messages()
        state = context_state()
        if invalid == 'unseen':
          sm.seen['livePose'] = False
        elif invalid == 'stale_arrival':
          sm.recv_time['livePose'] -= .4
        elif invalid == 'stale_source':
          sm.logMonoTime['livePose'] -= 400_000_000
        elif invalid == 'future_source':
          sm.logMonoTime['livePose'] += 1
        elif invalid == 'invalid_message':
          sm.valid['livePose'] = False
        elif invalid == 'dead':
          sm.alive['livePose'] = False
        elif invalid in ('inputs', 'sensors', 'posenet'):
          setattr(sm['livePose'], invalid + 'OK', False)
        elif invalid == 'orientation':
          sm['livePose'].orientationNED.valid = False
        elif invalid == 'nan':
          sm['livePose'].orientationNED.z = float('nan')
        elif invalid == 'disabled':
          state.latEnabled = False
        elif invalid == 'fault':
          state.steerFaultTemporary = True
        elif invalid == 'inactive':
          sm['selfdriveState'].active = False
        elif invalid == 'stale_permission':
          sm.recv_time['selfdriveState'] -= .4
        allowed, pose = turn_signal_context(sm, state, 10., N, False)
        self.assertEqual(allowed, invalid == '')
        if invalid in ('', 'disabled', 'fault', 'inactive', 'stale_permission'):
          self.assertEqual(pose, (N, .5))
        else:
          self.assertIsNone(pose)

  def test_always_lateral_is_permission_not_a_fault_or_freshness_override(self):
    sm = messages()
    sm['selfdriveState'].active = False
    state = context_state()
    self.assertTrue(turn_signal_context(sm, state, 10., N, True)[0])
    state.latEnabled = False
    self.assertFalse(turn_signal_context(sm, state, 10., N, True)[0])
    state.latEnabled = True
    sm.valid['carControl'] = False
    self.assertFalse(turn_signal_context(sm, state, 10., N, True)[0])


def advance(journey, tick, yaw=0., angle=90., speed=5., nav='turn left', distance=20, desire=1, **overrides):
  state = NS(vEgo=speed, steeringAngleDeg=angle, steeringPressed=False, steeringTorque=0.)
  state.__dict__.update(overrides)
  return journey.update(10. + tick * .05, state, (N + tick * 50_000_000, yaw), nav, distance, desire, True, True)


class TestTeslaTurnJourney(unittest.TestCase):
  def test_pose_discontinuity_never_finishes_a_previously_entered_turn(self):
    for fault in ('gap', 'backwards', 'jump', 'nan_angle', 'nan_speed'):
      with self.subTest(fault=fault):
        journey = TeslaTurnJourney()
        for i in range(12):
          self.assertEqual(advance(journey, i, yaw=-i * .05), 1)
        self.assertTrue(journey.entered)
        tick, yaw, angle, speed = 12, -.55, 10., 5.
        if fault == 'gap':
          tick = 30
        elif fault == 'backwards':
          tick = 3
        elif fault == 'jump':
          yaw = 2.
        elif fault == 'nan_angle':
          angle = float('nan')
        else:
          speed = float('nan')
        self.assertEqual(advance(journey, tick, yaw=yaw, angle=angle, speed=speed), 1)
        self.assertFalse(journey.entered)

  def test_heading_wrap_and_stopped_drift_do_not_fabricate_turn_rotation(self):
    journey = TeslaTurnJourney()
    advance(journey, 0, yaw=-3.1)
    advance(journey, 1, yaw=3.1)
    self.assertAlmostEqual(journey.rotation, 2 * math.pi - 6.2, places=6)
    for i in range(2, 15):
      advance(journey, i, yaw=3.1 - (i - 1) * .05, speed=0., angle=0.)
    self.assertFalse(journey.entered)
    self.assertLess(journey.rotation, math.radians(20))

  def test_opposite_torque_needs_wheel_past_zero_and_manual_abort_never_replays(self):
    for driver_abort in (False, True):
      with self.subTest(driver_abort=driver_abort):
        journey = TeslaTurnJourney()
        for i in range(5):
          advance(journey, i, yaw=-i * .05)
        self.assertEqual(advance(journey, 5, yaw=-.2, angle=20., steeringPressed=True, steeringTorque=-1.), 1)
        result = advance(journey, 6, yaw=-.2, angle=-.1 if driver_abort else 0., steeringPressed=True, steeringTorque=-1.)
        self.assertEqual(result, 0 if driver_abort else 1)
        if driver_abort:
          self.assertEqual(advance(journey, 7, yaw=-.2), 0)

  def test_following_turn_is_bounded_and_only_handed_over_after_completion(self):
    for same_side in (False, True):
      for delay in (1, 80):
        with self.subTest(same_side=same_side, delay=delay):
          journey = TeslaTurnJourney()
          for i in range(12):
            advance(journey, i, yaw=-i * .05)
          direction = 1 if same_side else 2
          nav = 'turn left' if same_side else 'turn right'
          self.assertEqual(advance(journey, 12, yaw=-.55, nav=nav, distance=100, desire=direction), 1)
          for tick in range(13, 13 + delay):
            self.assertEqual(advance(journey, tick, yaw=-.55, nav=nav, distance=100, desire=direction), 1)
          self.assertEqual(advance(journey, 13 + delay, yaw=-.55, angle=0., nav=nav, distance=100, desire=direction),
                           direction if delay == 1 else 0)
          self.assertFalse(journey.entered)
          self.assertEqual(advance(journey, 14 + delay, yaw=-.55, angle=0., nav=nav, distance=100, desire=direction),
                           direction if delay == 1 else 0)

  def test_journey_timeout_does_not_rearm_same_turn(self):
    journey = TeslaTurnJourney()
    self.assertEqual(advance(journey, 0), 1)
    self.assertEqual(advance(journey, 1200), 0)
    self.assertEqual(advance(journey, 1201, distance=100), 0)


if __name__ == '__main__':
  unittest.main()
