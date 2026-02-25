"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
from enum import StrEnum

from opendbc.car import Bus, create_button_events, structs
from opendbc.can.parser import CANParser
from opendbc.car.common.conversions import Conversions as CV
from opendbc.car.tesla.values import DBC, CANBUS
from opendbc.sunnypilot.car.tesla.values import TeslaFlagsSP

ButtonType = structs.CarState.ButtonEvent.Type


class CarStateExt:
  def __init__(self, CP: structs.CarParams, CP_SP: structs.CarParamsSP):
    self.CP = CP
    self.CP_SP = CP_SP

    self.infotainment_3_finger_press = 0

  def update(self, ret: structs.CarState, ret_sp: structs.CarStateSP, can_parsers: dict[StrEnum, CANParser]) -> None:
    if self.CP_SP.flags & TeslaFlagsSP.HAS_VEHICLE_BUS:
      cp_adas = can_parsers[Bus.adas]

      prev_infotainment_3_finger_press = self.infotainment_3_finger_press
      self.infotainment_3_finger_press = int(cp_adas.vl["UI_status2"]["UI_activeTouchPoints"])

      ret.buttonEvents = [*create_button_events(self.infotainment_3_finger_press, prev_infotainment_3_finger_press,
                                                {3: ButtonType.lkas})]

      ui_soc = float(cp_adas.vl["ID33AUI_rangeSOC"].get("UI_SOC", 0.0))
      ui_range_mi = float(cp_adas.vl["ID33AUI_rangeSOC"].get("UI_Range", 0.0))
      hv_batt_voltage_v = float(cp_adas.vl["ID132HVBattAmpVolt"].get("BattVoltage132", 0.0))
      battery_details = None
      try:
        battery_details = ret.batteryDetails
      except Exception:
        battery_details = None

      if 0.0 <= ui_soc <= 100.0:
        ret.fuelGauge = ui_soc / 100.0
        if battery_details is not None:
          battery_details.soc = ui_soc
          battery_details.charge = ui_soc
      if 0.0 <= ui_range_mi <= 1023.0 and battery_details is not None:
        battery_details.capacity = ui_range_mi
      if 0.0 < hv_batt_voltage_v <= 800.0 and battery_details is not None:
        battery_details.voltage = hv_batt_voltage_v

    cp_party = can_parsers[Bus.party]
    cp_ap_party = can_parsers[Bus.ap_party]

    speed_units = self.can_define.dv["DI_state"]["DI_speedUnits"].get(int(cp_party.vl["DI_state"]["DI_speedUnits"]), None)
    speed_limit = cp_ap_party.vl["DAS_status"]["DAS_fusedSpeedLimit"]
    if self.can_define.dv["DAS_status"]["DAS_fusedSpeedLimit"].get(int(speed_limit), None) in ["NONE", "UNKNOWN_SNA"]:
      ret_sp.speedLimit = 0
    else:
      if speed_units == "KPH":
        ret_sp.speedLimit = speed_limit * CV.KPH_TO_MS
      elif speed_units == "MPH":
        ret_sp.speedLimit = speed_limit * CV.MPH_TO_MS

  @staticmethod
  def get_parser(CP: structs.CarParams, CP_SP: structs.CarParamsSP) -> dict[StrEnum, CANParser]:
    messages = {}

    if CP_SP.flags & TeslaFlagsSP.HAS_VEHICLE_BUS:
      messages[Bus.adas] = CANParser(DBC[CP.carFingerprint][Bus.adas], [], CANBUS.vehicle)

    return messages
