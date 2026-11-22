import os
import random

import numpy as np

from openpilot.common.test import OpenpilotTestCase
from openpilot.cereal import log, messaging
from opendbc.car.structs import car
from openpilot.selfdrive.locationd.paramsd import retrieve_initial_vehicle_params, VehicleParamsLearner
from openpilot.selfdrive.locationd.models.car_kf import CarKalman
from openpilot.selfdrive.locationd.test.test_locationd_scenarios import TEST_ROUTE
from openpilot.selfdrive.test.process_replay.migration import migrate, migrate_carParams
from openpilot.common.params import Params
from openpilot.tools.lib.logreader import LogReader
from opendbc.car.structs import car


def get_test_car_params() -> car.CarParams:
  """测试用 CarParams：优先本机正在跑的车型，避免为取一份 CP 去下载远端 route。

  TEST_ROUTE 只用来拿一份 CarParams。设备 offline、或 AGNOS 上没有出网时，
  LogReader 会卡在下载，用例就从"逻辑失败"变成"环境失败"（2026-11-23 实测：
  在 comma three 上直接超时被杀）。有本地 CP 就用本地，没有才回退远端。
  """
  local = "/data/params/d/CarParamsPersistent"
  if os.path.isfile(local):
    with open(local, "rb") as f:
      return messaging.log_from_bytes(f.read(), car.CarParams)
  lr = migrate(LogReader(TEST_ROUTE), [migrate_carParams])
  return next(m for m in lr if m.which() == "carParams").carParams


def get_random_vehicle_parameters(CP):
  msg = messaging.new_message("vehicleParameters")
  msg.vehicleParameters.steerRatio = (random.random() + 0.5) * CP.steerRatio
  msg.vehicleParameters.stiffnessFactor = random.random()
  msg.vehicleParameters.angleOffsetAverageDeg = random.random()
  msg.vehicleParameters.debugFilterState.std = [random.random() for _ in range(CarKalman.P_initial.shape[0])]
  return msg


class TestParamsd(OpenpilotTestCase):
  def test_read_saved_params(self):
    params = Params()

    # 必须给几何参数：retrieve_initial_vehicle_params 会算 centerToFront/wheelbase
    # 来判定"车辆几何是否变了"，两者都为 0 时 0/0 抛 ZeroDivisionError，被 catch
    # 后当成"恢复失败"回退到 CP.steerRatio，断言就必然红（2026-11-23 定位）。
    CP = car.CarParams(carFingerprint="HONDA_CIVIC", steerRatio=15.38,
                       wheelbase=2.7, centerToFront=1.2)

    msg = get_random_vehicle_parameters(CP)
    params.put("LiveParametersV2", msg.to_bytes(), block=True)
    params.put("CarParamsPrevRoute", CP.to_bytes(), block=True)

    sr, sf, offset, p_init = retrieve_initial_vehicle_params(params, CP, replay=True, debug=True)
    np.testing.assert_allclose(sr, msg.vehicleParameters.steerRatio)
    np.testing.assert_allclose(sf, msg.vehicleParameters.stiffnessFactor)
    np.testing.assert_allclose(offset, msg.vehicleParameters.angleOffsetAverageDeg)
    np.testing.assert_equal(p_init.shape, CarKalman.P_initial.shape)
    np.testing.assert_allclose(np.diagonal(p_init), msg.vehicleParameters.debugFilterState.std)

  def test_learning_survives_incomplete_imu_calibration(self):
    """未校准外参不得冻结转向角学习，只让依赖外参的 yaw/roll 退让。

    paramsd 原先把 calib_valid 也放进 active 门控。这台车的相机从不开
    （spectra VIDIOC_CAM_CONTROL errno 19），calibrationd 永远收不了尾，
    calib_valid 长期 false，于是 2026-11-18 清掉 LiveParametersV2 之后
    一帧都没学过：angleOffsetDeg 恒 0、angleOffsetAverageStd 精确等于初始 Q
    (0.000349)，却仍报 angleOffsetValid=true，横向严重偏左。

    现在未校准时只有 yaw_rate_valid / roll_valid 被挡（退回 0±10° 有界值），
    转向角与车速观测照常，偏置仍能在直路上收敛。见 paramsd.py active 段注释。
    """
    CP = get_test_car_params()

    learner = VehicleParamsLearner(CP, CP.steerRatio, 1.0, 0.0)

    # 未校准（动态收集中）：转向角仍必须被观测，不能冻结
    ec = messaging.new_message("extrinsicsCalibration").extrinsicsCalibration
    ec.calStatus = log.ExtrinsicsCalibration.Status.uncalibrated
    ec.rpyCalib = [0.0, 0.0, 0.0]
    learner.handle_log(0.0, "extrinsicsCalibration", ec)

    cs = messaging.new_message("carState").carState
    cs.vEgo = 15.0
    cs.steeringAngleDeg = 0.0
    cs.gearShifter = car.CarState.GearShifter.drive
    learner.handle_log(1.0, "carState", cs)
    self.assertFalse(learner.calibrator.calib_valid, "本用例应处于未校准状态")
    self.assertTrue(learner.active,
                    "未校准不得冻结转向角学习：转向角/车速不依赖 IMU 外参")

    # Completed calibration with a valid matrix allows learning to resume.
    ec2 = messaging.new_message("extrinsicsCalibration").extrinsicsCalibration
    ec2.calStatus = log.ExtrinsicsCalibration.Status.calibrated
    ec2.rpyCalib = [0.0, 0.0, 0.0]
    ec2.imuCalibMatrix = np.eye(3, dtype=np.float32).flatten().tolist()
    learner.handle_log(2.0, "extrinsicsCalibration", ec2)

    learner.handle_log(3.0, "carState", cs)
    self.assertTrue(learner.active)

  def test_low_speed_does_not_activate_learner(self):
    """The bicycle-model fit is ill-conditioned at low speed.

    delta ~= yaw_rate * steerRatio * wheelbase / v, so a given yaw-rate error maps
    to a steering-angle error that scales with 1/v. Learning from parking-lot speeds
    walked ANGLE_OFFSET_FAST from -4 to -12 deg and latched "Steering misalignment
    detected" (route 00000036, 2026-11-18). The learner must stay inactive there.
    """
    CP = get_test_car_params()
    learner = VehicleParamsLearner(CP, CP.steerRatio, 1.0, 0.0)

    ec = messaging.new_message("extrinsicsCalibration").extrinsicsCalibration
    ec.calStatus = log.ExtrinsicsCalibration.Status.calibrated
    ec.rpyCalib = [0.0, 0.0, 0.0]
    ec.imuCalibMatrix = np.eye(3, dtype=np.float32).flatten().tolist()
    learner.handle_log(0.0, "extrinsicsCalibration", ec)

    cs = messaging.new_message("carState").carState
    cs.steeringAngleDeg = 0.0
    cs.gearShifter = car.CarState.GearShifter.drive

    cs.vEgo = 3.0
    learner.handle_log(1.0, "carState", cs)
    self.assertFalse(learner.active)

    cs.vEgo = 8.0
    learner.handle_log(2.0, "carState", cs)
    self.assertTrue(learner.active)

  def test_inputsOK_false_ignores_yaw_rate_and_roll(self):
    """paramsd must not learn from deviceMotion that locationd has rejected.

    On 2026-11-17 route 0000002d seg4, locationd set inputsOK=false for the
    whole segment (gyro/camera yaw-rate cross-check tripped on Macan vibration)
    while angularVelocityDevice.valid / posenetOK / sensorsOK all stayed true.
    paramsd used those "valid" but upstream-rejected yaw rates to learn
    angleOffset, which ran away to -13.9 deg, latched angleOffsetValid=false,
    and surfaced as "Steering misalignment detected" after the next engage.
    The learner must respect locationd's own verdict.
    """
    CP = get_test_car_params()
    learner = VehicleParamsLearner(CP, CP.steerRatio, 1.0, 0.0)

    # 先完成校准：2026-11-21 起 yaw_rate_valid 也要求 calibrator.calib_valid
    # （未校准时外参不可信，yaw 只退回 0±10° 有界值）。不先校准的话，下面的
    # 对照组会连同 calib 一起被拒，测不出 inputsOK 本身的作用。
    _cal = messaging.new_message("extrinsicsCalibration").extrinsicsCalibration
    _cal.calStatus = log.ExtrinsicsCalibration.Status.calibrated
    _cal.rpyCalib = [0.0, 0.0, 0.0]
    _cal.imuCalibMatrix = np.eye(3, dtype=np.float32).flatten().tolist()
    learner.handle_log(0.0, "extrinsicsCalibration", _cal)

    def make_device_motion(inputs_ok):
      dm = messaging.new_message("deviceMotion").deviceMotion
      dm.timestamp = 4_000_000_000
      dm.inputsOK = inputs_ok
      dm.posenetOK = True
      dm.sensorsOK = True
      dm.angularVelocityDevice.valid = True
      dm.angularVelocityDevice.x = 0.5
      dm.angularVelocityDevice.y = 0.0
      dm.angularVelocityDevice.z = 0.5
      dm.angularVelocityDevice.xStd = 0.01
      dm.angularVelocityDevice.yStd = 0.01
      dm.angularVelocityDevice.zStd = 0.01
      dm.orientationNED.valid = True
      dm.orientationNED.x = 0.0
      dm.orientationNED.y = 0.0
      dm.orientationNED.z = 0.0
      dm.orientationNED.xStd = 0.01
      dm.orientationNED.yStd = 0.01
      dm.orientationNED.zStd = 0.01
      return dm

    # locationd rejected its inputs: paramsd must bound yaw rate to 0 (the
    # "invalid" fallback), not adopt the 0.5 rad/s device reading.
    learner.handle_log(4.0, "deviceMotion", make_device_motion(False))
    self.assertEqual(learner.observed_yaw_rate, 0.0)

    # Control: same reading with inputsOK=true is adopted as before.
    learner.handle_log(5.0, "deviceMotion", make_device_motion(True))
    self.assertNotEqual(learner.observed_yaw_rate, 0.0)
