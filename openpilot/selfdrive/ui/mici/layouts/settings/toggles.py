from collections.abc import Callable

from openpilot.cereal import log

from openpilot.system.ui.widgets.scroller import NavScroller
from openpilot.selfdrive.ui.mici.widgets.button import BigParamControl, BigMultiParamToggle, BigMultiToggle, BigToggle, GreyBigButton
from openpilot.selfdrive.ui.mici.widgets.dialog import BigConfirmationCircleButton
from openpilot.system.ui.lib.application import gui_app
from openpilot.selfdrive.ui.layouts.settings.common import restart_needed_callback
from openpilot.common.params import Params
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.multilang import tr

PERSONALITY_TO_INT = log.LongitudinalPersonality.schema.enumerants


class MacanJerkControl(BigMultiToggle):
  """Macan 加速度变化率限制（m/s^3）：点击循环切换预设值，0=关闭（存储选项值本身）"""
  OPTIONS = ["0", "1.5", "2.5"]  # 三档：0=关 / 1.5标准 / 2.5激进（2026-08-22 用户要求三格）

  def __init__(self, text: str, param: str):
    super().__init__(text, self.OPTIONS)
    self._param = param
    self._params = Params()  # 对齐驾驶风格(BigMultiParamToggle)：独立实例，避免 ui_state 单例竞争
    self._load()

  def _load(self):
    cur = self._params.get(self._param)
    # get() 按参数类型返回 float/int，OPTIONS 是 str → str(cur) 转换比较（2026-08-22 实锤：
    # 类型不匹配会永远 idx=0 显示第一档，即"内容不变"）
    idx = self.OPTIONS.index(str(cur)) if str(cur) in self.OPTIONS else 0
    self.set_value(self.OPTIONS[idx])

  def _handle_mouse_release(self, mouse_pos):
    super()._handle_mouse_release(mouse_pos)
    self._params.put(self._param, float(self.value), block=True)  # FLOAT 参数需 float（str 会 TypeError 崩 UI）


class MacanAccelLimitControl(BigMultiToggle):
  # 2026-08-22 用户反馈：档位太多点击会重启 UI 不跳数值 → 改三档
  OPTIONS = ["1.0", "1.2", "1.6"]

  def __init__(self, text: str, param: str):
    super().__init__(text, self.OPTIONS)
    self._param = param
    self._params = Params()  # 对齐驾驶风格(BigMultiParamToggle)：独立实例，避免 ui_state 单例竞争
    self._load()

  def _load(self):
    cur = self._params.get(self._param)
    # get() 按参数类型返回 float/int，OPTIONS 是 str → str(cur) 转换比较（2026-08-22 实锤：
    # 类型不匹配会永远 idx=0 显示第一档，即"内容不变"）
    idx = self.OPTIONS.index(str(cur)) if str(cur) in self.OPTIONS else 0
    self.set_value(self.OPTIONS[idx])

  def _handle_mouse_release(self, mouse_pos):
    super()._handle_mouse_release(mouse_pos)
    self._params.put(self._param, float(self.value), block=True)  # FLOAT 参数需 float（str 会 TypeError 崩 UI）


class MacanStartStopDistControl(BigMultiToggle):
  """Macan 起步安全距离（米）：3/5/10 三档（tizi 为 0/3-10 每1米，mici 简化三档）"""
  OPTIONS = ["3", "5", "10"]

  def __init__(self, text: str, param: str):
    super().__init__(text, self.OPTIONS)
    self._param = param
    self._params = Params()  # 对齐驾驶风格(BigMultiParamToggle)：独立实例，避免 ui_state 单例竞争
    self._load()

  def _load(self):
    cur = self._params.get(self._param)
    # get() 按参数类型返回 float/int，OPTIONS 是 str → str(cur) 转换比较（2026-08-22 实锤：
    # 类型不匹配会永远 idx=0 显示第一档，即"内容不变"）
    idx = self.OPTIONS.index(str(cur)) if str(cur) in self.OPTIONS else 1
    self.set_value(self.OPTIONS[idx])

  def _handle_mouse_release(self, mouse_pos):
    super()._handle_mouse_release(mouse_pos)
    self._params.put(self._param, int(self.value), block=True)  # INT 参数需 int（str 会 TypeError 崩 UI）


class MacanAccelDeadzoneControl(BigMultiToggle):
  OPTIONS = ["0", "0.05", "0.1", "0.15", "0.2"]

  def __init__(self, text: str, param: str):
    super().__init__(text, self.OPTIONS)
    self._param = param
    self._params = Params()  # 对齐驾驶风格(BigMultiParamToggle)：独立实例，避免 ui_state 单例竞争
    self._load()

  def _load(self):
    cur = self._params.get(self._param)
    # get() 按参数类型返回 float/int，OPTIONS 是 str → str(cur) 转换比较（2026-08-22 实锤：
    # 类型不匹配会永远 idx=0 显示第一档，即"内容不变"）
    idx = self.OPTIONS.index(str(cur)) if str(cur) in self.OPTIONS else 0
    self.set_value(self.OPTIONS[idx])

  def _handle_mouse_release(self, mouse_pos):
    super()._handle_mouse_release(mouse_pos)
    self._params.put(self._param, float(self.value), block=True)  # FLOAT 参数需 float（str 会 TypeError 崩 UI）


class MacanSteerAllowanceControl(BigMultiToggle):
  """Macan 干预灵敏度（cNm）：0=仅零偏补偿(不动ALLOWANCE)/60/80 三档。仅零偏补偿开关开启时生效。"""
  OPTIONS = ["0", "60", "80"]

  def __init__(self, text: str, param: str):
    super().__init__(text, self.OPTIONS)
    self._param = param
    self._params = Params()
    self._load()

  def _load(self):
    cur = self._params.get(self._param)
    idx = self.OPTIONS.index(str(cur)) if str(cur) in self.OPTIONS else 0
    self.set_value(self.OPTIONS[idx])

  def _handle_mouse_release(self, mouse_pos):
    super()._handle_mouse_release(mouse_pos)
    self._params.put(self._param, int(self.value), block=True)  # INT 参数需 int


class ExperimentalModeConfirmPage(NavScroller):
  def __init__(self, on_confirm: Callable[[], None]):
    super().__init__()

    accept = BigConfirmationCircleButton(tr("enable\nexperimental mode"),
                                         gui_app.texture("icons_mici/setup/driver_monitoring/dm_check.png", 64, 64),
                                         lambda: self.dismiss(on_confirm))

    self._scroller.add_widgets([
      GreyBigButton(tr("enabling\nexperimental mode"), "scroll to continue",
                    gui_app.texture("icons_mici/setup/warning.png", 64, 64)),
      GreyBigButton("", tr("openpilot defaults to driving in chill mode.")),
      GreyBigButton("", tr("Experimental mode enables alpha-level features that aren't ready for chill mode.")),
      GreyBigButton(tr("End-to-End Longitudinal Control")),
      GreyBigButton("", tr("Let the driving model control the gas and brakes.")),
      GreyBigButton("", tr("openpilot will drive as it thinks a human would, including stopping for red lights and stop signs.")),
      GreyBigButton("", tr("The set speed will only act as an upper bound.")),
      GreyBigButton("", tr("This is an alpha quality feature; mistakes should be expected.")),
      GreyBigButton(tr("New Driving Visualization")),
      GreyBigButton("", tr("The path will change colors to communicate acceleration intent.")),
      GreyBigButton("", tr("Red for braking, green for acceleration, and gray for coasting.")),
      accept,
    ])


class TogglesLayoutMici(NavScroller):
  def __init__(self):
    super().__init__()

    self._personality_toggle = BigMultiParamToggle(tr("driving personality"), "LongitudinalPersonality", ["aggressive", "standard", "relaxed"])
    self._experimental_btn = BigToggle(tr("experimental mode"), initial_state=ui_state.params.get_bool("ExperimentalMode"),
                                       toggle_callback=self._on_experimental_mode)
    is_metric_toggle = BigParamControl(tr("use metric units"), "IsMetric")
    ldw_toggle = BigParamControl(tr("lane departure warnings"), "IsLdwEnabled")
    always_on_dm_toggle = BigParamControl(tr("always-on driver monitor"), "AlwaysOnDM")
    distraction_level_toggle = BigMultiParamToggle(
      tr("distraction detection level"),
      "DistractionDetectionLevel",
      ["strict", "moderate", "lenient"],
    )
    record_front = BigParamControl(tr("record & upload driver camera"), "RecordFront", toggle_callback=restart_needed_callback)
    record_mic = BigParamControl(tr("record & upload mic audio"), "RecordAudio", toggle_callback=restart_needed_callback)
    enable_openpilot = BigParamControl(tr("enable sunnypilot"), "OpenpilotEnabledToggle", toggle_callback=restart_needed_callback)
    macan_start_stop = BigParamControl(tr("Macan Stop and Go"), "MacanStartStop")
    macan_start_stop_distance = MacanStartStopDistControl(tr("Startup Safe Distance (Macan)"), "MacanStartStopDistance")
    macan_jerk_enable = BigParamControl(tr("Macan Accel Jerk Limit"), "MacanJerkLimitEnable")
    macan_jerk_limit = MacanJerkControl(tr("Accel Jerk Limit Value (m/s^3)"), "MacanJerkLimit")
    macan_corner_limit = BigParamControl(tr("Macan Corner Accel Limit"), "MacanCornerLimit")
    macan_slope_comp = BigParamControl(tr("Macan Slope Compensation"), "MacanSlopeComp")
    macan_slope_comp_unlimited = BigParamControl(tr("Macan Slope Comp Unlimited"), "MacanSlopeCompUnlimited")
    macan_steer_params = BigParamControl(tr("Macan Dynamic Steering Ratio"), "MacanSteerParams")
    macan_accel_limit = MacanAccelLimitControl(tr("Macan Accel Limit (m/s^2)"), "MacanAccelLimit")
    macan_accel_deadzone = MacanAccelDeadzoneControl(tr("Macan Accel Deadzone (m/s^2)"), "MacanAccelDeadzone")
    macan_deadzone_enable = BigParamControl(tr("Macan Accel Deadzone Enable"), "MacanAccelDeadzoneEnable")
    macan_radar_fusion = BigParamControl(tr("Radar Fusion (Macan)"), "MacanRadarFusion")
    macan_startup_gap_sync = BigParamControl(tr("Macan Distance Sync Direction"), "MacanStartupGapSync")
    macan_steer_bias = BigParamControl(tr("Macan Steering Bias Compensation"), "MacanSteerBiasComp")
    macan_steer_allowance = MacanSteerAllowanceControl(tr("Macan Intervention Sensitivity (cNm)"), "MacanSteerAllowance")

    self._scroller.add_widgets([
      self._personality_toggle,
      self._experimental_btn,
      is_metric_toggle,
      ldw_toggle,
      always_on_dm_toggle,
      distraction_level_toggle,
      record_front,
      record_mic,
      enable_openpilot,
      macan_start_stop,
      macan_start_stop_distance,
      macan_jerk_enable,
      macan_jerk_limit,
      macan_corner_limit,
      macan_slope_comp,
      macan_slope_comp_unlimited,
      macan_steer_params,
      macan_accel_limit,
      macan_deadzone_enable,
      macan_accel_deadzone,
      macan_radar_fusion,
      macan_startup_gap_sync,
      macan_steer_bias,
      macan_steer_allowance,
    ])

    self._macan_start_stop = macan_start_stop
    self._macan_start_stop_distance = macan_start_stop_distance
    self._macan_jerk_enable = macan_jerk_enable
    self._macan_jerk_limit = macan_jerk_limit
    self._macan_corner_limit = macan_corner_limit
    self._macan_slope_comp = macan_slope_comp
    self._macan_slope_comp_unlimited = macan_slope_comp_unlimited
    self._macan_steer_params = macan_steer_params
    self._macan_accel_limit = macan_accel_limit
    self._macan_accel_deadzone = macan_accel_deadzone
    self._macan_deadzone_enable = macan_deadzone_enable
    self._macan_radar_fusion = macan_radar_fusion
    self._macan_startup_gap_sync = macan_startup_gap_sync
    self._macan_steer_bias = macan_steer_bias
    self._macan_steer_allowance = macan_steer_allowance
    self._always_on_dm_toggle = always_on_dm_toggle
    self._distraction_level_toggle = distraction_level_toggle

    # Toggle lists
    self._refresh_toggles = (
      ("ExperimentalMode", self._experimental_btn),
      ("IsMetric", is_metric_toggle),
      ("IsLdwEnabled", ldw_toggle),
      ("AlwaysOnDM", always_on_dm_toggle),
      ("RecordFront", record_front),
      ("MacanStartStop", macan_start_stop),
      ("MacanStartStopDistance", macan_start_stop_distance),
      ("MacanJerkLimitEnable", macan_jerk_enable),
      ("MacanCornerLimit", macan_corner_limit),
      ("MacanSlopeComp", macan_slope_comp),
      ("MacanSlopeCompUnlimited", macan_slope_comp_unlimited),
      ("MacanSteerParams", macan_steer_params),
      ("MacanAccelLimit", macan_accel_limit),
      ("MacanAccelDeadzone", macan_accel_deadzone),
      ("MacanAccelDeadzoneEnable", macan_deadzone_enable),
      ("MacanRadarFusion", macan_radar_fusion),
      ("MacanStartupGapSync", macan_startup_gap_sync),
      ("MacanSteerBiasComp", macan_steer_bias),
      ("MacanSteerAllowance", macan_steer_allowance),
      ("RecordAudio", record_mic),
      ("OpenpilotEnabledToggle", enable_openpilot),
    )

    enable_openpilot.set_enabled(lambda: not ui_state.engaged)
    macan_steer_allowance.set_visible(lambda: ui_state.params.get_bool("MacanSteerBiasComp"))
    macan_start_stop_distance.set_enabled(lambda: not ui_state.engaged)
    macan_slope_comp.set_enabled(lambda: not ui_state.engaged)
    macan_slope_comp_unlimited.set_enabled(lambda: not ui_state.engaged)
    macan_steer_params.set_enabled(lambda: not ui_state.engaged)
    record_front.set_enabled(False if ui_state.params.get_bool("RecordFrontLock") else (lambda: not ui_state.engaged))
    record_mic.set_enabled(lambda: not ui_state.engaged)

    if ui_state.params.get_bool("ShowDebugInfo"):
      gui_app.set_show_touches(True)
      gui_app.set_show_fps(True)

    ui_state.add_engaged_transition_callback(self._update_toggles)

  def _update_state(self):
    super()._update_state()

    if ui_state.sm.updated["selfdriveState"]:
      personality = PERSONALITY_TO_INT[ui_state.sm["selfdriveState"].personality]
      if personality != ui_state.personality and ui_state.started:
        self._personality_toggle.set_value(self._personality_toggle._options[personality])
      ui_state.personality = personality

  def show_event(self):
    super().show_event()
    self._update_toggles()

  def _update_toggles(self):
    ui_state.update_params()

    # CP gating for experimental mode
    if ui_state.CP is not None:
      if ui_state.has_longitudinal_control:
        self._experimental_btn.set_visible(True)
        self._personality_toggle.set_visible(True)
      else:
        # no long for now
        self._experimental_btn.set_visible(False)
        self._experimental_btn.set_checked(False)
        self._personality_toggle.set_visible(False)
        ui_state.params.remove("ExperimentalMode")

    # Macan Stop and Go / Slope Comp / Steering Params: only shown for Macan (MLB)
    if ui_state.CP is not None and ui_state.CP.carFingerprint == "PORSCHE_MACAN_MK1":
      slope_comp_on = ui_state.params.get_bool("MacanSlopeComp")
      self._macan_start_stop.set_visible(True)
      # 起步安全距离：仅 SnG 开关开启时显示（联动）
      self._macan_start_stop_distance.set_visible(ui_state.params.get_bool("MacanStartStop"))
      self._macan_jerk_enable.set_visible(True)
      self._macan_jerk_limit.set_visible(ui_state.params.get_bool("MacanJerkLimitEnable"))
      self._macan_slope_comp.set_visible(True)
      self._macan_slope_comp_unlimited.set_visible(slope_comp_on)
      self._macan_steer_params.set_visible(True)
      self._macan_accel_limit.set_visible(True)
      self._macan_deadzone_enable.set_visible(True)
      self._macan_accel_deadzone.set_visible(ui_state.params.get_bool("MacanAccelDeadzoneEnable"))
      self._macan_radar_fusion.set_visible(True)
    else:
      self._macan_start_stop.set_visible(False)
      self._macan_jerk_enable.set_visible(False)
      self._macan_jerk_limit.set_visible(False)
      self._macan_slope_comp.set_visible(False)
      self._macan_slope_comp_unlimited.set_visible(False)
      self._macan_steer_params.set_visible(False)
      self._macan_accel_limit.set_visible(False)
      self._macan_deadzone_enable.set_visible(False)
      self._macan_accel_deadzone.set_visible(False)
      self._macan_radar_fusion.set_visible(False)

    # Refresh toggles from params to mirror external changes
    for key, item in self._refresh_toggles:
      item.set_checked(ui_state.params.get_bool(key))

    dm_on = ui_state.params.get_bool("AlwaysOnDM")
    self._distraction_level_toggle.set_visible(dm_on)
    if dm_on:
      self._distraction_level_toggle._load_value()

  def _on_experimental_mode(self, state: bool):
    if state and not ui_state.params.get_bool("ExperimentalModeConfirmed"):
      # Don't show enabled state until confirm
      self._experimental_btn.set_checked(False)

      def on_confirm():
        ui_state.params.put_bool("ExperimentalModeConfirmed", True)
        ui_state.params.put_bool("ExperimentalMode", True)
        self._experimental_btn.set_checked(True)

      gui_app.push_widget(ExperimentalModeConfirmPage(on_confirm))
    else:
      ui_state.params.put_bool("ExperimentalMode", state)
