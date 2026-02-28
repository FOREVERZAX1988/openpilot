"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""

from openpilot.common.params import Params
from opendbc.car import structs
from opendbc.safety import ALTERNATIVE_EXPERIENCE
from opendbc.iqpilot.car.hyundai.values import HyundaiFlagsIQ, HyundaiSafetyFlagsIQ
from opendbc.iqpilot.car.tesla.values import TeslaFlagsIQ


AOL_NO_ACC_MAIN_BUTTON = ("rivian", "tesla")


class AolSteeringModeOnBrake:
  REMAIN_ACTIVE = 0
  PAUSE = 1
  DISENGAGE = 2


def get_aol_limited_brands(CP: structs.CarParams, CP_IQ: structs.IQCarParams) -> bool:
  if CP.brand == 'rivian':
    return True
  if CP.brand == 'tesla':
    return not CP_IQ.flags & TeslaFlagsIQ.HAS_VEHICLE_BUS

  return False


def get_aol_enabled(params: Params) -> bool:
  return params.get_bool("AolEnabled")


def get_aol_main_cruise_allowed(params: Params) -> bool:
  return params.get_bool("AolMainCruiseAllowed")


def get_aol_unified_engagement_mode(params: Params) -> bool:
  return params.get_bool("AolUnifiedEngagementMode")


def read_steering_mode_param(CP: structs.CarParams, CP_IQ: structs.IQCarParams, params: Params):
  if get_aol_limited_brands(CP, CP_IQ):
    return AolSteeringModeOnBrake.DISENGAGE

  return params.get("AolSteeringMode", return_default=True)


def set_alternative_experience(CP: structs.CarParams, CP_IQ: structs.IQCarParams, params: Params):
  enabled = get_aol_enabled(params)
  steering_mode = read_steering_mode_param(CP, CP_IQ, params)

  if enabled:
    CP.alternativeExperience |= ALTERNATIVE_EXPERIENCE.ENABLE_AOL

    if steering_mode == AolSteeringModeOnBrake.DISENGAGE:
      CP.alternativeExperience |= ALTERNATIVE_EXPERIENCE.AOL_DISENGAGE_LATERAL_ON_BRAKE
    elif steering_mode == AolSteeringModeOnBrake.PAUSE:
      CP.alternativeExperience |= ALTERNATIVE_EXPERIENCE.AOL_PAUSE_LATERAL_ON_BRAKE


def set_car_specific_params(CP: structs.CarParams, CP_IQ: structs.IQCarParams, params: Params):
  if CP.brand == "hyundai":
    # TODO-IQ: This should be separated from AOL module for future implementations
    #          Use "HyundaiLongitudinalMainCruiseToggleable" param
    hyundai_cruise_main_toggleable = True
    if hyundai_cruise_main_toggleable:
      CP_IQ.flags |= HyundaiFlagsIQ.LONGITUDINAL_MAIN_CRUISE_TOGGLEABLE.value
      CP_IQ.safetyParam |= HyundaiSafetyFlagsIQ.LONG_MAIN_CRUISE_TOGGLEABLE

  # AOL Partial Support
  # AOL is currently partially supported for these platforms due to lack of consistent states to engage controls
  # Only AolSteeringModeOnBrake.DISENGAGE is supported for these platforms
  # TODO-IQ: To enable AOL full support for Rivian and most Tesla, identify consistent signals for AOL toggling
  aol_partial_support = get_aol_limited_brands(CP, CP_IQ)
  if aol_partial_support:
    params.put("AolSteeringMode", 2)
    params.put_bool("AolUnifiedEngagementMode", True)

  # no ACC MAIN button for these brands
  if CP.brand in AOL_NO_ACC_MAIN_BUTTON:
    params.remove("AolMainCruiseAllowed")
