"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
from openpilot.selfdrive.ui.sunnypilot.layouts.settings.vehicle.brands.base import BrandSettings
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.multilang import tr, tr_noop
from openpilot.system.ui.widgets import DialogResult
from openpilot.system.ui.widgets.confirm_dialog import ConfirmDialog
from openpilot.system.ui.sunnypilot.widgets.list_view import toggle_item_sp, option_item_sp


DESCRIPTIONS = {
  'jerk_limit': tr_noop(
    'Macan Accel Jerk Limit: limits how fast the acceleration request can '
    'change (m/s^3). Lower = smoother (gentler transitions, less surge); '
    'higher = more responsive. 0 = off (no limit). Decel (braking) is '
    'allowed 2.2x faster for safety. Takes effect within 1s.'
  ),
  'start_stop_distance': tr_noop(
    'Startup Safe Distance (Macan): when ON, auto-resume from a stop requires '
    'the stock radar distance (>0) or vision lead (>5m) - prevents phantom '
    'starts. When OFF, resumes on vision intent alone (V1 behavior) - use in '
    'heavy traffic to keep tight gaps and prevent cut-ins. Only effective '
    'when Stop and Go (Macan) is enabled.'
  ),
  'start_stop': tr_noop(
    'Macan Stop and Go: when enabled, the vision model decides when to start, '
    'and openpilot sends the RESUME signal to release the stock parking hold '
    '(with a chime). When disabled, gently press the gas or SET/RESUME to '
    'resume (stock behavior).'
  ),
  'slope_comp': tr_noop(
    'Macan Slope Compensation: when enabled, the IMU slope signal adds '
    'g*sin(slope) to the acceleration request - more torque uphill, and a '
    'brake tap downhill (prevents forward lurch). Default off = stock '
    'behavior. Onroad cycle restart is requested after toggling.'
  ),
  'slope_comp_unlimited': tr_noop(
    'Macan Slope Comp Unlimited (sub-option): when Slope Compensation is ON, '
    'this removes the stock torque cap (option 2: min(max(stock_mom, 200))), '
    'giving small slopes room to act. When OFF, the stock cap applies '
    '(option 1: min(stock_mom)).'
  ),
  'corner_limit': tr_noop(
    'Macan Corner Accel Limit: when enabled, the steering angle (>5 deg) '
    'linearly reduces the longitudinal acceleration cap (down to 0.3x at '
    '30+ deg) - prevents "accelerating before the wheel is straight". '
    'Field data: 62% of accel events happen with |angle|>8 deg. Takes '
    'effect immediately, no restart needed.'
  ),
  'accel_limit': tr_noop(
    'Macan Accel Limit: clamps the acceleration request magnitude (m/s^2). 0 = factory curve.'
  ),
  'accel_deadzone': tr_noop(
    'Macan Accel Deadzone: zeroes aTarget inside +/- this value to filter MPC jitter (m/s^2). 0 = off.'
  ),
  'accel_deadzone_enable': tr_noop(
    'Macan Accel Deadzone Enable: master switch. Off = deadzone fully disabled (value kept but ignored).'
  ),
  'radar_fusion': tr_noop(
    'Radar Fusion (Macan): uses the stock ACC radar (bus2 distance + lead speed) to correct the vision lead, reduces follow jitter.'
  ),
  'steer_params': tr_noop(
    'Dynamic Steering Ratio (Macan): speed-dependent steering ratio - 15.0 below 140 km/h, '
'18.7 above 145 km/h (linear transition 140-145), fitted from 29,284 samples across '
'the full 4f route (RMSE 1.75 deg), plus torque friction 0.52. When disabled, uses '
'stock fixed 16.2. Replaces the old experimental 18.0 (discarded: 22% gyro spread, '
'15% oversteer in city corners).'
  )
}


class VolkswagenSettings(BrandSettings):
  def __init__(self):
    super().__init__()

    self.start_stop = toggle_item_sp(
      lambda: tr("Stop and Go (Macan)"),
      description=lambda: tr(DESCRIPTIONS["start_stop"]),
      initial_state=ui_state.params.get_bool("MacanStartStop"),
      callback=self._on_enable_start_stop,
      enabled=lambda: not ui_state.engaged,
    )

    self.start_stop_distance = option_item_sp(
      lambda: tr("Startup Safe Distance (Macan)"),
      "MacanStartStopDistance",
      min_value=0, max_value=8,
      description=lambda: tr(DESCRIPTIONS["start_stop_distance"]),
      value_change_step=1,
      value_map={0: 0, 1: 3, 2: 4, 3: 5, 4: 6, 5: 7, 6: 8, 7: 9, 8: 10},  # 显示档→存储米（0=Off, 3~10米每1米）
      label_callback=lambda v: tr("Off") if v == 0 else f"{v} m",  # v 是存储值(3-10)，直接显示米
      enabled=lambda: not ui_state.engaged,
    )
    self.start_stop_distance.set_visible(ui_state.params.get_bool("MacanStartStop"))  # 仅 SnG 开启时可见

    self.jerk_limit_enable = toggle_item_sp(
      lambda: tr("Accel Jerk Limit (Macan)"),
      description=lambda: tr(DESCRIPTIONS["jerk_limit"]),
      initial_state=ui_state.params.get_bool("MacanJerkLimitEnable"),
      callback=self._on_enable_jerk_limit,
      enabled=lambda: not ui_state.engaged,
    )
    self.jerk_limit = option_item_sp(
      lambda: tr("Accel Jerk Limit Value (m/s^3)"),
      "MacanJerkLimit",
      min_value=0, max_value=300,
      description=lambda: tr(DESCRIPTIONS["jerk_limit"]),
      value_change_step=10,
      use_float_scaling=True,
      label_callback=lambda v: tr("Off") if v == 0 else f"{v / 100.0:.1f} m/s^3",
      enabled=lambda: not ui_state.engaged,
    )
    self.jerk_limit.set_visible(ui_state.params.get_bool("MacanJerkLimitEnable"))  # 初始状态按开关参数

    self.corner_limit = toggle_item_sp(
      lambda: tr("Corner Accel Limit (Macan)"),
      description=lambda: tr(DESCRIPTIONS["corner_limit"]),
      initial_state=ui_state.params.get_bool("MacanCornerLimit"),
      callback=self._on_enable_corner_limit,
      enabled=lambda: not ui_state.engaged,
    )

    self.slope_comp = toggle_item_sp(
      lambda: tr("Slope Compensation (Macan)"),
      description=lambda: tr(DESCRIPTIONS["slope_comp"]),
      initial_state=ui_state.params.get_bool("MacanSlopeComp"),
      callback=self._on_enable_slope_comp,
      enabled=lambda: not ui_state.engaged,
    )

    self.slope_comp_unlimited = toggle_item_sp(
      lambda: tr("Slope Comp Unlimited (Macan)"),
      description=lambda: tr(DESCRIPTIONS["slope_comp_unlimited"]),
      initial_state=ui_state.params.get_bool("MacanSlopeCompUnlimited"),
      callback=self._on_enable_slope_comp_unlimited,
      enabled=lambda: not ui_state.engaged,
    )

    self.steer_params = toggle_item_sp(
      lambda: tr("Dynamic Steering Ratio (Macan)"),
      description=lambda: tr(DESCRIPTIONS["steer_params"]),
      initial_state=ui_state.params.get_bool("MacanSteerParams"),
      callback=self._on_enable_steer_params,
      enabled=lambda: not ui_state.engaged,
    )

    self.accel_limit = option_item_sp(
      lambda: tr("Macan Accel Limit (m/s^2)"),
      "MacanAccelLimit",
      min_value=0, max_value=200,
      description=lambda: tr(DESCRIPTIONS["accel_limit"]),
      value_change_step=10,
      use_float_scaling=True,
      label_callback=lambda v: tr("Off") if v == 0 else f"{v / 100.0:.1f} m/s^2",
      enabled=lambda: not ui_state.engaged,
    )

    self.accel_deadzone_enable = toggle_item_sp(
      lambda: tr("Macan Accel Deadzone Enable"),
      description=lambda: tr(DESCRIPTIONS["accel_deadzone_enable"]),
      initial_state=ui_state.params.get_bool("MacanAccelDeadzoneEnable"),
      callback=self._on_enable_accel_deadzone,
      enabled=lambda: not ui_state.engaged,
    )

    self.accel_deadzone = option_item_sp(
      lambda: tr("Macan Accel Deadzone (m/s^2)"),
      "MacanAccelDeadzone",
      min_value=0, max_value=20,
      description=lambda: tr(DESCRIPTIONS["accel_deadzone"]),
      value_change_step=5,
      use_float_scaling=True,
      label_callback=lambda v: tr("Off") if v == 0 else f"{v / 100.0:.2f} m/s^2",
      enabled=lambda: not ui_state.engaged,
    )
    self.accel_deadzone.set_visible(ui_state.params.get_bool("MacanAccelDeadzoneEnable"))  # 初始状态按开关参数

    self.radar_fusion = toggle_item_sp(
      lambda: tr("Radar Fusion (Macan)"),
      description=lambda: tr(DESCRIPTIONS["radar_fusion"]),
      initial_state=ui_state.params.get_bool("MacanRadarFusion"),
      callback=self._on_enable_radar_fusion,
      enabled=lambda: not ui_state.engaged,
    )

    self.items = [
      self.start_stop,
      self.start_stop_distance,
      self.jerk_limit_enable,
      self.jerk_limit,
      self.corner_limit,
      self.slope_comp,
      self.slope_comp_unlimited,
      self.steer_params,
      self.accel_limit,
      self.accel_deadzone_enable,
      self.accel_deadzone,
      self.radar_fusion,
    ]

  def _on_enable_jerk_limit(self, state: bool):
    ui_state.params.put_bool("MacanJerkLimitEnable", state)
    self.jerk_limit.set_visible(state)  # 立即显示/隐藏数值项（显式布尔，不触发 UI 重载）
    # 注：不 put 清值——longcontrol 代码层已有 Enable 兜底（关→强制不生效），
    # 且 put FLOAT 参数会触发 UI 重载（2026-08-21 实测）

  def _on_enable_accel_deadzone(self, state: bool):
    ui_state.params.put_bool("MacanAccelDeadzoneEnable", state)
    self.accel_deadzone.set_visible(state)  # 立即显示/隐藏数值项

  def _on_enable_radar_fusion(self, state: bool):
    ui_state.params.put_bool("MacanRadarFusion", state)

  def _on_enable_start_stop(self, state: bool):
    if state:
      def confirm_callback(result: int):
        if result == DialogResult.CONFIRM:
          ui_state.params.put_bool("MacanStartStop", True)
          ui_state.params.put_bool("OnroadCycleRequested", True)
          self.start_stop_distance.set_visible(True)  # SnG 开 → 显示距离子开关
        else:
          self.start_stop.action_item.set_state(False)

      content = (f"<h1>{self.start_stop.title}</h1><br>" +
                 f"<p>{self.start_stop.description}</p>")

      dlg = ConfirmDialog(content, tr("Enable"), rich=True, callback=confirm_callback)
      gui_app.push_widget(dlg)

    else:
      ui_state.params.put_bool("MacanStartStop", False)
      ui_state.params.put_bool("OnroadCycleRequested", True)
      self.start_stop_distance.set_visible(False)  # SnG 关 → 隐藏距离子开关

  def _on_enable_corner_limit(self, state: bool):
    # planner 每 1s 刷新参数，即时生效，无需 onroad cycle 重启
    ui_state.params.put_bool("MacanCornerLimit", state)

  def _on_enable_slope_comp(self, state: bool):
    ui_state.params.put_bool("MacanSlopeComp", state)
    if not state:
      ui_state.params.put_bool("MacanSlopeCompUnlimited", False)
      self.slope_comp_unlimited.action_item.set_state(False)
    ui_state.params.put_bool("OnroadCycleRequested", True)

  def _on_enable_slope_comp_unlimited(self, state: bool):
    ui_state.params.put_bool("MacanSlopeCompUnlimited", state)
    ui_state.params.put_bool("OnroadCycleRequested", True)

  def _on_enable_steer_params(self, state: bool):
    ui_state.params.put_bool("MacanSteerParams", state)
    ui_state.params.put_bool("OnroadCycleRequested", True)

  def update_settings(self):
    if ui_state.CP is not None:
      # 仅 Macan(MLB) 支持；其他 VW 平台隐藏开关
      is_macan = ui_state.CP.carFingerprint == "PORSCHE_MACAN_MK1"
      slope_comp_on = ui_state.params.get_bool("MacanSlopeComp")
      start_stop_on = ui_state.params.get_bool("MacanStartStop")
      self.start_stop.action_item.set_enabled(is_macan and not ui_state.engaged)
      self.start_stop.set_visible(is_macan)
      self.start_stop_distance.action_item.set_enabled(is_macan and not ui_state.engaged and start_stop_on)
      self.start_stop_distance.set_visible(is_macan and start_stop_on)
      self.jerk_limit_enable.action_item.set_enabled(is_macan and not ui_state.engaged)
      self.jerk_limit_enable.set_visible(is_macan)
      jerk_limit_on = ui_state.params.get_bool("MacanJerkLimitEnable")
      self.jerk_limit.action_item.set_enabled(is_macan and not ui_state.engaged and jerk_limit_on)
      self.jerk_limit.set_visible(is_macan and jerk_limit_on)
      self.corner_limit.action_item.set_enabled(is_macan and not ui_state.engaged)
      self.corner_limit.set_visible(is_macan)
      self.slope_comp.action_item.set_enabled(is_macan and not ui_state.engaged)
      self.slope_comp.set_visible(is_macan)
      # 子选项（放开限制）：仅坡度补偿开启时显示（联动，整行隐藏）
      self.slope_comp_unlimited.action_item.set_enabled(is_macan and not ui_state.engaged and slope_comp_on)
      self.slope_comp_unlimited.set_visible(is_macan and slope_comp_on)
      self.steer_params.action_item.set_enabled(is_macan and not ui_state.engaged)
      self.steer_params.set_visible(is_macan)
      self.accel_limit.action_item.set_enabled(is_macan and not ui_state.engaged)
      self.accel_limit.set_visible(is_macan)
      self.accel_deadzone_enable.action_item.set_enabled(is_macan and not ui_state.engaged)
      self.accel_deadzone_enable.set_visible(is_macan)
      deadzone_on = ui_state.params.get_bool("MacanAccelDeadzoneEnable")
      self.accel_deadzone.action_item.set_enabled(is_macan and not ui_state.engaged and deadzone_on)
      self.accel_deadzone.set_visible(is_macan and deadzone_on)
      self.radar_fusion.action_item.set_enabled(is_macan and not ui_state.engaged)
      self.radar_fusion.set_visible(is_macan)
