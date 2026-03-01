import cereal.messaging as messaging
from cereal import log, car, custom
from openpilot.common.constants import CV
from openpilot.iqpilot.selfdrive.selfdrived.events_base import EventsBase, Priority, ET, Alert, \
  NoEntryAlert, ImmediateDisableAlert, EngagementAlert, NormalPermanentAlert, AlertCallbackType, wrong_car_mode_alert
from openpilot.iqpilot.selfdrive.controls.lib.speed_limit import PCM_LONG_REQUIRED_MAX_SET_SPEED, CONFIRM_SPEED_THRESHOLD
#ADD TR TO Translate
from openpilot.system.ui.lib.multilang import tr


AlertSize = log.SelfdriveState.AlertSize
AlertStatus = log.SelfdriveState.AlertStatus
VisualAlert = car.CarControl.HUDControl.VisualAlert
AudibleAlert = car.CarControl.HUDControl.AudibleAlert
AudibleAlertIQ = custom.IQState.AudibleAlert
EventNameIQ = custom.IQOnroadEvent.EventName


# get event name from enum
EVENT_NAME_IQ = {v: k for k, v in EventNameIQ.schema.enumerants.items()}


def _get_longitudinal_plan_ext(sm: messaging.SubMaster):
  return sm['iqPlan']


def speed_limit_adjust_alert(CP: car.CarParams, CS: car.CarState, sm: messaging.SubMaster, metric: bool, soft_disable_time: int, personality) -> Alert:
  speedLimit = _get_longitudinal_plan_ext(sm).speedLimit.resolver.speedLimit
  speed = round(speedLimit * (CV.MS_TO_KPH if metric else CV.MS_TO_MPH))
  message = tr("Adjusting to {speed} {unit} speed limit", speed=speed, unit="km/h" if metric else "mph")
  return Alert(
    message,
    "",
    AlertStatus.normal, AlertSize.small,
    Priority.LOW, VisualAlert.none, AudibleAlert.none, 4.)


def speed_limit_pre_active_alert(CP: car.CarParams, CS: car.CarState, sm: messaging.SubMaster, metric: bool, soft_disable_time: int, personality) -> Alert:
  speed_conv = CV.MS_TO_KPH if metric else CV.MS_TO_MPH
  speed_limit_final_last = _get_longitudinal_plan_ext(sm).speedLimit.resolver.speedLimitFinalLast
  speed_limit_final_last_conv = round(speed_limit_final_last * speed_conv)
  alert_1_str = ""
  alert_2_str = ""
  alert_size = AlertSize.none

  if CP.openpilotLongitudinalControl and CP.pcmCruise:
    # PCM long
    cst_low, cst_high = PCM_LONG_REQUIRED_MAX_SET_SPEED[metric]
    pcm_long_required_max = cst_low if speed_limit_final_last_conv < CONFIRM_SPEED_THRESHOLD[metric] else cst_high
    pcm_long_required_max_set_speed_conv = round(pcm_long_required_max * speed_conv)
    speed_unit = "km/h" if metric else "mph"

    alert_1_str = tr("Speed Limit Assist: Activation Required")
    alert_2_str = tr("Manually change set speed to {speed} {unit} to activate", speed=pcm_long_required_max_set_speed_conv, unit=speed_unit)
    alert_size = AlertSize.mid

  return Alert(
    alert_1_str,
    alert_2_str,
    AlertStatus.normal, alert_size,
    Priority.LOW, VisualAlert.none, AudibleAlertIQ.promptSingleLow, .1)


class IQEvents(EventsBase):
  def __init__(self):
    super().__init__()
    self.event_counters = dict.fromkeys(EVENTS_IQ.keys(), 0)

  def get_events_mapping(self) -> dict[int, dict[str, Alert | AlertCallbackType]]:
    return EVENTS_IQ

  def get_event_name(self, event: int):
    return EVENT_NAME_IQ[event]

  def get_event_msg_type(self):
    return custom.IQOnroadEvent.Event


EVENTS_IQ: dict[int, dict[str, Alert | AlertCallbackType]] = {
  # iqpilot
  EventNameIQ.lkasEnable: {
    ET.ENABLE: EngagementAlert(AudibleAlert.engage),
  },

  EventNameIQ.lkasDisable: {
    ET.USER_DISABLE: EngagementAlert(AudibleAlert.disengage),
  },

  EventNameIQ.manualSteeringRequired: {
    ET.USER_DISABLE: Alert(
      tr("Automatic Lane Centering is OFF"),
      tr("Manual Steering Required"),
      AlertStatus.normal, AlertSize.mid,
      Priority.LOW, VisualAlert.none, AudibleAlert.disengage, 1.),
  },

  EventNameIQ.manualLongitudinalRequired: {
    ET.WARNING: Alert(
      tr("Smart/Adaptive Cruise Control: OFF"),
      tr("Manual Speed Control Required"),
      AlertStatus.normal, AlertSize.mid,
      Priority.LOW, VisualAlert.none, AudibleAlert.none, 1.),
  },

  EventNameIQ.silentLkasEnable: {
    ET.ENABLE: EngagementAlert(AudibleAlert.none),
  },

  EventNameIQ.silentLkasDisable: {
    ET.USER_DISABLE: EngagementAlert(AudibleAlert.none),
  },

  EventNameIQ.silentBrakeHold: {
    ET.WARNING: EngagementAlert(AudibleAlert.none),
    ET.NO_ENTRY: NoEntryAlert(tr("Brake Hold Active")),
  },

  EventNameIQ.silentWrongGear: {
    ET.WARNING: Alert(
      "",
      "",
      AlertStatus.normal, AlertSize.none,
      Priority.LOWEST, VisualAlert.none, AudibleAlert.none, 0.),
    ET.NO_ENTRY: Alert(
      tr("Gear not D"),
      tr("openpilot Unavailable"),
      AlertStatus.normal, AlertSize.mid,
      Priority.LOW, VisualAlert.none, AudibleAlert.none, 0.),
  },

  EventNameIQ.silentReverseGear: {
    ET.PERMANENT: Alert(
      tr("Reverse\nGear"),
      "",
      AlertStatus.normal, AlertSize.full,
      Priority.LOWEST, VisualAlert.none, AudibleAlert.none, .2, creation_delay=0.5),
    ET.NO_ENTRY: NoEntryAlert(tr("Reverse Gear")),
  },

  EventNameIQ.silentDoorOpen: {
    ET.WARNING: Alert(
      "",
      "",
      AlertStatus.normal, AlertSize.none,
      Priority.LOWEST, VisualAlert.none, AudibleAlert.none, 0.),
    ET.NO_ENTRY: NoEntryAlert(tr("Door Open")),
  },

  EventNameIQ.silentSeatbeltNotLatched: {
    ET.WARNING: Alert(
      "",
      "",
      AlertStatus.normal, AlertSize.none,
      Priority.LOWEST, VisualAlert.none, AudibleAlert.none, 0.),
    ET.NO_ENTRY: NoEntryAlert(tr("Seatbelt Unlatched")),
  },

  EventNameIQ.silentParkBrake: {
    ET.WARNING: Alert(
      "",
      "",
      AlertStatus.normal, AlertSize.none,
      Priority.LOWEST, VisualAlert.none, AudibleAlert.none, 0.),
    ET.NO_ENTRY: NoEntryAlert(tr("Parking Brake Engaged")),
  },

  EventNameIQ.controlsMismatchLateral: {
    ET.IMMEDIATE_DISABLE: ImmediateDisableAlert(tr("Controls Mismatch: Lateral")),
    ET.NO_ENTRY: NoEntryAlert(tr("Controls Mismatch: Lateral")),
  },

  EventNameIQ.experimentalModeSwitched: {
    ET.WARNING: NormalPermanentAlert(tr("Experimental Mode Switched"), duration=1.5)
  },

  EventNameIQ.wrongCarModeAlertOnly: {
    ET.WARNING: wrong_car_mode_alert,
  },

  EventNameIQ.pedalPressedAlertOnly: {
    ET.WARNING: NoEntryAlert(tr("Pedal Pressed"))
  },

  EventNameIQ.laneTurnLeft: {
    ET.WARNING: Alert(
      tr("Turning Left"),
      "",
      AlertStatus.normal, AlertSize.small,
      Priority.LOW, VisualAlert.none, AudibleAlert.none, 1.),
  },

  EventNameIQ.laneTurnRight: {
    ET.WARNING: Alert(
      tr("Turning Right"),
      "",
      AlertStatus.normal, AlertSize.small,
      Priority.LOW, VisualAlert.none, AudibleAlert.none, 1.),
  },

  EventNameIQ.speedLimitActive: {
    ET.WARNING: Alert(
      tr("Automatically adjusting to the posted speed limit"),
      "",
      AlertStatus.normal, AlertSize.small,
      Priority.LOW, VisualAlert.none, AudibleAlertIQ.promptSingleHigh, 5.),
  },

  EventNameIQ.speedLimitChanged: {
    ET.WARNING: Alert(
      tr("Set speed changed"),
      "",
      AlertStatus.normal, AlertSize.small,
      Priority.LOW, VisualAlert.none, AudibleAlertIQ.promptSingleHigh, 5.),
  },

  EventNameIQ.speedLimitPreActive: {
    ET.WARNING: speed_limit_pre_active_alert,
  },

  EventNameIQ.speedLimitPending: {
    ET.WARNING: Alert(
      tr("Automatically adjusting to the last speed limit"),
      "",
      AlertStatus.normal, AlertSize.small,
      Priority.LOW, VisualAlert.none, AudibleAlertIQ.promptSingleHigh, 5.),
  },

  EventNameIQ.e2eChime: {
    ET.PERMANENT: Alert(
      "",
      "",
      AlertStatus.normal, AlertSize.none,
      Priority.MID, VisualAlert.none, AudibleAlert.prompt, 3.),
  },
}
