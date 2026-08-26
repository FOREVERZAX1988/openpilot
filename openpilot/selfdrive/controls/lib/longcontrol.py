import time
import numpy as np
from opendbc.car.structs import car
from openpilot.common.params import Params
from openpilot.common.realtime import DT_CTRL
from openpilot.selfdrive.controls.lib.drive_helpers import CONTROL_N
from openpilot.common.pid import PIDController
from openpilot.selfdrive.modeld.constants import ModelConstants

CONTROL_N_T_IDX = ModelConstants.T_IDXS[:CONTROL_N]

# Macan 减猛：accel 变化率限幅（MacanJerkLimit 参数，m/s³；0=关闭，默认关）
# 依据（0051 vs 原厂 02/04/05）：OP aEgo 波动幅度 0.48 vs 原厂 0.31-0.35——
# 链路 aTarget→longcontrol(feedforward 直通，无变化率限制)→accel→力矩→aEgo，
# MPC relaxed 已全档平滑（a_change=200）但距离误差主导时 aTarget 仍 ±1.2 快速翻转。
# 正向 jerk 限幅削过冲；负向（减速）放宽 2.2 倍，安全优先。
_macan_jerk_limit = 0.0
_macan_jerk_limit_t = 0.0
_MACAN_JERK_NEG_FACTOR = 2.2
_MACAN_JERK_SNG_EXEMPT_SPEED = 3.0  # m/s≈10.8km/h；SnG 起步豁免阈值（0060 vs 005f 实证）
def _get_macan_jerk_limit():
  global _macan_jerk_limit, _macan_jerk_limit_t
  now = time.monotonic()
  if now - _macan_jerk_limit_t > 1.0:  # 每1秒刷新（不阻塞）
    try:
      _macan_jerk_limit = float(Params().get("MacanJerkLimit") or 0.0) if Params().get_bool("MacanJerkLimitEnable") else 0.0  # 总开关关闭时强制不生效
    except Exception:
      _macan_jerk_limit = 0.0
    _macan_jerk_limit_t = now
  return _macan_jerk_limit

LongCtrlState = car.CarControl.Actuators.LongControlState


def long_control_state_trans(CP_SP, active, long_control_state,
                             should_stop, brake_pressed, cruise_standstill):
  # Gas Interceptor
  cruise_standstill = cruise_standstill and not CP_SP.enableGasInterceptor

  starting_condition = (not should_stop and
                        not cruise_standstill and
                        not brake_pressed)

  if not active:
    long_control_state = LongCtrlState.off

  else:
    if long_control_state == LongCtrlState.off:
      if not starting_condition:
        long_control_state = LongCtrlState.stopping
      else:
        long_control_state = LongCtrlState.pid

    elif long_control_state == LongCtrlState.stopping:
      if starting_condition:
        long_control_state = LongCtrlState.pid

    elif long_control_state == LongCtrlState.pid:
      if should_stop:
        long_control_state = LongCtrlState.stopping

  return long_control_state

class LongControl:
  def __init__(self, CP, CP_SP):
    self.CP = CP
    self.CP_SP = CP_SP
    self.long_control_state = LongCtrlState.off
    self.pid = PIDController(0.0, (CP.longitudinalTuning.kiBP, CP.longitudinalTuning.kiV),
                             rate=1 / DT_CTRL)
    self.last_output_accel = 0.0

  def reset(self):
    self.pid.reset()

  def update(self, active, CS, a_target, should_stop, accel_limits):
    """Update longitudinal control. This updates the state machine and runs a PID loop"""
    self.pid.neg_limit = accel_limits[0]
    self.pid.pos_limit = accel_limits[1]

    self.long_control_state = long_control_state_trans(self.CP_SP, active, self.long_control_state,
                                                       should_stop, CS.brakePressed,
                                                       CS.cruiseState.standstill)
    if self.long_control_state == LongCtrlState.off:
      self.reset()
      output_accel = 0.

    elif self.long_control_state == LongCtrlState.stopping:
      output_accel = self.last_output_accel
      if output_accel > self.CP.stopAccel:
        output_accel = min(output_accel, 0.0)
        # TODO: can we just go straight to stopAccel?
        output_accel -= 1.0 * DT_CTRL  # m/s^2/s while trying to stop
      self.reset()

    else:  # LongCtrlState.pid
      error = a_target - CS.aEgo
      output_accel = self.pid.update(error, speed=CS.vEgo,
                                     feedforward=a_target)

    # Macan 减猛（MacanJerkLimit>0 时）：accel 变化率限幅——削 aTarget 过冲透传，
    # 正 jerk 限 lim，负 jerk（减速）限 2.2×lim（安全优先）。0=关闭（默认）。
    jerk_lim = _get_macan_jerk_limit()
    # SnG 起步豁免（2026-08-26 实证，0060 vs 005f）：pid 状态且 vEgo<3m/s 的起步阶段
    # 不限幅——否则 jerk=0.2 时 accel 从 -0.55 爬到正值需 ~5s，车 3s 没动，
    # MPC shouldStop 判定起步失败撤回（0060 345-365s 起步失败）；豁免后 accel
    # 即时转正、车 ~1s 内起步（005f seg4/seg10 正常起步行为）。行驶中减猛不受影响。
    _sng_exempt = (self.long_control_state == LongCtrlState.pid and CS.vEgo < _MACAN_JERK_SNG_EXEMPT_SPEED)
    if jerk_lim > 0.0 and not _sng_exempt:
      _delta = output_accel - self.last_output_accel
      _max_d = jerk_lim * DT_CTRL
      _max_dn = jerk_lim * _MACAN_JERK_NEG_FACTOR * DT_CTRL
      output_accel = self.last_output_accel + float(np.clip(_delta, -_max_dn, _max_d))
    self.last_output_accel = np.clip(output_accel, accel_limits[0], accel_limits[1])
    return self.last_output_accel
