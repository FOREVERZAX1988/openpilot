"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""

from cereal import log, custom

from opendbc.car import structs
from opendbc.car.hyundai.values import HyundaiFlags
from openpilot.common.params import Params
from openpilot.iqpilot.aol.helpers import AolSteeringModeOnBrake, read_steering_mode_param, AOL_NO_ACC_MAIN_BUTTON, \
  get_aol_enabled, get_aol_main_cruise_allowed, get_aol_unified_engagement_mode
from openpilot.iqpilot.aol.state import AolStateMachine, GEARS_ALLOW_PAUSED_SILENT

State = custom.AlwaysOnLateral.AlwaysOnLateralState
ButtonType = structs.CarState.ButtonEvent.Type
EventName = log.OnroadEvent.EventName
EventNameIQ = custom.IQOnroadEvent.EventName
GearShifter = structs.CarState.GearShifter
SafetyModel = structs.CarParams.SafetyModel

SET_SPEED_BUTTONS = (ButtonType.accelCruise, ButtonType.resumeCruise, ButtonType.decelCruise, ButtonType.setCruise)
IGNORED_SAFETY_MODES = (SafetyModel.silent, SafetyModel.noOutput)


class AlwaysOnLateral:
  def __init__(self, selfdrive):
    self.CP = selfdrive.CP
    self.CP_IQ = selfdrive.CP_IQ
    self.params = selfdrive.params

    self.enabled = False
    self.active = False
    self.available = False
    self.allow_always = False
    self.no_main_cruise = False
    self.selfdrive = selfdrive
    self.selfdrive.enabled_prev = False
    self.state_machine = AolStateMachine(self)
    self.events = self.selfdrive.events
    self.events_iq = self.selfdrive.events_iq
    self.disengage_on_accelerator = Params().get_bool("DisengageOnAccelerator")
    if self.CP.brand == "hyundai":
      if self.CP.flags & (HyundaiFlags.HAS_LDA_BUTTON | HyundaiFlags.CANFD):
        self.allow_always = True
    if self.CP.brand == "tesla":
      self.allow_always = True

    if self.CP.brand in AOL_NO_ACC_MAIN_BUTTON:
      self.no_main_cruise = True

    # read params on init
    self.enabled_toggle = get_aol_enabled(self.params)
    self.main_enabled_toggle = get_aol_main_cruise_allowed(self.params)
    self.steering_mode_on_brake = read_steering_mode_param(self.CP, self.CP_IQ, self.params)
    self.unified_engagement_mode = get_aol_unified_engagement_mode(self.params)

  def read_params(self):
    self.main_enabled_toggle = get_aol_main_cruise_allowed(self.params)
    self.unified_engagement_mode = get_aol_unified_engagement_mode(self.params)

  def _consume_joystick_aol_request(self, CS: structs.CarState) -> str | None:
    if not self.params.get_bool("JoystickDebugMode"):
      return None

    # Prefer AOL key and keep legacy key compatibility.
    raw = self.params.get("JoystickAolRequest")
    legacy_raw = self.params.get("JoystickAolRequest")
    if raw is None:
      raw = legacy_raw
    if not raw:
      return None

    try:
      request = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else str(raw)
    except Exception:
      request = ""

    self.params.remove("JoystickAolRequest")
    self.params.remove("JoystickAolRequest")
    request = request.strip().lower()
    if request not in ("enable", "disable"):
      return None

    started = getattr(CS, "started", False)
    if not started:
      return None

    if getattr(CS, "doorOpen", False) or getattr(CS, "seatbeltUnlatched", False):
      return None

    if getattr(CS, "gearShifter", GearShifter.unknown) in (GearShifter.park, GearShifter.reverse):
      return None

    return request

  def pedal_pressed_non_gas_pressed(self, CS: structs.CarState) -> bool:
    # ignore `pedalPressed` events caused by gas presses
    if self.events.has(EventName.pedalPressed) and not (CS.gasPressed and not self.selfdrive.CS_prev.gasPressed and self.disengage_on_accelerator):
      return True

    return False

  def should_silent_lkas_enable(self, CS: structs.CarState) -> bool:
    if self.steering_mode_on_brake == AolSteeringModeOnBrake.PAUSE and self.pedal_pressed_non_gas_pressed(CS):
      return False

    if self.events_iq.contains_in_list(GEARS_ALLOW_PAUSED_SILENT):
      return False

    return True

  def block_unified_engagement_mode(self) -> bool:
    # UEM disabled
    if not self.unified_engagement_mode:
      return True

    if self.enabled:
      return True

    if self.selfdrive.enabled and self.selfdrive.enabled_prev:
      return True

    return False

  def get_wrong_car_mode(self, alert_only: bool) -> None:
    if alert_only:
      if self.events.has(EventName.wrongCarMode):
        self.replace_event(EventName.wrongCarMode, EventNameIQ.wrongCarModeAlertOnly)
    else:
      self.events.remove(EventName.wrongCarMode)

  def transition_paused_state(self):
    if self.state_machine.state != State.paused:
      self.events_iq.add(EventNameIQ.silentLkasDisable)

  def replace_event(self, old_event: int, new_event: int):
    self.events.remove(old_event)
    self.events_iq.add(new_event)

  def update_events(self, CS: structs.CarState):
    request = self._consume_joystick_aol_request(CS)
    if request == "enable":
      self.events_iq.add(EventNameIQ.lkasEnable)
    elif request == "disable":
      self.events_iq.add(EventNameIQ.lkasDisable)

    if not self.selfdrive.enabled and self.enabled:
      if CS.standstill:
        if self.events.has(EventName.doorOpen):
          self.replace_event(EventName.doorOpen, EventNameIQ.silentDoorOpen)
          self.transition_paused_state()
        if self.events.has(EventName.seatbeltNotLatched):
          self.replace_event(EventName.seatbeltNotLatched, EventNameIQ.silentSeatbeltNotLatched)
          self.transition_paused_state()
      if self.events.has(EventName.wrongGear) and (CS.vEgo < 2.5 or CS.gearShifter == GearShifter.reverse):
        self.replace_event(EventName.wrongGear, EventNameIQ.silentWrongGear)
        self.transition_paused_state()
      if self.events.has(EventName.reverseGear):
        self.replace_event(EventName.reverseGear, EventNameIQ.silentReverseGear)
        self.transition_paused_state()
      if self.events.has(EventName.brakeHold):
        self.replace_event(EventName.brakeHold, EventNameIQ.silentBrakeHold)
        self.transition_paused_state()
      if self.events.has(EventName.parkBrake):
        self.replace_event(EventName.parkBrake, EventNameIQ.silentParkBrake)
        self.transition_paused_state()

      if self.steering_mode_on_brake == AolSteeringModeOnBrake.PAUSE:
        if self.pedal_pressed_non_gas_pressed(CS):
          self.transition_paused_state()

      self.events.remove(EventName.preEnableStandstill)
      self.events.remove(EventName.belowEngageSpeed)
      self.events.remove(EventName.speedTooLow)
      self.events.remove(EventName.cruiseDisabled)
      self.events.remove(EventName.manualRestart)

    selfdrive_enable_events = self.events.has(EventName.pcmEnable) or self.events.has(EventName.buttonEnable)
    set_speed_btns_enable = any(be.type in SET_SPEED_BUTTONS for be in CS.buttonEvents)

    # wrongCarMode alert only or actively block control
    self.get_wrong_car_mode(selfdrive_enable_events or set_speed_btns_enable)

    if selfdrive_enable_events:
      if self.pedal_pressed_non_gas_pressed(CS):
        self.events_iq.add(EventNameIQ.pedalPressedAlertOnly)

      if self.block_unified_engagement_mode():
        self.events.remove(EventName.pcmEnable)
        self.events.remove(EventName.buttonEnable)
    else:
      if self.main_enabled_toggle:
        lateral_available = getattr(CS, 'lateralAvailable', CS.cruiseState.available)
        lateral_available_prev = getattr(self.selfdrive.CS_prev, 'lateralAvailable', self.selfdrive.CS_prev.cruiseState.available)
        if lateral_available and not lateral_available_prev:
          self.events_iq.add(EventNameIQ.lkasEnable)

    for be in CS.buttonEvents:
      if be.type == ButtonType.cancel:
        if not self.selfdrive.enabled and self.selfdrive.enabled_prev:
          self.events_iq.add(EventNameIQ.manualLongitudinalRequired)
      lateral_available = getattr(CS, 'lateralAvailable', CS.cruiseState.available)
      if be.type == ButtonType.lkas and be.pressed and (lateral_available or self.allow_always):
        if self.enabled:
          if self.selfdrive.enabled:
            self.events_iq.add(EventNameIQ.manualSteeringRequired)
          else:
            self.events_iq.add(EventNameIQ.lkasDisable)
        else:
          self.events_iq.add(EventNameIQ.lkasEnable)

    lateral_available = getattr(CS, 'lateralAvailable', CS.cruiseState.available)
    lateral_available_prev = getattr(self.selfdrive.CS_prev, 'lateralAvailable', self.selfdrive.CS_prev.cruiseState.available)
    if not lateral_available and not self.no_main_cruise:
      self.events.remove(EventName.buttonEnable)
      if lateral_available_prev:
        self.events_iq.add(EventNameIQ.lkasDisable)

    if self.steering_mode_on_brake == AolSteeringModeOnBrake.DISENGAGE:
      if self.pedal_pressed_non_gas_pressed(CS):
        if self.enabled:
          self.events_iq.add(EventNameIQ.lkasDisable)
        else:
          # block lkasEnable if being sent, then send pedalPressedAlertOnly event
          if self.events_iq.contains(EventNameIQ.lkasEnable):
            self.events_iq.remove(EventNameIQ.lkasEnable)
            self.events_iq.add(EventNameIQ.pedalPressedAlertOnly)

    if self.should_silent_lkas_enable(CS):
      if self.state_machine.state == State.paused:
        self.events_iq.add(EventNameIQ.silentLkasEnable)

    self.events.remove(EventName.pcmDisable)
    self.events.remove(EventName.buttonCancel)
    self.events.remove(EventName.pedalPressed)
    self.events.remove(EventName.wrongCruiseMode)

  def update(self, CS: structs.CarState):
    if not self.enabled_toggle:
      return

    self.update_events(CS)

    if not self.CP.passive and self.selfdrive.initialized:
      self.enabled, self.active = self.state_machine.update()

    # Copy of previous SelfdriveD states for AOL events handling
    self.selfdrive.enabled_prev = self.selfdrive.enabled

