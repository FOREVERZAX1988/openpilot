import math
import numpy as np

from opendbc.car.structs import car
from openpilot.common.constants import CV
from openpilot.sunnypilot.selfdrive.car.cruise_ext import VCruiseHelperSP


# WARNING: this value was determined based on the model's training distribution,
#          model predictions above this speed can be unpredictable
# V_CRUISE's are in kph
V_CRUISE_MIN = 8
V_CRUISE_MAX = 145
V_CRUISE_UNSET = 255
V_CRUISE_INITIAL = 30
V_CRUISE_INITIAL_EXPERIMENTAL_MODE = 30
IMPERIAL_INCREMENT = round(CV.MPH_TO_KPH, 1)  # round here to avoid rounding errors incrementing set speed

ButtonEvent = car.CarState.ButtonEvent
ButtonType = car.CarState.ButtonEvent.Type
CRUISE_LONG_PRESS = 50
CRUISE_NEAREST_FUNC = {
  ButtonType.accelCruise: math.ceil,
  ButtonType.decelCruise: math.floor,
}
CRUISE_INTERVAL_SIGN = {
  ButtonType.accelCruise: +1,
  ButtonType.decelCruise: -1,
}


class VCruiseHelper(VCruiseHelperSP):
  def __init__(self, CP, CP_SP):
    VCruiseHelperSP.__init__(self, CP, CP_SP)
    self.CP = CP
    self.v_cruise_kph = V_CRUISE_UNSET
    self.v_cruise_cluster_kph = V_CRUISE_UNSET
    self.v_cruise_kph_last = 0
    self.button_timers = {ButtonType.decelCruise: 0, ButtonType.accelCruise: 0, ButtonType.setCruise: 0}
    self.button_change_states = {btn: {"standstill": False, "enabled": False} for btn in self.button_timers}

  @property
  def v_cruise_initialized(self):
    return self.v_cruise_kph != V_CRUISE_UNSET

  def update_v_cruise(self, CS, enabled, is_metric):
    self.v_cruise_kph_last = self.v_cruise_kph

    self.get_minimum_set_speed(is_metric)

    _enabled = self.update_enabled_state(CS, enabled)

    if CS.cruiseState.available:
      if not self.CP.pcmCruise or (not self.CP_SP.pcmCruiseSpeed and _enabled):
        # if stock cruise is completely disabled, then we can use our own set speed logic
        self._update_v_cruise_non_pcm(CS, _enabled, is_metric)
        self.update_speed_limit_assist_v_cruise_non_pcm()
        self.v_cruise_cluster_kph = self.v_cruise_kph
      else:
        self.v_cruise_kph = CS.cruiseState.speed * CV.MS_TO_KPH
        self.v_cruise_cluster_kph = CS.cruiseState.speedCluster * CV.MS_TO_KPH
        if CS.cruiseState.speed == 0:
          self.v_cruise_kph = V_CRUISE_UNSET
          self.v_cruise_cluster_kph = V_CRUISE_UNSET
        elif CS.cruiseState.speed == -1:
          self.v_cruise_kph = -1
          self.v_cruise_cluster_kph = -1
    else:
      self.v_cruise_kph = V_CRUISE_UNSET
      self.v_cruise_cluster_kph = V_CRUISE_UNSET

    if not self.CP.pcmCruise or not self.CP_SP.pcmCruiseSpeed:
      self.update_button_timers(CS, enabled)

  def _update_v_cruise_non_pcm(self, CS, enabled, is_metric):
    # handle button presses. TODO: this should be in state_control, but a decelCruise press
    # would have the effect of both enabling and changing speed is checked after the state transition
    if not enabled:
      return

    long_press = False
    button_type = None

    v_cruise_delta = 1. if is_metric else IMPERIAL_INCREMENT

    for b in CS.buttonEvents:
      if b.type.raw in self.button_timers and not b.pressed:
        if self.button_timers[b.type.raw] > CRUISE_LONG_PRESS:
          return  # end long press
        button_type = b.type.raw
        break
    else:
      for k, timer in self.button_timers.items():
        if timer and timer % CRUISE_LONG_PRESS == 0:
          button_type = k
          long_press = True
          break

    if button_type is None:
      return

    # Macan: SET 与 + 同一物理键（bit16+17 同置位），carstate 只保留 setCruise 事件。
    # 激活状态下 setCruise 按 accelCruise(+1) 语义调巡航速度（未激活时 setCruise=接合，不走此分支）
    if button_type == ButtonType.setCruise:
      # 00000045 实锤：超驰（gas 踩油门车速高于巡航）时按 SET，原厂把当前车速设为巡航速度。
      # 旧代码 setCruise→accelCruise(+1) 转换先于 133 行 gas 锚定执行，锚定永不触发。
      # 锚定必须在转换之前处理（enabled=激活中，未激活时 setCruise=接合不走此分支）。
      if CS.gasPressed and self.button_change_states[button_type]["enabled"]:
        # 2026-08-22 修复（00000052 seg11 实测：vEgo=42/cru=45 按SET没反应）：
        # 旧公式 max(v_cruise_kph, vEgo) 只增不减，介入车速<旧巡航时 vCruise 不变。
        # 改为以当前车速为锚、下限 30(公制)/20(英制)——>30 置当前车速、<30 置 30，
        # 与原厂语义一致（避免用 V_CRUISE_MIN=8 触发原厂 ACC st=6，用户确认）。
        anchor_min = 30.0 if is_metric else 20.0
        self.v_cruise_kph = np.clip(round(max(CS.vEgo * CV.MS_TO_KPH, anchor_min), 1), anchor_min, V_CRUISE_MAX)
        self.v_cruise_cluster_kph = self.v_cruise_kph
        return
      # 事件在 update_button_timers 中按 type.raw=setCruise 键存储 change state，
      # 转换后必须同步到 accelCruise 键，否则下方 button_change_states[accelCruise]["enabled"]
      # 读到初始 False 会直接 return，speed+ 永远无法调巡航速度（route 00000040 实锤）。
      self.button_change_states[ButtonType.accelCruise] = self.button_change_states[ButtonType.setCruise]
      button_type = ButtonType.accelCruise

    # Don't adjust speed when pressing resume to exit standstill
    cruise_standstill = self.button_change_states[button_type]["standstill"] or CS.cruiseState.standstill
    if button_type == ButtonType.accelCruise and cruise_standstill:
      return

    # Don't adjust speed if we've enabled since the button was depressed (some ports enable on rising edge)
    if not self.button_change_states[button_type]["enabled"]:
      return

    # Speed Limit Assist for Non PCM long cars.
    # True: Disallow set speed changes when user confirmed the target set speed during preActive state
    # False: Allow set speed changes as SLA is not requesting user confirmation
    if self.update_speed_limit_assist_pre_active_confirmed(button_type):
      return

    long_press, v_cruise_delta = VCruiseHelperSP.update_v_cruise_delta(self, long_press, v_cruise_delta)
    if long_press and self.v_cruise_kph % v_cruise_delta != 0:  # partial interval
      self.v_cruise_kph = CRUISE_NEAREST_FUNC[button_type](self.v_cruise_kph / v_cruise_delta) * v_cruise_delta
    else:
      self.v_cruise_kph += v_cruise_delta * CRUISE_INTERVAL_SIGN[button_type]

    # If set is pressed while overriding, clip cruise speed to minimum of vEgo
    if CS.gasPressed and button_type in (ButtonType.decelCruise, ButtonType.setCruise):
      self.v_cruise_kph = max(self.v_cruise_kph, CS.vEgo * CV.MS_TO_KPH)

    self.v_cruise_kph = np.clip(round(self.v_cruise_kph, 1), self.v_cruise_min, V_CRUISE_MAX)

  def update_button_timers(self, CS, enabled):
    # increment timer for buttons still pressed
    for k in self.button_timers:
      if self.button_timers[k] > 0:
        self.button_timers[k] += 1

    for b in CS.buttonEvents:
      if b.type.raw in self.button_timers:
        # Start/end timer and store current state on change of button pressed
        self.button_timers[b.type.raw] = 1 if b.pressed else 0
        self.button_change_states[b.type.raw] = {"standstill": CS.cruiseState.standstill, "enabled": enabled}

  def initialize_v_cruise(self, CS, experimental_mode: bool, dynamic_experimental_control: bool) -> None:
    # initializing is handled by the PCM
    if self.CP.pcmCruise:
      return

    initial_experimental_mode = experimental_mode and not dynamic_experimental_control
    initial = V_CRUISE_INITIAL_EXPERIMENTAL_MODE if initial_experimental_mode else V_CRUISE_INITIAL

    if any(b.type in (ButtonType.accelCruise, ButtonType.resumeCruise) for b in CS.buttonEvents) and self.v_cruise_initialized:
      self.v_cruise_kph = self.v_cruise_kph_last
    else:
      self.v_cruise_kph = int(round(np.clip(CS.vEgo * CV.MS_TO_KPH, initial, V_CRUISE_MAX)))

    self.v_cruise_cluster_kph = self.v_cruise_kph
