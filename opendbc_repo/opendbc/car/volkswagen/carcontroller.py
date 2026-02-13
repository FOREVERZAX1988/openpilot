import sys
import os
import numpy as np
from opendbc.can import CANPacker
from opendbc.car import Bus, DT_CTRL, structs
from opendbc.car.lateral import apply_driver_steer_torque_limits
from opendbc.car.common.conversions import Conversions as CV
from opendbc.car.interfaces import CarControllerBase
from opendbc.car.volkswagen import mlbcan, mqbcan, pqcan
from opendbc.car.volkswagen.values import CanBus, CarControllerParams, VolkswagenFlags

sunnypilot_path = os.path.join(os.path.dirname(__file__), '..', '..', '..')
sys.path.insert(0, sunnypilot_path)
try:
  from openpilot.common.params import Params
except ImportError:
  pass

VisualAlert = structs.CarControl.HUDControl.VisualAlert
LongCtrlState = structs.CarControl.Actuators.LongControlState


class CarController(CarControllerBase):
  def __init__(self, dbc_names, CP, CP_SP):
    super().__init__(dbc_names, CP, CP_SP)
    self._params = Params()
    self.CCP = CarControllerParams(CP)
    self.CAN = CanBus(CP)
    self.packer_pt = CANPacker(dbc_names[Bus.pt])

    if CP.flags & VolkswagenFlags.PQ:
      self.CCS = pqcan
    elif CP.flags & VolkswagenFlags.MLB:
      self.CCS = mlbcan
    else:
      self.CCS = mqbcan

    self.accel = 0
    self.apply_torque_last = 0
    self.gra_acc_counter_last = None
    self.eps_timer_soft_disable_alert = False
    self.hca_frame_timer_running = 0
    self.hca_frame_same_torque = 0
    self.accel_last = 0
    self.accel_diff = 0
    self.long_deviation = 0
    self.long_jerklimit = 0
    self.HCA_Status = 3
    self.leadDistanceBars = 0
    self.blinkerActive = None
    self.eps_timer_workaround = bool(CP.flags & VolkswagenFlags.MLB)
    self.hca_frame_timer_resetting = 0
    self.hca_frame_low_torque = 0

  def update(self, CC, CC_SP, CS, now_nanos):
    actuators = CC.actuators
    hud_control = CC.hudControl
    can_sends = []
    output_torque = 0
    pqhca5or7Toggle = self._params.get_bool("pqhca5or7Toggle")

    # **** Steering Controls ************************************************ #

    if self.frame % self.CCP.STEER_STEP == 0:
      if CC.latActive:
        new_torque = int(round(actuators.torque * self.CCP.STEER_MAX))
        apply_torque = apply_driver_steer_torque_limits(new_torque, self.apply_torque_last, CS.out.steeringTorque, self.CCP)
        self.hca_frame_timer_running += self.CCP.STEER_STEP
        if self.apply_torque_last == apply_torque:
          self.hca_frame_same_torque += self.CCP.STEER_STEP
          if self.hca_frame_same_torque > self.CCP.STEER_TIME_STUCK_TORQUE / DT_CTRL:
            apply_torque -= (1, -1)[apply_torque < 0]
            self.hca_frame_same_torque = 0
        else:
          self.hca_frame_same_torque = 0
        hca_enabled = abs(apply_torque) > 0
        if self.eps_timer_workaround and self.hca_frame_timer_running >= self.CCP.STEER_TIME_BM / DT_CTRL:
          if abs(apply_torque) <= self.CCP.STEER_LOW_TORQUE:
            self.hca_frame_low_torque += self.CCP.STEER_STEP
            if self.hca_frame_low_torque >= self.CCP.STEER_TIME_LOW_TORQUE / DT_CTRL:
              hca_enabled = False
          else:
            self.hca_frame_low_torque = 0
            if self.hca_frame_timer_resetting > 0:
              apply_torque = 0
      else:
        self.hca_frame_low_torque = 0
        hca_enabled = False
        apply_torque = 0

      if hca_enabled:
        output_torque = apply_torque
        self.hca_frame_timer_resetting = 0
      else:
        output_torque = 0
        self.hca_frame_timer_resetting += self.CCP.STEER_STEP
        if self.hca_frame_timer_resetting >= self.CCP.STEER_TIME_RESET / DT_CTRL or not self.eps_timer_workaround:
          self.hca_frame_timer_running = 0
          apply_torque = 0

      if hca_enabled and abs(apply_torque) > 0:
        if pqhca5or7Toggle and (self.CP.flags & (VolkswagenFlags.PQ | VolkswagenFlags.MLB)):
          self.HCA_Status = 7
        else:
          self.HCA_Status = 5
      else:
        self.HCA_Status = 3

      self.eps_timer_soft_disable_alert = self.hca_frame_timer_running > self.CCP.STEER_TIME_ALERT / DT_CTRL
      self.apply_torque_last = apply_torque

      can_sends.append(self.CCS.create_hca_steering_control(self.packer_pt, self.CAN.pt, output_torque, self.HCA_Status))

      if self.CP.flags & VolkswagenFlags.STOCK_HCA_PRESENT:
        # Pacify VW Emergency Assist driver inactivity detection by changing its view of driver steering input torque
        # to the greatest of actual driver input or 2x openpilot's output (1x openpilot output is not enough to
        # consistently reset inactivity detection on straight level roads). See commaai/openpilot#23274 for background.
        ea_simulated_torque = float(np.clip(apply_torque * 2, -self.CCP.STEER_MAX, self.CCP.STEER_MAX))
        if abs(CS.out.steeringTorque) > abs(ea_simulated_torque):
          ea_simulated_torque = CS.out.steeringTorque
        can_sends.append(self.CCS.create_eps_update(self.packer_pt, self.CAN.cam, CS.eps_stock_values, ea_simulated_torque))

    # **** Acceleration Controls ******************************************** #

    if self.frame % self.CCP.ACC_CONTROL_STEP == 0 and self.CP.openpilotLongitudinalControl:
      acc_control = self.CCS.acc_control_value(CS.out.cruiseState.available, CC.longActive, CC.cruiseControl.override, CS.out.accFaulted)
      accel = float(np.clip(actuators.accel, self.CCP.ACCEL_MIN, self.CCP.ACCEL_MAX) if CC.longActive else 0)
      stopping = actuators.longControlState == LongCtrlState.stopping
      if stopping and accel < 0:
        self.accel = -2.0
      else:
        self.accel = accel
      starting = actuators.longControlState == LongCtrlState.pid and (CS.esp_hold_confirmation or CS.out.vEgo < self.CP.vEgoStopping)
      self.accel_diff = (0.0019 * (accel - self.accel_last)) + (1 - 0.0019) * self.accel_diff
      self.long_jerklimit = (0.01 * (np.clip(abs(accel), 0.7, 2))) + (1 - 0.01) * self.long_jerklimit
      self.long_deviation = np.interp(abs(accel - self.accel_diff), [0, 0.3, 1.0], [0.02, 0.04, 0.08])
      self.accel_last = accel
      can_sends.extend(self.CCS.create_acc_accel_control(self.packer_pt, self.CAN.pt, CS.acc_type, self.accel, acc_control, stopping, starting, CS.esp_hold_confirmation, self.long_deviation, self.long_jerklimit))

    # **** HUD Controls ***************************************************** #

    if self.frame % self.CCP.LDW_STEP == 0:
      hud_alert = 0
      if hud_control.visualAlert in (VisualAlert.steerRequired, VisualAlert.ldw) or CS.out.steerFaultTemporary:
        hud_alert = self.CCP.LDW_MESSAGES["laneAssistTakeOver"]
      can_sends.append(self.CCS.create_lka_hud_control(self.packer_pt, self.CAN.pt, CS.ldw_stock_values, CC.latActive, CS.out.steeringPressed, hud_alert, hud_control))
    if self.frame % self.CCP.ACC_HUD_STEP == 0 and self.CP.openpilotLongitudinalControl:
      leadDistance = min(8, hud_control.leadDistance) if hud_control.leadDistance != 0 else 0
      fcw_alert = hud_control.visualAlert == VisualAlert.fcw
      self.leadDistanceBars = min(3, hud_control.leadDistanceBars)
      acc_hud_status = self.CCS.acc_hud_status_value(CS.out.cruiseState.available, CS.out.accFaulted, CS.out.gasPressed, CC.longActive, CC.cruiseControl.override)
      set_speed = hud_control.setSpeed * CV.MS_TO_KPH
      can_sends.append(self.CCS.create_acc_hud_control(self.packer_pt, self.CAN.pt, acc_hud_status, set_speed, leadDistance, self.leadDistanceBars, fcw_alert, hud_control.leadVisible))

    # **** Volkswagen PQ Specific ************************************ #
    if self.CP.flags & VolkswagenFlags.PQ:
      if self.frame % 2 == 0:
        self.blinkerActive = CS.leftBlinkerUpdate or CS.rightBlinkerUpdate
        leftBlinker = CC.leftBlinker if not self.blinkerActive else False
        rightBlinker = CC.rightBlinker if not self.blinkerActive else False
        can_sends.append(self.CCS.create_blinker_control(self.packer_pt, self.CAN.pt, leftBlinker, rightBlinker))

    if self.CP.openpilotLongitudinalControl and (self.CP.flags & VolkswagenFlags.PQ):
      if self.frame % 2 == 0:
        can_sends.append(self.CCS.filter_motor2(self.packer_pt, self.CAN.ext, CS.motor2_stock))

    # **** Stock ACC Button Controls **************************************** #

    gra_send_ready = self.CP.pcmCruise and CS.gra_stock_values["COUNTER"] != self.gra_acc_counter_last
    if self.CP.flags & VolkswagenFlags.MLB:
      stock_cancel_pressed = bool(CS.gra_stock_values["LS_Abbrechen"])
    else: # MQB / PQ use GRA
      stock_cancel_pressed = bool(CS.gra_stock_values["GRA_Abbrechen"])

    if gra_send_ready and (stock_cancel_pressed or CC.cruiseControl.resume):
      bus_send = self.CAN.aux if self.CP.flags & VolkswagenFlags.PQ else self.CAN.ext
      can_sends.append(self.CCS.create_acc_buttons_control(self.packer_pt, bus_send, CS.gra_stock_values, cancel=stock_cancel_pressed, resume=CC.cruiseControl.resume))

    new_actuators = actuators.as_builder()
    new_actuators.torque = self.apply_torque_last / self.CCP.STEER_MAX
    new_actuators.torqueOutputCan = self.apply_torque_last

    self.gra_acc_counter_last = CS.gra_stock_values["COUNTER"]
    self.frame += 1
    return new_actuators, can_sends
