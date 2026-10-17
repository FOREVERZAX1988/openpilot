"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
import time

import numpy as np

import openpilot.cereal.messaging as messaging
from openpilot.cereal import log, custom

from opendbc.car import structs
from opendbc.sunnypilot.car.interfaces import get_steer_slew_schedule
from openpilot.common.params import Params
from openpilot.common.realtime import DT_CTRL
from openpilot.common.swaglog import cloudlog
from openpilot.selfdrive.controls.lib.longcontrol import LongCtrlState
from openpilot.sunnypilot import PARAMS_UPDATE_PERIOD
from openpilot.sunnypilot.livedelay.helpers import get_lat_delay
from openpilot.sunnypilot.selfdrive.car.intelligent_cruise_button_management.icbm_latch import icbm_active
from openpilot.sunnypilot.modeld_v2.modeld_base import ModelStateBase
from openpilot.sunnypilot.selfdrive.locationd.speed_bin_learner import LIVE_TORQUE_PARAMETERS_SP_SERVICE
from openpilot.sunnypilot.carrot.carrot_controls import CarrotControls
from openpilot.sunnypilot.selfdrive.controls.controls_lateral_zp import ControlsLateralZP
from openpilot.sunnypilot.selfdrive.controls.lib.blinker_pause_lateral import BlinkerPauseLateral
from openpilot.sunnypilot.selfdrive.controls.lib.lane_change_smoothing import LaneChangeSmoothing
from openpilot.sunnypilot.selfdrive.controls.lib.latcontrol_torque_v0 import LatControlTorque as LatControlTorqueV0
from openpilot.sunnypilot.selfdrive.controls.lib.latcontrol_torque_v2 import LatControlTorque as LatControlTorqueV2
from openpilot.sunnypilot.selfdrive.controls.lib.stopping_controller import StoppingController
from openpilot.sunnypilot.selfdrive.controls.lib.lateral_readiness import LateralStartupGate
from openpilot.sunnypilot.selfdrive.controls.lib.cruise_coasting import CruiseCoastingControl, coasting_relief
from openpilot.sunnypilot.selfdrive.controls.lib.steer_limit import classify
from openpilot.sunnypilot.selfdrive.controls.lib.torque_tune import resolved_tune_versions

# how long lateral control has to be inactive, continuously, before the torque tune follows
# a model change: a one-frame drop (a steer fault flicker) would otherwise swap and resume
# steering on a controller no inactive frame had primed
TUNE_SWAP_INACTIVE_FRAMES = round(0.5 / DT_CTRL)


class ControlsExt(ModelStateBase, ControlsLateralZP):
  def __init__(self, CP: structs.CarParams, params: Params):
    ModelStateBase.__init__(self)
    self.CP = CP
    self.params = params
    self._param_update_time: float = 0.0
    self.blinker_pause_lateral = BlinkerPauseLateral()
    ControlsLateralZP.__init__(self, CP)
    # Carrot lat-suspend lives here so lateral enable has exactly one decision point.
    # It used to be applied in controlsd.py AFTER this arbitration, which gave carrot
    # a second, independent gate on CC.latActive and also meant it kept working with
    # CarrotEnabled off, since nothing consulted that switch.
    self.carrot_controls = CarrotControls(CP)
    # Carrot startup lateral-readiness gate (default off). Blocks lateral enable
    # during the first startup until lateral inputs and CAN transmission are
    # ready. One-way latch: later input failures are owned by runtime safety.
    self.lateral_startup = LateralStartupGate()
    self.lateral_startup_enabled = params.get_bool("CarrotLateralReadinessEnabled")
    # Carrot cruise coasting (default off): brake relief inside the band.
    self._coasting = CruiseCoastingControl()
    self._coasting_relief = coasting_relief
    self._coasting_enabled = params.get_bool("CarrotCruiseCoastingEnabled")

    cloudlog.info("controlsd_ext is waiting for CarParamsSP")
    self.CP_SP = messaging.log_from_bytes(params.get("CarParamsSP", block=True), custom.CarParamsSP)
    cloudlog.info("controlsd_ext got CarParamsSP")

    self.stopping_controller = StoppingController(self.CP.stopAccel) if params.get_bool("SunnypilotStoppingController") else None
    # the stock LongControl.update() has already run by the time long_accel_sp() sees it, so carry the pair it was
    # handed last frame; a fresh LongControl starts at (off, 0.0)
    self._stopping_prev = (LongCtrlState.off, 0.0)

    # carStateSP is needed for pcm_cruise_speed (icbm_latch) and the CarState zoompilot nest;
    # accelerometer is this fork's stop-and-go / slope source
    self.sm_services_ext = ['radarState', 'selfdriveStateSP', 'carStateSP', 'accelerometer', LIVE_TORQUE_PARAMETERS_SP_SERVICE]
    self.pm_services_ext = ['carControlSP']

  @property
  def pcm_cruise_speed(self) -> bool:
    """CarParamsSP.pcmCruiseSpeed as card has it this frame: False while ICBM drives the set speed."""
    return not icbm_active(self.sm['carStateSP'], self.CP_SP)

  def long_accel_sp(self, actuators, CS, long_plan, accel_limits: tuple[float, float]) -> None:
    """sunnypilot: terminal-stop policy applied after the stock LongControl.update() (see stopping_controller.py)."""
    stock_state = self.LoC.long_control_state
    stock_accel = actuators.accel
    prev_state, prev_accel = self._stopping_prev
    self._stopping_prev = (stock_state, stock_accel)

    # Carrot cruise coasting (default off): relax an overspeed brake within the
    # published band. Runs before the stopping controller so a stop policy always
    # has the final say; never adds thrust (relief only eases a negative accel).
    if self._coasting_enabled and long_plan is not None:
      target = float(getattr(long_plan, 'cruiseCoastingTarget', 0.0) or 0.0)
      percent = int(getattr(long_plan, 'cruiseCoastingPercent', 0) or 0)
      relief = self._coasting_relief(CS.vEgo, target, percent) if target > 0.0 else 0.0
      actuators.accel = float(self._coasting.apply(float(actuators.accel), relief, DT_CTRL))
    else:
      self._coasting.reset()

    if self.stopping_controller is None:
      return

    state, accel = self.stopping_controller.update(
      prev_state, stock_state, CS, long_plan.aTarget, prev_accel, stock_accel, accel_limits, long_plan.hasLead,
      pitch=self.calibrated_pose.orientation.pitch if self.calibrated_pose is not None else None,
      a_long=self.calibrated_pose.acceleration.x if self.calibrated_pose is not None else None)
    if state != stock_state:
      self.LoC.reset()
    self.LoC.long_control_state = state
    self.LoC.last_output_accel = accel
    self._stopping_prev = (state, accel)
    actuators.accel = float(accel)

  def get_params_sp(self, sm: messaging.SubMaster) -> None:
    if time.monotonic() - self._param_update_time > PARAMS_UPDATE_PERIOD:
      self.blinker_pause_lateral.get_params()
      self.lane_change_smoothing.get_params()
      self.carrot_controls.update_params()

      if self.CP.lateralTuning.which() == 'torque':
        self.lat_delay = get_lat_delay(self.params, sm["lateralDelay"].lateralDelay)

      self._param_update_time = time.monotonic()

  def _get_lat_active(self, sm: messaging.SubMaster) -> bool:
    # Carrot startup gate (default off): wait for the first readiness
    # confirmation before lateral can engage, including AlwaysLateral.
    if self.lateral_startup_enabled and not self.lateral_startup.update(sm, sm['carState'], 'carState'):
      return False

    if self.blinker_pause_lateral.update(sm['carState']):
      return False

    # Carrot's "driver is steering hard" pause. Same exit point as above, so a single
    # False here disables lateral for every consumer. Gated by CarrotEnabled inside
    # wants_suspend, and LatSuspendAngleDeg defaults to 300 deg - beyond reachable
    # steering angles - so this changes nothing unless the user lowers it.
    if self.carrot_controls.wants_suspend(sm['carState']):
      return False

    ss_sp = sm['selfdriveStateSP']
    if ss_sp.mads.available:
      return bool(ss_sp.mads.active)

    # MADS not available, use stock state to engage
    return bool(sm['selfdriveState'].active)

  def reclassify_steer_limit(self, sm: messaging.SubMaster) -> None:
    """Runs after publish() has set this frame's steer_limited_by_safety from the raw torque
    mismatch. Replaces it with the classifier's directional, rail-aware flag (lib/steer_limit.py)
    before the next frame's LaC.update reads it. Torque tunes only; while lateral is inactive
    (get_lat_active's last value, the one publish() gated on) the flag is left as controlsd set it."""
    ext = getattr(self.LaC, 'extension', None)
    if ext is None or self._steer_slew_schedule is None:
      return
    if not self._lat_active_last:
      self._applied_torque_prev = None
      return
    v_ego = sm['carState'].vEgo
    applied = float(sm['carOutput'].actuatorsOutput.torque)
    bp, up, down = self._steer_slew_schedule
    rail_scale = ext.rail_scale_at(v_ego)
    limit = classify(ext.commanded_torque, applied, self._applied_torque_prev,
                     float(np.interp(v_ego, bp, up)), float(np.interp(v_ego, bp, down)),
                     rail_scale, self.steer_limited_by_safety, ext.last_error, ext.integrator)
    self.steer_limited_by_safety = limit.limited
    ext.set_actuator_state(applied, limit.at_rail)
    self._applied_torque_prev = applied

  def lane_change_jerk_factor(self, sm: messaging.SubMaster, lat_active: bool,
                              new_desired_curvature: float, prev_desired_curvature: float) -> float:
    """Lane-change smoothing's jerk factor for clip_curvature (1.0 outside a smoothed lane
    change). The lateral maneuver mode's scripted commands pass through the stock clip.
    Called once a frame with CC.latActive, which select_lateral_control waits on."""
    self.note_lat_active(lat_active)
    if sm.valid['lateralManeuverPlan']:
      # a lane-change unwind armed before maneuver mode must not resume stale after it
      self.lane_change_smoothing.reset()
      return 1.0
    return self.lane_change_smoothing.update(sm['carState'], sm['modelV2'], lat_active, new_desired_curvature, prev_desired_curvature)

  def note_lat_active(self, lat_active: bool) -> None:
    self._inactive_frames = 0 if lat_active else self._inactive_frames + 1

  @staticmethod
  def get_lead_data(_lead, src: log.RadarState.LeadData) -> None:
    _lead.dRel = src.dRel
    _lead.yRel = src.yRel
    _lead.vRel = src.vRel
    _lead.aRel = src.deprecated.aRel
    _lead.vLead = src.vLead
    _lead.dPath = src.deprecated.dPath
    _lead.vLat = src.deprecated.vLat
    _lead.vLeadK = src.vLeadK
    _lead.aLeadK = src.aLeadK
    _lead.fcw = src.deprecated.fcw
    _lead.present = src.present
    _lead.aLeadTau = src.aLeadTau
    _lead.modelProb = src.modelProb
    _lead.radar = src.radar
    _lead.radarTrackId = src.radarTrackId

  def state_control_ext(self, sm: messaging.SubMaster) -> custom.CarControlSP:
    CC_SP = custom.CarControlSP.new_message()

    self.get_lead_data(CC_SP.leadOne, sm['radarState'].leadOne)
    self.get_lead_data(CC_SP.leadTwo, sm['radarState'].leadTwo)

    # MADS state
    mads_src = sm['selfdriveStateSP'].mads
    CC_SP.mads.state = mads_src.state
    CC_SP.mads.enabled = mads_src.enabled
    CC_SP.mads.active = mads_src.active
    CC_SP.mads.available = mads_src.available
    CC_SP.mads.lateralHeld = mads_src.lateralHeld

    # ICBM state
    icbm_src = sm['selfdriveStateSP'].intelligentCruiseButtonManagement
    CC_SP.intelligentCruiseButtonManagement.state = icbm_src.state
    CC_SP.intelligentCruiseButtonManagement.sendButton = icbm_src.sendButton
    CC_SP.intelligentCruiseButtonManagement.vTarget = icbm_src.vTarget
    CC_SP.zoompilot.icbmHold = sm['selfdriveStateSP'].zoompilot.icbmHold

    # lane-change pace clamp telemetry, for offline validation
    CC_SP.zoompilot.laneChangeSmoothing.jerkFactor = float(self.lane_change_smoothing.jerk_factor)

    # Macan SnG: 传递 planner 原始加速度请求。LoC 在停车保持态（原厂
    # cruise_standstill=True）卡在 stopping 状态，actuators.accel 恒 ≤0
    # （0000004d 实测 5 次长停 aTarget 0.21-0.45 但 accel=0，SnG 判定
    # 永远看不到正信号 → 不代发 RESUME → 不起步）。carcontroller 的
    # SnG 判定需看真实起步意图（aTarget）而非被 LoC 压过的输出。
    try:
      _a_target_param = CC_SP.params.append()
      _a_target_param.key = "aTarget"
      _a_target_param.value = str(sm['longitudinalPlan'].aTarget).encode()
    except Exception:
      pass

    # Macan SnG 视觉源（2026-10-07）：把 modelV2 的**原始**前车（leadsV3[0]）送到
    # carcontroller。SnG 的距离门/前车运动门不能用 CS.op_lead_dRel——那是 radard 融合
    # 后的值，原厂 idx 冻结时会被钉成常数（00000091 seg9 钉在 10.09 m），拿它做门等于
    # 门失效。leadsV3 是雷达坐标系（RADAR_TO_CAMERA=1.52 m 前置），与雷达 dRel/保险杠
    # 口径对齐需减去 1.52。
    #
    # ⚠️ 传参机制（2026-10-07 实测修正）：pycapnp 2.1.0 的 _DynamicListBuilder **没有
    # append()**（只有 adopt/disown/init），`CC_SP.params.append()` 会抛 AttributeError
    # 并被 except 吞掉 → 参数根本出不去。route 00000049 实测 carControlSP.params 恒为 []。
    # 因此这里改为**整表赋值**（capnp 允许对 List 字段整体赋值 dict 列表）。
    # 同因受损的历史通道：aTarget / slopePct（下面两段仍是 append 写法，依旧无效）——
    # 复活它们会改变 ①SnG 触发源（planner aTarget 而非 CC.actuators.accel）②坡度补偿
    # （纯OP 直接用它、融合模式做 IMU 复核），属需单独路试验证的行为变更 → 未夹带本轮，
    # 已登记待办。将来若一并复活，请改为统一收集到一个 list 后一次赋值，勿再用 append。
    try:
      _leads = sm['modelV2'].leadsV3
      if len(_leads) > 0 and float(_leads[0].prob) >= 0.5:
        _vis_x = float(_leads[0].x[0]) - 1.52
        if 0.0 < _vis_x < 150.0:
          CC_SP.params = [
            {"key": "visLeadDist", "value": f"{_vis_x:.2f}".encode()},
            {"key": "visLeadVLead", "value": f"{float(_leads[0].v[0]):.2f}".encode()},
          ]
    except Exception:
      pass

    # Macan IMU 坡度（重力投影，2026-08-18 标定于 00000002/00000049 本机 C3X）：
    # 加速度计含重力分量，车辆前向 n·acc 的静态分量随坡度变化。
    # 坡度% = (n·acc - s_ref)/9.81×100；n=[0.4571,-0.0079,-0.7667]、s_ref≈4.0412m/s²
    # （00000049 回归标定，残差 0.265m/s²）。为将来坡度补偿（mom_calc 坡度项/下坡 verz）
    # 提供实时坡度信号——当前仅传递，不改变任何控制行为（mlbcan 暂不使用）。
    try:
      _acc_v = sm['accelerometer'].acceleration.v
      _slope_pct = (0.4571 * _acc_v[0] - 0.0079 * _acc_v[1] - 0.7667 * _acc_v[2] - 4.0412) / 9.81 * 100
      _slope_param = CC_SP.params.append()
      _slope_param.key = "slopePct"
      _slope_param.value = f"{_slope_pct:.2f}".encode()
    except Exception:
      pass
    return CC_SP

  @staticmethod
  def publish_ext(CC_SP: custom.CarControlSP, sm: messaging.SubMaster, pm: messaging.PubMaster) -> None:
    cc_sp_send = messaging.new_message('carControlSP')
    cc_sp_send.valid = sm['carState'].canValid
    cc_sp_send.carControlSP = CC_SP

    pm.send('carControlSP', cc_sp_send)

  def run_ext(self, sm: messaging.SubMaster, pm: messaging.PubMaster) -> None:
    CC_SP = self.state_control_ext(sm)
    self.publish_ext(CC_SP, sm, pm)
    self.run_lateral_zp(sm)
