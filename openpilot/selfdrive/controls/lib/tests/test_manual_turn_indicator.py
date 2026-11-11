"""ManualTurnIndicator / following_road_curve / ModelIndicator manual-turn 集成测试（sp 适配版）。

cp manual-turn 行为覆盖在 controls/tests/test_desire_helper_stalk.py 的
test_manual_turn_signal_remains_isolated_during_acceleration_with_atc_off（经完整
cp DesireHelper 驱动）。sp 的灯效观测层挂在 selfdrived/indicator_layer.py，desire
仍是红线，因此这里直接驱动 sp 实际拥有的组件：

- desire_lib.manual_turn_indicator.ManualTurnIndicator：准入速度窗、扭矩意图、
  确认几何（角度/横摆积分）、road_curve 阻断、反向回正完成。
- desire_lib.indicator_observer.following_road_curve：曲率车道几何与实测横摆一致性。
- desire_lib.indicator_observer.ModelIndicator：cp 同款 90 帧加速场景
  （manual_turn_enabled + yaw_rate），确认 manual_turn 起源且不产生任何 desire。
  lateral_active 两种取值均覆盖（cp 同）。

未适配项（如实记录）：cp 经 DesireHelper._update_driver_blinker / lane_change_state
联动的断言依赖 cp FSM（sp desire_helper 保留自己的回退架构，见
test_desire_helper_stalk.py 头注）；本文件用 lane 几何 + desireState 全零的模型帧
保证自动来源永不触发，等价覆盖“不影响 desire”的语义。

在 Windows/非设备环境无需 POSIX 桩：不导入 openpilot.cereal（capnp 绑定），
cs/md/isolation 均为 SimpleNamespace 鸭子对象。
"""
import math
import unittest
from types import SimpleNamespace as NS

from openpilot.selfdrive.controls.lib.desire_lib.boundary_indicator import BoundaryIndicator
from openpilot.selfdrive.controls.lib.desire_lib.indicator_observer import (
  MANUAL_TURN_QUIET_SEC, ModelIndicator, following_road_curve,
)
from openpilot.selfdrive.controls.lib.desire_lib.manual_turn_indicator import ManualTurnIndicator

DT = .05  # 20 Hz 模型帧节奏（cp DT_MDL）


def model(stRAIGHT=True, curvature=0., frame=0):
  """鸭子 modelV2：内侧/外侧 lane line + road edge，y 为常数（直道）或抛物线（弯道）。"""
  def y_for(x, base):
    return base + curvature * x * x / 2.

  xs = [float(x) for x in range(33)]
  return NS(
    frameId=frame, valid=True,
    laneLines=[NS(x=xs, y=[y_for(x, base) for x in xs]) for base in (-5.4, -1.8, 1.8, 5.4)],
    laneLineProbs=[.9, .9, .9, .9],
    roadEdges=[NS(y=[y_for(x, -6.2) for x in xs]), NS(y=[y_for(x, 6.2) for x in xs])],
    roadEdgeStds=[.1, .1],
    meta=NS(desireState=[1., 0., 0., 0., 0., 0., 0., 0.]),
  )


def car_state(**kwargs):
  values = {
    'canValid': True, 'gearShifter': 'drive', 'trailerConnected': False,
    'steerFaultTemporary': False, 'steerFaultPermanent': False, 'blinkerLever': 0,
    'vEgo': 5., 'steeringTorque': 0., 'steeringPressed': False, 'steeringAngleDeg': 0.,
    'leftBlinker': False, 'rightBlinker': False,
    'laneLineInfoMonoTime': 0, 'leftLaneLine': 10, 'rightLaneLine': 10,
    'leftBlindspot': False, 'rightBlindspot': False,
  }
  values.update(kwargs)
  return NS(**values)


def drive_manual_turn(lateral_active=True, enabled=True, yaw_rate=None, blink_at=50):
  """cp test_manual_turn_signal_remains_isolated_during_acceleration_with_atc_off 的
  ModelIndicator 级重放：90 帧，i=25 起左转扭矩与角度斜坡，i=29 起注入实测横摆。"""
  indicator = ModelIndicator()
  boundary = BoundaryIndicator()
  md_frames = (model(frame=i) for i in range(90))
  saw_request = False
  md = None
  for i, md in enumerate(md_frames):
    now = 10. + i * DT
    cs = car_state(steeringPressed=25 <= i < 55,
                   steeringTorque=400. if 25 <= i < 55 else 0.,
                   steeringAngleDeg=min(100., max(0, i - 25) * 8.),
                   vEgo=12. if i >= 55 else 5.,
                   leftBlinker=i >= blink_at)
    rate = (yaw_rate if yaw_rate is not None else (-.2 if i >= 29 else 0.)) if enabled else None
    boundary.update(now, cs, md, enabled=False, valid=True, busy=False)
    indicator.update(now, cs, md, valid=True, lateral_active=lateral_active,
                     desire_enabled=False, path_enabled=False, busy=False,
                     isolation=boundary, manual_turn_enabled=enabled, yaw_rate=rate)
    saw_request |= indicator.active is not None
  return indicator, saw_request


class TestManualTurnIndicator(unittest.TestCase):
  def test_below_min_speed_is_never_admitted(self):
    observer = ManualTurnIndicator()
    cs = car_state(vEgo=1., steeringPressed=True, steeringTorque=400., steeringAngleDeg=50.)
    self.assertIsNone(observer.update(10., cs, 0, -.3, allowed=True))
    self.assertEqual(observer.reason, 'admission')

  def test_confirmed_turn_produces_movement(self):
    observer = ManualTurnIndicator()
    movement = None
    for i in range(40):
      now = 10. + i * DT
      angle = max(0, i) * 8.
      cs = car_state(steeringPressed=True, steeringTorque=400., steeringAngleDeg=angle, vEgo=8.)
      movement = observer.update(now, cs, i, -.3, allowed=True)
      if movement is not None:
        break
    self.assertIsNotNone(movement)
    self.assertEqual(movement.direction, 1)
    self.assertEqual(movement.source, 'manual_turn')

  def test_road_curve_blocks_confirmation(self):
    observer = ManualTurnIndicator()
    for i in range(40):
      now = 10. + i * DT
      cs = car_state(steeringPressed=True, steeringTorque=400., steeringAngleDeg=i * 8., vEgo=8.)
      self.assertIsNone(observer.update(now, cs, i, -.3, allowed=True, following_curve=True))
    self.assertEqual(observer.reason, 'road_curve')
    self.assertIsNone(observer.candidate)

  def test_driver_opposite_steering_ends_movement(self):
    observer = ManualTurnIndicator()
    movement = None
    for i in range(40):
      cs = car_state(steeringPressed=True, steeringTorque=400., steeringAngleDeg=i * 8., vEgo=8.)
      movement = observer.update(10. + i * DT, cs, i, -.3, allowed=True)
      if movement is not None:
        break
    self.assertIsNotNone(movement)
    # 反向扭矩 + 反向角度：回正结束（ManualTurnMovement.driver_opposite）。
    cs = car_state(steeringPressed=True, steeringTorque=-400., steeringAngleDeg=-10., vEgo=8.)
    self.assertFalse(movement.update(10. + (i + 1) * DT, cs, -.3))
    self.assertEqual(movement.reason, 'driver_opposite')


class TestFollowingRoadCurve(unittest.TestCase):
  def test_straight_lanes_do_not_mask_a_turn(self):
    self.assertFalse(following_road_curve(model(), 10., -.2))
    self.assertFalse(following_road_curve(model(), 10., .2))

  def test_matched_curved_lane_agrees_with_vehicle_arc(self):
    md = model(curvature=-.01)  # 左弯（y 随 x 为负增长）
    self.assertTrue(following_road_curve(md, 10., -.1))

  def test_unmatched_curvature_is_rejected(self):
    md = model(curvature=-.01)
    self.assertFalse(following_road_curve(md, 10., .1))
    self.assertFalse(following_road_curve(md, 10., -.05))  # 半量偏差超出容差

  def test_invalid_inputs_are_rejected(self):
    self.assertFalse(following_road_curve(model(), 10., None))
    self.assertFalse(following_road_curve(model(), .5, -.2))  # speed < 1
    self.assertFalse(following_road_curve(model(), 10., 0.))


class TestModelIndicatorManualTurn(unittest.TestCase):
  def test_manual_turn_request_remains_isolated_during_acceleration(self):
    # cp 同款场景：lateral_active 两种取值下 manual_turn 均可确认，且全程无 desire。
    for lateral_active in (False, True):
      with self.subTest(lateral_active=lateral_active):
        indicator, saw_request = drive_manual_turn(lateral_active)
        self.assertTrue(saw_request)
        self.assertEqual(indicator.active.source, 'manual_turn')
        self.assertNotEqual(indicator.reason, 'model_desire')
        self.assertIsNone(indicator.candidate)

  def test_disabled_by_param_never_requests(self):
    indicator, saw_request = drive_manual_turn(enabled=False)
    self.assertFalse(saw_request)
    self.assertEqual(indicator.manual_turn.reason, 'disabled')

  def test_driver_lamp_blocks_observation(self):
    # cp：手动灯亮期间（i>=50）dark window 打断；这里整程左灯亮 → 观测从未准入。
    indicator, saw_request = drive_manual_turn(blink_at=0)
    self.assertFalse(saw_request)

  def test_quiet_sec_shorter_than_lane_change_isolation(self):
    # 手动转弯在 boundary 隔离窗内更早重臂（QUIET_SEC 3s vs MANUAL_TURN_QUIET_SEC 2s）。
    self.assertLess(MANUAL_TURN_QUIET_SEC, 3.)


if __name__ == '__main__':
  unittest.main()
