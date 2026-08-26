#!/usr/bin/env python3
import math
import time
import numpy as np

import openpilot.cereal.messaging as messaging
from opendbc.car.interfaces import ACCEL_MIN, ACCEL_MAX
from openpilot.common.constants import CV
from openpilot.common.filter_simple import FirstOrderFilter
from openpilot.common.realtime import DT_MDL
from openpilot.selfdrive.modeld.constants import ModelConstants
from openpilot.selfdrive.controls.lib.longcontrol import LongCtrlState
from openpilot.selfdrive.controls.lib.longitudinal_mpc_lib.long_mpc import LongitudinalMpc, LongitudinalPlanSource
from openpilot.selfdrive.controls.lib.longitudinal_mpc_lib.long_mpc import T_IDXS as T_IDXS_MPC
from openpilot.selfdrive.controls.lib.drive_helpers import CONTROL_N, get_accel_from_plan, should_stop
from openpilot.selfdrive.car.cruise import V_CRUISE_MAX, V_CRUISE_UNSET
from openpilot.common.swaglog import cloudlog
from openpilot.common.params import Params

from openpilot.sunnypilot.selfdrive.controls.lib.longitudinal_planner import LongitudinalPlannerSP

A_CRUISE_MAX_VALS = [1.6, 1.2, 0.8, 0.6]
A_CRUISE_MAX_BP = [0., 10.0, 25., 40.]
J_CRUISE_VALS = [1.6, 1.2, 0.8, 0.6]
A_CRUISE_MIN = -1.2
# Macan 巡航滑行带（2026-08-26 根因修复：005f/0060 喘息振荡）
# 原链路：target_accel=clip(v_cruise-v_ego, -1.2, max)——P=1 无限幅带，0.7s 执行滞后+惯性
# → vEgo 过冲 → 反向全力(±1.2) → 极限环(±1.3m/s, ~10s 周期)=“忽快忽慢、无滑行感”
# 带内(±0.4m/s)输出 0 = 滑行，车自然收敛；带外 deadband 控制（边界连续无跳变）
_MACAN_CRUISE_COAST_BAND = 0.4  # m/s ≈ ±1.4km/h
_macan_cruise_coast = 0.0
_macan_cruise_coast_t = 0.0
def _get_macan_cruise_coast():
  """Macan 巡航滑行带（MacanCruiseCoastEnable/Band 参数）：总开关关或 band<=0 → 0（回退原行为）"""
  global _macan_cruise_coast, _macan_cruise_coast_t
  now = time.monotonic()
  if now - _macan_cruise_coast_t > 1.0:  # 每1秒刷新（不阻塞）
    try:
      if Params().get_bool("MacanCruiseCoastEnable"):
        # return_default=True：参数未写入时用默认 0.4（避免 None→0 导致"开了开关但带宽=0 不生效"）
        _macan_cruise_coast = float(Params().get("MacanCruiseCoastBand", return_default=True) or 0.0)
      else:
        _macan_cruise_coast = 0.0
    except Exception:
      _macan_cruise_coast = 0.0
    _macan_cruise_coast_t = now
  return _macan_cruise_coast or 0.0
CONTROL_N_T_IDX = ModelConstants.T_IDXS[:CONTROL_N]
ALLOW_THROTTLE_THRESHOLD = 0.4
MIN_ALLOW_THROTTLE_SPEED = 2.5

# Lookup table for turns
_A_TOTAL_MAX_V = [1.7, 3.2]
_A_TOTAL_MAX_BP = [20., 40.]

def get_max_accel(v_ego):
  return np.interp(v_ego, A_CRUISE_MAX_BP, A_CRUISE_MAX_VALS)

# Macan 加速度限制（MacanAccelLimit 参数，m/s²；0=关闭用原厂曲线）
# 数据依据（0000004f）：激活时间 20.2% 在 aTarget>1.0、14.7% 在 >1.2（低速曲线允许1.6）
# ——起步/跟车加速顶到 1.4-1.6 即"忽然加速"体感来源；限到 1.0-1.2 舒适
_macan_accel_limit = 0.0
_macan_accel_limit_t = 0.0
def _get_macan_accel_limit():
  global _macan_accel_limit, _macan_accel_limit_t
  now = time.monotonic()
  if now - _macan_accel_limit_t > 1.0:  # 每1秒刷新（不阻塞）
    try:
      _macan_accel_limit = float(Params().get("MacanAccelLimit") or 0.0)  # FLOAT 参数 get() 返回 float
    except Exception:
      _macan_accel_limit = 0.0
    _macan_accel_limit_t = now
  return _macan_accel_limit

# Macan 弯道系数开关（MacanCornerLimit，BOOL；开=启用，强度下限硬编码 0.3）
# 数据依据（0000004f）：62%加速事件发生在 |angle|>8°；回放验证 0.36-0.85 压限
# 强度参数化待后续（FLOAT 开关需 params 库重编译，暂用常量）
_MACAN_CORNER_MIN = 0.3
_macan_corner_on = False
_macan_corner_on_t = 0.0
def _get_macan_corner_on():
  global _macan_corner_on, _macan_corner_on_t
  now = time.monotonic()
  if now - _macan_corner_on_t > 1.0:  # 每1秒刷新（不阻塞）
    try:
      # BOOL 参数：get() 返回 python bool，必须用 get_bool()（== "1" 会永远 False）
      _macan_corner_on = Params().get_bool("MacanCornerLimit")
    except Exception:
      _macan_corner_on = False
    _macan_corner_on_t = now
  return _macan_corner_on

def _macan_accel_limited(max_accel: float, CP) -> float:
  """对 Macan 应用自定义加速度上限（其他车不受影响）"""
  try:
    fp = CP.carFingerprint.upper()
  except Exception:
    return max_accel
  if "MACAN" not in fp:
    return max_accel
  lim = _get_macan_accel_limit()
  if lim > 0:
    return min(max_accel, lim)
  return max_accel


# Macan aTarget 死区（MacanAccelDeadzone，m/s²；0=关闭）
# 机制实锤（0000004f 段7 帧97000-97700）：MPC 在 0 附近微抖动（+0.04→-0.06 来回过零），
# aTarget 过零时 mom 在巡航维持(~95)与滑行(0)之间跳变 = "喘气/一冲一冲"体感
_macan_deadzone = 0.0
_macan_deadzone_t = 0.0
def _get_macan_deadzone():
  global _macan_deadzone, _macan_deadzone_t
  now = time.monotonic()
  if now - _macan_deadzone_t > 1.0:  # 每1秒刷新
    try:
      # 总开关：MacanAccelDeadzoneEnable=false 时强制 0（数值保留但不生效，杜绝"关了还生效"）
      if Params().get_bool("MacanAccelDeadzoneEnable"):
        _macan_deadzone = float(Params().get("MacanAccelDeadzone") or 0.0)
      else:
        _macan_deadzone = 0.0
    except Exception:
      _macan_deadzone = 0.0
    _macan_deadzone_t = now
  return _macan_deadzone

def get_coast_accel(pitch):
  return np.sin(pitch) * -5.65 - 0.3  # fitted from data using xx/projects/allow_throttle/compute_coast_accel.py

def get_cruise_accel(e2e, v_cruise, v_ego, a_cruise_prev, angle_steers, CP, dt, accel_coast, allow_throttle):
  max_accel = ACCEL_MAX if e2e else get_max_accel(v_ego)
  max_accel = _macan_accel_limited(max_accel, CP)
  # Macan 弯道系数：方向盘角 >5° 线性压低纵向上限（解决"头没转正就加速"——4f 实测62%加速在弯道）
  # 独立开关：MacanCornerLimit（BOOL）——UI 启停下方按钮；基于当前上限（限幅后）缩放，直道 factor=1 不变
  try:
    if "MACAN" in (getattr(CP, "carFingerprint", "") or "").upper() and _get_macan_corner_on():
      factor = float(np.clip(1.0 - (abs(angle_steers) - 5.0) / 25.0, _MACAN_CORNER_MIN, 1.0))
      max_accel = min(max_accel, max_accel * factor)
  except Exception:
    pass

  if not e2e:
    a_total_max = np.interp(v_ego, _A_TOTAL_MAX_BP, _A_TOTAL_MAX_V)
    a_y = v_ego ** 2 * angle_steers * CV.DEG_TO_RAD / (CP.steerRatio * CP.wheelbase)
    a_x_allowed = math.sqrt(max(a_total_max ** 2 - a_y ** 2, 0.))
    max_accel = min(max_accel, a_x_allowed)
    if not allow_throttle:
      clipped_accel_coast = max(accel_coast, ACCEL_MIN)
      coast_limit = np.interp(v_ego, [MIN_ALLOW_THROTTLE_SPEED, MIN_ALLOW_THROTTLE_SPEED*2], [max_accel, clipped_accel_coast])
      max_accel = min(max_accel, coast_limit)

  dv = v_cruise - v_ego
  try:
    _macan_coast = "MACAN" in (getattr(CP, "carFingerprint", "") or "").upper()
  except Exception:
    _macan_coast = False
  if _macan_coast:
    # Macan 巡航滑行带：带内滑行(0)，带外 deadband 控制（连续，无死区跳变）
    band = _get_macan_cruise_coast()
    if band > 0.0:
      if dv > band:
        target_accel = np.clip(dv - band, A_CRUISE_MIN, max_accel)
      elif dv < -band:
        target_accel = np.clip(dv + band, A_CRUISE_MIN, max_accel)
      else:
        target_accel = 0.0
    else:  # band<=0：回退原行为
      target_accel = np.clip(dv, A_CRUISE_MIN, max_accel)
  else:
    target_accel = np.clip(dv, A_CRUISE_MIN, max_accel)
  if not e2e:
    j_cruise = np.interp(v_ego, A_CRUISE_MAX_BP, J_CRUISE_VALS)
    target_accel = float(np.clip(target_accel, a_cruise_prev - j_cruise * dt, a_cruise_prev + j_cruise * dt))

  return target_accel


class LongitudinalPlanner(LongitudinalPlannerSP):
  def __init__(self, CP, CP_SP, init_v=0.0, init_a=0.0, dt=DT_MDL):
    self.CP = CP
    self.mpc = LongitudinalMpc(dt=dt)
    LongitudinalPlannerSP.__init__(self, self.CP, CP_SP, self.mpc)
    self.fcw = False
    self.dt = dt
    self.allow_throttle = True

    self.a_desired = init_a
    self.v_desired_filter = FirstOrderFilter(init_v, 2.0, self.dt)
    self.a_cruise = 0.0
    self.output_a_target = 0.0
    self.output_should_stop = False

    self.v_desired_trajectory = np.zeros(CONTROL_N)
    self.a_desired_trajectory = np.zeros(CONTROL_N)
    self.j_desired_trajectory = np.zeros(CONTROL_N)

  def update(self, sm):
    LongitudinalPlannerSP.update(self, sm)

    if len(sm['carControl'].orientationNED) == 3:
      accel_coast = get_coast_accel(sm['carControl'].orientationNED[1])
    else:
      accel_coast = ACCEL_MAX

    v_ego = sm['carState'].vEgo
    v_cruise_kph = min(sm['carState'].vCruise, V_CRUISE_MAX)
    v_cruise = v_cruise_kph * CV.KPH_TO_MS
    if sm['controlsState'].forceDecel:
      v_cruise = 0.0

    long_control_off = sm['controlsState'].longControlState == LongCtrlState.off

    # Reset current state when not engaged, or user is controlling the speed
    reset_state = long_control_off if self.CP.openpilotLongitudinalControl else not sm['selfdriveState'].enabled
    # PCM cruise speed may be updated a few cycles later, check if initialized
    v_cruise_initialized = sm['carState'].vCruise != V_CRUISE_UNSET
    reset_state = reset_state or not v_cruise_initialized

    throttle_probs = sm['modelV2'].meta.disengagePredictions.gasPressProbs
    throttle_prob = throttle_probs[1] if len(throttle_probs) > 1 else 1.0
    self.allow_throttle = throttle_prob > ALLOW_THROTTLE_THRESHOLD or v_ego <= MIN_ALLOW_THROTTLE_SPEED

    steer_angle_without_offset = sm['carState'].steeringAngleDeg - sm['vehicleParameters'].angleOffsetDeg

    if reset_state:
      self.v_desired_filter.x = v_ego
      self.a_desired = np.clip(sm['carState'].aEgo, ACCEL_MIN, ACCEL_MAX)

    # Prevent divergence, smooth in current v_ego
    self.v_desired_filter.x = max(0.0, self.v_desired_filter.update(v_ego))

    # No change cost when user is controlling the speed, or when standstill
    prev_accel_constraint = not (reset_state or sm['carState'].standstill)

    # Get new v_cruise and a_desired from Smart Cruise Control and Speed Limit Assist
    v_cruise, self.a_desired = LongitudinalPlannerSP.update_targets(self, sm, self.v_desired_filter.x, self.a_desired, v_cruise)

    self.mpc.set_weights(prev_accel_constraint, personality=sm['selfdriveState'].personality)
    self.mpc.set_cur_state(self.v_desired_filter.x, self.a_desired)
    self.mpc.update(sm['radarState'], personality=sm['selfdriveState'].personality)

    self.v_desired_trajectory = np.interp(CONTROL_N_T_IDX, T_IDXS_MPC, self.mpc.v_solution)
    self.a_desired_trajectory = np.interp(CONTROL_N_T_IDX, T_IDXS_MPC, self.mpc.a_solution)
    self.j_desired_trajectory = np.interp(CONTROL_N_T_IDX, T_IDXS_MPC[:-1], self.mpc.j_solution)

    # TODO counter is only needed because radar is glitchy, remove once radar is gone
    self.fcw = self.mpc.crash_cnt > 2 and not sm['carState'].standstill
    if self.fcw:
      cloudlog.info("FCW triggered")

    # Save starting point for next iteration
    a_prev = self.a_desired

    action_t =  self.CP.longitudinalActuatorDelay + DT_MDL
    output_a_target_mpc = get_accel_from_plan(self.v_desired_trajectory, self.a_desired_trajectory, CONTROL_N_T_IDX,
                                              action_t=action_t)
    output_should_stop_mpc = should_stop(v_ego, output_a_target_mpc)
    output_a_target_e2e = sm['modelV2'].action.desiredAcceleration
    output_should_stop_e2e = sm['modelV2'].action.shouldStop

    is_e2e = self.is_e2e(sm)

    self.a_cruise = get_cruise_accel(is_e2e, v_cruise, v_ego,
                                     self.a_cruise, steer_angle_without_offset, self.CP, self.dt,
                                     accel_coast, self.allow_throttle)
    cruise_should_stop = should_stop(v_ego, self.a_cruise)

    candidates = [(output_a_target_mpc, self.mpc.source, output_should_stop_mpc),
                  (self.a_cruise, LongitudinalPlanSource.cruise, cruise_should_stop)]
    if is_e2e:
      candidates.append((output_a_target_e2e, LongitudinalPlanSource.e2e, output_should_stop_e2e))

    output_a_target, self.mpc.source, _ = min(candidates, key=lambda c: c[0])
    self.output_should_stop = any(should_stop for _, _, should_stop in candidates)
    self.output_a_target = np.clip(output_a_target, ACCEL_MIN, ACCEL_MAX)
    # Macan aTarget 死区：|aTarget|<dz 归零（滤 MPC 0附近抖动，防 mom 开合喘气；其他车不受影响）
    if "MACAN" in (self.CP.carFingerprint or "").upper():
      dz = _get_macan_deadzone()
      if dz > 0 and abs(self.output_a_target) < dz:
        self.output_a_target = 0.0

    self.a_desired = float(self.output_a_target)
    self.v_desired_filter.x = self.v_desired_filter.x + self.dt * (self.output_a_target + a_prev) / 2.0

  def publish(self, sm, pm):
    plan_send = messaging.new_message('longitudinalPlan')

    plan_send.valid = sm.all_checks()

    longitudinalPlan = plan_send.longitudinalPlan
    longitudinalPlan.modelMonoTime = sm.logMonoTime['modelV2']
    longitudinalPlan.processingDelay = (plan_send.logMonoTime / 1e9) - sm.logMonoTime['modelV2']
    longitudinalPlan.solverExecutionTime = self.mpc.solve_time

    longitudinalPlan.speeds = self.v_desired_trajectory.tolist()
    longitudinalPlan.accels = self.a_desired_trajectory.tolist()
    longitudinalPlan.jerks = self.j_desired_trajectory.tolist()

    longitudinalPlan.hasLead = sm['radarState'].leadOne.present
    longitudinalPlan.longitudinalPlanSource = self.mpc.source
    longitudinalPlan.fcw = self.fcw

    longitudinalPlan.aTarget = float(self.output_a_target)
    longitudinalPlan.shouldStop = bool(self.output_should_stop)
    longitudinalPlan.allowBrake = True
    longitudinalPlan.allowThrottle = bool(self.allow_throttle)

    pm.send('longitudinalPlan', plan_send)

    self.publish_longitudinal_plan_sp(sm, pm)
