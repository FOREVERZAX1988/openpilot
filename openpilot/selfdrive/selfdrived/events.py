#!/usr/bin/env python3
import math
import os

from openpilot.cereal import log
from opendbc.car.structs import car
from opendbc.car.hyundai.values import HyundaiFlags
import openpilot.cereal.messaging as messaging
from openpilot.common.constants import CV
from openpilot.common.git import get_short_branch
from openpilot.common.params import Params
from openpilot.common.realtime import DT_CTRL
from openpilot.selfdrive.locationd.calibrationd import MIN_SPEED_FILTER
from openpilot.common.hardware import HARDWARE
from openpilot.common.dm import is_dm_disabled
from openpilot.sunnypilot.common.param_read import read_bool

from openpilot.sunnypilot.selfdrive.selfdrived.events_base import EventsBase, Priority, ET, Alert, \
   NoEntryAlert, SoftDisableAlert, UserSoftDisableAlert, ImmediateDisableAlert, EngagementAlert, NormalPermanentAlert, \
   StartupAlert, AlertCallbackType, wrong_car_mode_alert


AlertSize = log.SelfdriveState.AlertSize
AlertStatus = log.SelfdriveState.AlertStatus
VisualAlert = car.CarControl.HUDControl.VisualAlert
AudibleAlert = log.SelfdriveState.AudibleAlert
EventName = log.OnroadEvent.EventName


# get event name from enum
EVENT_NAME = {v: k for k, v in EventName.schema.enumerants.items()}

# Temporary-steering warnings are frequently momentary: a single dropped frame
# of steering makes steerTempUnavailable true for one cycle, and an alert that
# flashes for 100 ms trains the driver to ignore it. Present the warning only
# after 120 ms of accumulated faults, and require 1 s of health before the
# accumulator resets so short healthy gaps cannot hide repeated interruptions.
# Presentation only: the events themselves still drive the state machine, the
# counters and every deadline, and no-entry and critical alerts bypass the
# delay entirely. (upstream c61d998-series via cp 6a33883d)
TEMP_STEER_EVENTS = (EventName.steerTempUnavailable, EventName.steerTempUnavailableSilent)
TEMP_STEER_WARNING_DELAY_FRAMES = round(0.12 / DT_CTRL)
TEMP_STEER_WARNING_RESET_FRAMES = round(1.0 / DT_CTRL)


class Events(EventsBase):
  def __init__(self):
    super().__init__()
    self.event_counters = dict.fromkeys(EVENTS.keys(), 0)
    # Rebuilt once by bind_nnff_notice(), so the per-frame lookup stays a plain
    # attribute read instead of copying EVENTS on every contains()/create_alerts().
    self._events_mapping = EVENTS
    self._steer_warning_fault_frames = 0
    self._steer_warning_clear_frames = 0

  def bind_nnff_notice(self, model_name: str, fuzzy: bool) -> None:
    """Name the loaded NNFF model on the one-shot torqueNNLoad notice."""
    self._events_mapping = EVENTS | {EventName.torqueNNLoad: {ET.PERMANENT: nnff_load_alert(model_name, fuzzy)}}

  def clear(self) -> None:
    # Count completed cycles, sharing history across audible/silent variants.
    if any(e in self.events for e in TEMP_STEER_EVENTS):
      self._steer_warning_fault_frames = min(self._steer_warning_fault_frames + 1, TEMP_STEER_WARNING_DELAY_FRAMES)
      self._steer_warning_clear_frames = 0
    else:
      self._steer_warning_clear_frames = min(self._steer_warning_clear_frames + 1, TEMP_STEER_WARNING_RESET_FRAMES)
      if self._steer_warning_clear_frames >= TEMP_STEER_WARNING_RESET_FRAMES:
        self._steer_warning_fault_frames = 0
    super().clear()

  def create_alerts(self, event_types: list[str], callback_args=None):
    """The base builder, plus the temporary-steering presentation delay.

    The event stays in `self.events` the whole time - this only withholds the
    rendered alert, so control inhibition and the state machine are untouched.
    """
    if callback_args is None:
      callback_args = []

    ret = []
    for e in self.events:
      types = self.get_events_mapping()[e].keys()
      for et in event_types:
        if et in types:
          alert = self.get_events_mapping()[e][et]
          if not isinstance(alert, Alert):
            alert = alert(*callback_args)

          if (e in TEMP_STEER_EVENTS and et in (ET.SOFT_DISABLE, ET.WARNING) and
              alert.alert_status != AlertStatus.critical and
              self._steer_warning_fault_frames < TEMP_STEER_WARNING_DELAY_FRAMES):
            continue

          if DT_CTRL * (self.event_counters[e] + 1) >= alert.creation_delay:
            alert.alert_type = f"{self.get_event_name(e)}/{et}"
            alert.event_type = et
            ret.append(alert)
    return ret

  def get_events_mapping(self) -> dict[int, dict[str, Alert | AlertCallbackType]]:
    return self._events_mapping

  def get_event_name(self, event: int):
    return EVENT_NAME[event]

  def get_event_msg_type(self):
    return log.OnroadEvent



# ********** helper functions **********
def get_display_speed(speed_ms: float, metric: bool) -> str:
  speed = int(round(speed_ms * (CV.MS_TO_KPH if metric else CV.MS_TO_MPH)))
  unit = 'km/h' if metric else 'mph'
  return f"{speed} {unit}"


# ********** alert callback functions **********


def soft_disable_alert(alert_text_2: str) -> AlertCallbackType:
  def func(CP: car.CarParams, CS: car.CarState, sm: messaging.SubMaster, metric: bool, soft_disable_time: int, personality) -> Alert:
    if soft_disable_time < int(0.5 / DT_CTRL):
      return ImmediateDisableAlert(alert_text_2)
    return SoftDisableAlert(alert_text_2)
  return func

def user_soft_disable_alert(alert_text_2: str) -> AlertCallbackType:
  def func(CP: car.CarParams, CS: car.CarState, sm: messaging.SubMaster, metric: bool, soft_disable_time: int, personality) -> Alert:
    if soft_disable_time < int(0.5 / DT_CTRL):
      return ImmediateDisableAlert(alert_text_2)
    return UserSoftDisableAlert(alert_text_2)
  return func

def startup_master_alert(CP: car.CarParams, CS: car.CarState, sm: messaging.SubMaster, metric: bool, soft_disable_time: int, personality) -> Alert:
  branch = get_short_branch()  # Ensure get_short_branch is cached to avoid lags on startup
  if "REPLAY" in os.environ:
    branch = "replay"

  return StartupAlert('WARNING: This branch is not tested', branch, alert_status=AlertStatus.userPrompt)

def below_engage_speed_alert(CP: car.CarParams, CS: car.CarState, sm: messaging.SubMaster, metric: bool, soft_disable_time: int, personality) -> Alert:
  return NoEntryAlert(f'Drive above {get_display_speed(CP.minEnableSpeed, metric)} to engage')


def below_steer_speed_alert(CP: car.CarParams, CS: car.CarState, sm: messaging.SubMaster, metric: bool, soft_disable_time: int, personality) -> Alert:
  return Alert(
    f'Steer Unavailable Below {get_display_speed(CP.minSteerSpeed, metric)}',
    "",
    AlertStatus.userPrompt, AlertSize.small,
    Priority.LOW, VisualAlert.none, AudibleAlert.prompt, 0.4)


def calibration_incomplete_alert(CP: car.CarParams, CS: car.CarState, sm: messaging.SubMaster, metric: bool, soft_disable_time: int, personality) -> Alert:
  first_word = 'Recalibration' if sm['extrinsicsCalibration'].calStatus == log.ExtrinsicsCalibration.Status.recalibrating else 'Calibration'
  return Alert(
    f"{first_word} in Progress: {sm['extrinsicsCalibration'].calPerc:.0f}%",
    f'Drive above {get_display_speed(MIN_SPEED_FILTER, metric)} to Calibrate',
    AlertStatus.normal, AlertSize.mid,
    Priority.LOWEST, VisualAlert.none, AudibleAlert.none, .2)


def too_distracted_alert(CP: car.CarParams, CS: car.CarState, sm: messaging.SubMaster, metric: bool, soft_disable_time: int, personality) -> Alert:
  if is_dm_disabled():
    return NoEntryAlert("", priority=Priority.LOWEST)
  if sm['driverMonitoringState'].lockout:
    mins_left = sm['driverMonitoringState'].lockoutMinutesRemaining
    subtitle = f'{mins_left} Minutes Left'
    return NoEntryAlert('Too Distracted', subtitle, priority=Priority.HIGH)
  return NoEntryAlert('Pay Attention to Engage', priority=Priority.HIGH)


def audio_feedback_alert(CP: car.CarParams, CS: car.CarState, sm: messaging.SubMaster, metric: bool, soft_disable_time: int, personality) -> Alert:
  return NormalPermanentAlert(
    'Recording Audio Feedback',
    '30 Seconds Left. Press Again to Save Early.',
    priority=Priority.LOW)


def out_of_space_alert(CP: car.CarParams, CS: car.CarState, sm: messaging.SubMaster, metric: bool, soft_disable_time: int, personality) -> Alert:
  full_perc = round(100. - sm['deviceState'].freeSpacePercent)
  return NormalPermanentAlert('Out of Storage', f'Used: {full_perc}%')


def posenet_invalid_alert(CP: car.CarParams, CS: car.CarState, sm: messaging.SubMaster, metric: bool, soft_disable_time: int, personality) -> Alert:
  mdl = sm['modelV2'].velocity.x[0] if len(sm['modelV2'].velocity.x) else math.nan
  err = CS.vEgo - mdl
  msg = f'Speed Error: {err:.1f} m/s'
  return NoEntryAlert(msg, alert_text_1='Posenet Speed Invalid')


def process_not_running_alert(CP: car.CarParams, CS: car.CarState, sm: messaging.SubMaster, metric: bool, soft_disable_time: int, personality) -> Alert:
  not_running = [p.name for p in sm['managerState'].processes if not p.running and p.shouldBeRunning]
  msg = ', '.join(not_running)
  return NoEntryAlert(msg, alert_text_1='Process Not Running')


def comm_issue_alert(CP: car.CarParams, CS: car.CarState, sm: messaging.SubMaster, metric: bool, soft_disable_time: int, personality) -> Alert:
  bs = [s for s in sm.data.keys() if not sm.all_checks([s, ])]
  msg = ', '.join(bs[:4])  # can't fit too many on one line
  return NoEntryAlert(msg, alert_text_1='Communication Issue Between Processes')


def camera_malfunction_alert(CP: car.CarParams, CS: car.CarState, sm: messaging.SubMaster, metric: bool, soft_disable_time: int, personality) -> Alert:
  all_cams = ('narrowRoadCameraState', 'cabinCameraState', 'wideRoadCameraState')
  bad_cams = [s.replace('State', '') for s in all_cams if s in sm.data.keys() and not sm.all_checks([s, ])]
  return NormalPermanentAlert('Camera Malfunction', ', '.join(bad_cams))


def calibration_invalid_alert(CP: car.CarParams, CS: car.CarState, sm: messaging.SubMaster, metric: bool, soft_disable_time: int, personality) -> Alert:
  rpy = sm['extrinsicsCalibration'].rpyCalib
  yaw = math.degrees(rpy[2] if len(rpy) == 3 else math.nan)
  pitch = math.degrees(rpy[1] if len(rpy) == 3 else math.nan)
  angles = f'Remount Device (Pitch: {pitch:.1f}°, Yaw: {yaw:.1f}°)'
  return NormalPermanentAlert('Calibration Invalid', angles)


def paramsd_invalid_alert(CP: car.CarParams, CS: car.CarState, sm: messaging.SubMaster, metric: bool, soft_disable_time: int, personality) -> Alert:
  if not sm['vehicleParameters'].angleOffsetValid:
    angle_offset_deg = sm['vehicleParameters'].angleOffsetDeg
    title = 'Steering misalignment detected'
    text = f'Angle offset too high (Offset: {angle_offset_deg:.1f}°)'
  elif not sm['vehicleParameters'].steerRatioValid:
    steer_ratio = sm['vehicleParameters'].steerRatio
    title = 'Steer ratio mismatch'
    text = f'Steering rack geometry may be off (Ratio: {steer_ratio:.1f})'
  elif not sm['vehicleParameters'].stiffnessFactorValid:
    stiffness_factor = sm['vehicleParameters'].stiffnessFactor
    title = 'Abnormal tire stiffness'
    text = f'Check tires, pressure, or alignment (Factor: {stiffness_factor:.1f})'
  else:
    return NoEntryAlert('paramsd Temporary Error')

  return NoEntryAlert(alert_text_1=title, alert_text_2=text)

def overheat_alert(CP: car.CarParams, CS: car.CarState, sm: messaging.SubMaster, metric: bool, soft_disable_time: int, personality) -> Alert:
  cpu = max(sm['deviceState'].cpuTempC, default=0.)
  gpu = max(sm['deviceState'].gpuTempC, default=0.)
  temp = max((cpu, gpu, sm['deviceState'].memoryTempC))
  return NormalPermanentAlert('System Overheated', f'{temp:.0f} °C')


def low_memory_alert(CP: car.CarParams, CS: car.CarState, sm: messaging.SubMaster, metric: bool, soft_disable_time: int, personality) -> Alert:
  return NormalPermanentAlert('Low Memory', f"Used: {sm['deviceState'].memoryUsagePercent}%")


def high_cpu_usage_alert(CP: car.CarParams, CS: car.CarState, sm: messaging.SubMaster, metric: bool, soft_disable_time: int, personality) -> Alert:
  x = max(sm['deviceState'].cpuUsagePercent, default=0.)
  return NormalPermanentAlert('High CPU Usage', f'Used: {x}%')


def modeld_lagging_alert(CP: car.CarParams, CS: car.CarState, sm: messaging.SubMaster, metric: bool, soft_disable_time: int, personality) -> Alert:
  return NormalPermanentAlert('Driving Model Lagging', f"Frames Dropped: {sm['modelV2'].frameDropPerc:.1f}%")


def joystick_alert(CP: car.CarParams, CS: car.CarState, sm: messaging.SubMaster, metric: bool, soft_disable_time: int, personality) -> Alert:
  gb = sm['carControl'].actuators.accel / 4.
  steer = sm['carControl'].actuators.torque
  vals = f'Gas: {round(gb * 100.0)}%, Steer: {round(steer * 100.0)}%'
  return NormalPermanentAlert('Joystick Mode', vals)


def longitudinal_maneuver_alert(CP: car.CarParams, CS: car.CarState, sm: messaging.SubMaster, metric: bool, soft_disable_time: int, personality) -> Alert:
  ad = sm['alertDebug']
  audible_alert = AudibleAlert.prompt if 'Active' in ad.alertText1 else AudibleAlert.none
  alert_status = AlertStatus.userPrompt if 'Active' in ad.alertText1 else AlertStatus.normal
  alert_size = AlertSize.mid if ad.alertText2 else AlertSize.small
  return Alert(ad.alertText1, ad.alertText2,
               alert_status, alert_size,
               Priority.LOW, VisualAlert.none, audible_alert, 0.2)


def personality_changed_alert(CP: car.CarParams, CS: car.CarState, sm: messaging.SubMaster, metric: bool, soft_disable_time: int, personality) -> Alert:
  personality = str(personality).title()
  personality_cn = ""
  if personality == "Aggressive":
    personality_cn = 'Aggressive'
  elif personality == "Standard":
    personality_cn = 'Normal'
  elif personality == "Relaxed":
    personality_cn = 'Relaxed'
  return NormalPermanentAlert(f'Driving Personality: {personality_cn}', duration=1.5)


def invalid_lkas_setting_alert(CP: car.CarParams, CS: car.CarState, sm: messaging.SubMaster, metric: bool, soft_disable_time: int, personality) -> Alert:
  text = 'Toggle stock LKAS on or off to engage'
  if CP.brand == "tesla":
    text = 'Switch to Traffic-Aware Cruise Control to engage'
  elif CP.brand == "mazda":
    text = "Enable your car's LKAS to engage"
  elif CP.brand == "nissan":
    text = "Disable your car's stock LKAS to engage"
  return NormalPermanentAlert('Invalid LKAS setting', text)



def nnff_load_alert(model_name: str, fuzzy: bool) -> Alert:
  """One-shot notice naming the NNFF torque model card picked at boot.

  fuzzy means the model file matched this car's fingerprint only approximately
  (see nnlc.get_nn_model_path), so the driver should know the tune is a
  substitute rather than the exact one.
  """
  text = f'{model_name} (Fuzzy Model)' if fuzzy else model_name
  return Alert('NNFF Torque Model Loaded', text, AlertStatus.userPrompt, AlertSize.mid,
               Priority.LOW, VisualAlert.none, AudibleAlert.prompt, 6.0)


def can_error_alert(CP: car.CarParams, CS: car.CarState, sm: messaging.SubMaster, metric: bool, soft_disable_time: int, personality) -> Alert:
  # cp's camera-SCC hint (selfdrived/events.py car_parser_result): on a Hyundai whose
  # fingerprint has no CAMERA_SCC flag and whose HyundaiCameraSCC toggle is off, a canError
  # is often the camera-bus SCC that nobody told openpilot about, so name the fix instead of
  # the symptom. Gated on HyundaiCameraSccHint (BOOL, default off — no other behaviour
  # changes); every non-Hyundai car, this repo's Toyota included, always gets the plain text.
  if (CP.brand == "hyundai" and not (CP.flags & HyundaiFlags.CAMERA_SCC)
      and Params().get_int("HyundaiCameraSCC") == 0 and read_bool(Params(), "HyundaiCameraSccHint")):
    return Alert(
      'CAN Error: Enable CameraSCC',
      'SCC Detected on Camera Bus',
      AlertStatus.normal, AlertSize.mid,
      Priority.LOW, VisualAlert.none, AudibleAlert.none, 1., creation_delay=1.)
  return Alert(
    'CAN Error: Check Connections',
    "",
    AlertStatus.normal, AlertSize.small,
    Priority.LOW, VisualAlert.none, AudibleAlert.none, 1., creation_delay=1.)


EVENTS: dict[int, dict[str, Alert | AlertCallbackType]] = {
  # ********** events with no alerts **********

  EventName.noGps: {},
  EventName.stockFcw: {},

  # ********** events only containing alerts displayed in all states **********

  EventName.joystickDebug: {
    ET.WARNING: joystick_alert,
    ET.PERMANENT: NormalPermanentAlert('Joystick Mode'),
  },

  EventName.longitudinalManeuver: {
    ET.WARNING: longitudinal_maneuver_alert,
    ET.PERMANENT: NormalPermanentAlert('Longitudinal Maneuver Mode',
                                       'Ensure Road Ahead Is Clear'),
  },

  EventName.bigModelLoading: {
    ET.NO_ENTRY: NoEntryAlert("Driving Model Loading"),
  },

  EventName.bigModelFailed: {
    ET.PERMANENT: NormalPermanentAlert("Big Model Failed ", "Restart the car to retry,\nsmall model is still available", duration=20.),
  },

  EventName.lateralManeuver: {
    ET.WARNING: longitudinal_maneuver_alert,
    ET.PERMANENT: NormalPermanentAlert('Lateral Maneuver Mode'),
  },

  EventName.selfdriveInitializing: {
    ET.NO_ENTRY: NoEntryAlert('System Initializing'),
  },

  # cp impact dashcam: the global UI renders the cancellable countdown, including over settings.
  EventName.impactDetected: {
    ET.PERMANENT: Alert("", "", AlertStatus.normal, AlertSize.none, Priority.LOW,
                        VisualAlert.none, AudibleAlert.prompt, 0.2),
  },
  EventName.impactDashcamReboot: {
    ET.IMMEDIATE_DISABLE: ImmediateDisableAlert('Reboot to Dashcam Mode'),
    ET.NO_ENTRY: NoEntryAlert('Dashcam Mode'),
    ET.PERMANENT: NormalPermanentAlert('Reboot to Dashcam Mode', priority=Priority.LOW),
  },

  EventName.startup: {
    ET.PERMANENT: StartupAlert('Always Be Ready to Take Control')
  },

  EventName.startupMaster: {
    ET.PERMANENT: startup_master_alert,
  },

  EventName.startupNoControl: {
    ET.PERMANENT: StartupAlert('Dashcam Mode Only'),
    ET.NO_ENTRY: NoEntryAlert('Dashcam Mode Only'),
  },

  EventName.startupNoCar: {
    ET.PERMANENT: StartupAlert('Dashcam Mode Unsupported for Vehicle'),
  },

  EventName.startupNoSecOcKey: {
    ET.PERMANENT: NormalPermanentAlert('Dashcam Mode Only',
                                       'Safety Key Unavailable',
                                       priority=Priority.HIGH),
  },

  EventName.dashcamMode: {
    ET.PERMANENT: NormalPermanentAlert('Dashcam Mode Only',
                                       priority=Priority.LOWEST),
  },

  EventName.invalidLkasSetting: {
    ET.PERMANENT: invalid_lkas_setting_alert,
    ET.NO_ENTRY: NoEntryAlert('Lane Keeping Assist System (LKAS) Setting Invalid'),
  },

  # Macan(MLB) 适配：非 pcm 车 OP enabled 但原厂巡航已退出（TSK_04=0）时恢复 USER_DISABLE——
  # OP 立即跟随原厂退出。否则 panda 经 TSK_04 无条件 pcm_cruise_check 撤 controls_allowed 后，
  # selfdrived mismatch_counter 200 帧触发 controlsMismatch（00000041 seg5/7/10/12/15 共5次实锤）。
  # 阈值见 selfdrived.py cruise_mismatch_counter（6s→1s，须 < panda 的 2s）。
  EventName.cruiseMismatch: {
    ET.USER_DISABLE: EngagementAlert(AudibleAlert.disengage),
  },

  # openpilot doesn't recognize the car. This switches openpilot into a
  # read-only mode. This can be solved by adding your fingerprint.
  # See https://github.com/commaai/openpilot/wiki/Fingerprinting for more information
  EventName.carUnrecognized: {
    ET.PERMANENT: NormalPermanentAlert('Dashcam Mode Only',
                                       'Vehicle Not Recognized',
                                       priority=Priority.LOWEST),
  },

  EventName.aeb: {
    ET.PERMANENT: Alert(
      'BRAKE!',
      'Emergency Braking: Possible Collision',
      AlertStatus.critical, AlertSize.full,
      Priority.HIGHEST, VisualAlert.fcw, AudibleAlert.none, 2.),
    ET.NO_ENTRY: NoEntryAlert('AEB: Possible Collision'),
  },

  EventName.stockAeb: {
    ET.PERMANENT: Alert(
      'BRAKE!',
      'Stock AEB: Possible Collision',
      AlertStatus.critical, AlertSize.full,
      Priority.HIGHEST, VisualAlert.fcw, AudibleAlert.none, 2.),
    ET.NO_ENTRY: NoEntryAlert('Stock AEB: Possible Collision'),
  },

  EventName.stockLkas: {
    ET.NO_ENTRY: NoEntryAlert('Stock LKAS: Lane Departure Detection'),
  },

  EventName.fcw: {
    ET.PERMANENT: Alert(
      'BRAKE!',
      'Possible Collision',
      AlertStatus.critical, AlertSize.full,
      Priority.HIGHEST, VisualAlert.fcw, AudibleAlert.warningSoft, 2.),
  },

  EventName.ldw: {
    ET.PERMANENT: Alert(
      'Lane Departure Detected',
      "",
      AlertStatus.userPrompt, AlertSize.small,
      Priority.LOW, VisualAlert.ldw, AudibleAlert.prompt, 3.),
  },

  # ********** events only containing alerts that display while engaged **********

  EventName.steerTempUnavailableSilent: {
    ET.WARNING: Alert(
      'Steer Temporarily Unavailable',
      "",
      AlertStatus.userPrompt, AlertSize.small,
      Priority.LOW, VisualAlert.steerRequired, AudibleAlert.prompt, 1.8),
  },

  EventName.driverDistracted1: {
    ET.PERMANENT: Alert(
      'Pay Attention',
      "",
      AlertStatus.normal, AlertSize.small,
      Priority.LOW, VisualAlert.none, AudibleAlert.preAlert, .1),
  },

  EventName.driverDistracted2: {
    ET.PERMANENT: Alert(
      'Pay Attention',
      'Driver Distracted',
      AlertStatus.userPrompt, AlertSize.mid,
      Priority.MID, VisualAlert.steerRequired, AudibleAlert.promptDistracted, .1),
  },

  EventName.driverDistracted3: {
    ET.PERMANENT: Alert(
      'DISENGAGE IMMEDIATELY',
      'Driver Distracted',
      AlertStatus.critical, AlertSize.full,
      Priority.HIGH, VisualAlert.steerRequired, AudibleAlert.warningImmediate, .1),
  },

  EventName.driverUnresponsive1: {
    ET.PERMANENT: Alert(
      'Touch Steering Wheel: Face Not Detected',
      "",
      AlertStatus.normal, AlertSize.small,
      Priority.LOW, VisualAlert.steerRequired, AudibleAlert.none, .1),
  },

  EventName.driverUnresponsive2: {
    ET.PERMANENT: Alert(
      'Touch Steering Wheel',
      'Driver Unresponsive',
      AlertStatus.userPrompt, AlertSize.mid,
      Priority.MID, VisualAlert.steerRequired, AudibleAlert.promptDistracted, .1),
  },

  EventName.driverUnresponsive3: {
    ET.PERMANENT: Alert(
      'DISENGAGE IMMEDIATELY',
      'Driver Unresponsive',
      AlertStatus.critical, AlertSize.full,
      Priority.HIGH, VisualAlert.steerRequired, AudibleAlert.warningImmediate, .1),
  },

  EventName.manualRestart: {
    ET.WARNING: Alert(
      'Take Control',
      'Continue Driving Manually',
      AlertStatus.userPrompt, AlertSize.mid,
      Priority.LOW, VisualAlert.none, AudibleAlert.none, .2),
  },

  EventName.resumeRequired: {
    ET.WARNING: Alert(
      'Press Resume to Exit Stop State',
      "",
      AlertStatus.userPrompt, AlertSize.small,
      Priority.LOW, VisualAlert.none, AudibleAlert.none, .2),
  },

  EventName.belowSteerSpeed: {
    ET.WARNING: below_steer_speed_alert,
  },

  EventName.preLaneChangeLeft: {
    ET.WARNING: Alert(
      'Confirm Safe Before Left Lane Change',
      "",
      AlertStatus.normal, AlertSize.small,
      Priority.LOW, VisualAlert.none, AudibleAlert.none, .1),
  },

  EventName.preLaneChangeRight: {
    ET.WARNING: Alert(
      'Confirm Safe Before Right Lane Change',
      "",
      AlertStatus.normal, AlertSize.small,
      Priority.LOW, VisualAlert.none, AudibleAlert.none, .1),
  },

  EventName.laneChangeBlocked: {
    ET.WARNING: Alert(
      'Blind Spot Vehicle Detected',
      "",
      AlertStatus.userPrompt, AlertSize.small,
      Priority.LOW, VisualAlert.none, AudibleAlert.prompt, .1),
  },

  EventName.laneChange: {
    ET.WARNING: Alert(
      'Changing Lanes',
      "",
      AlertStatus.normal, AlertSize.small,
      Priority.LOW, VisualAlert.none, AudibleAlert.none, .1),
  },

  EventName.steerSaturated: {
    ET.WARNING: Alert(
      'Please Take Control',
      'Steering Exceeds Limit',
      AlertStatus.userPrompt, AlertSize.mid,
      Priority.LOW, VisualAlert.steerRequired, AudibleAlert.promptRepeat, 2.),
  },

  # Thrown when the fan is driven at >50% but is not rotating
  EventName.fanMalfunction: {
    ET.PERMANENT: NormalPermanentAlert('Fan Malfunction', 'Likely Hardware Issue'),
  },

  # Camera is not outputting frames
  EventName.cameraMalfunction: {
    ET.PERMANENT: camera_malfunction_alert,
    ET.SOFT_DISABLE: soft_disable_alert('Camera Malfunction'),
    ET.NO_ENTRY: NoEntryAlert('Camera Malfunction: Restart Device'),
  },
  # Camera framerate too low
  EventName.cameraFrameRate: {
    ET.PERMANENT: NormalPermanentAlert('Low Camera Frame Rate', 'Restart Device'),
    ET.SOFT_DISABLE: soft_disable_alert('Low Camera Frame Rate'),
    ET.NO_ENTRY: NoEntryAlert('Low Camera Frame Rate: Restart Device'),
  },

  # Unused

  EventName.locationdTemporaryError: {
    ET.NO_ENTRY: NoEntryAlert('locationd Temporary Error'),
    ET.SOFT_DISABLE: soft_disable_alert('locationd Temporary Error'),
  },

  # openpilot tries to learn certain parameters about your car by observing
  # how the car behaves to steering inputs from both human and openpilot driving.
  # This includes:
  # - steer ratio: gear ratio of the steering rack. Steering angle divided by tire angle
  # - tire stiffness: how much grip your tires have
  # - angle offset: most steering angle sensors are offset and measure a non zero angle when driving straight
  # This alert is thrown when any of these values exceed a sanity check. This can be caused by
  # bad alignment or bad sensor data. If this happens consistently consider creating an issue on GitHub
  EventName.paramsdTemporaryError: {
    ET.NO_ENTRY: paramsd_invalid_alert,
    ET.SOFT_DISABLE: soft_disable_alert('paramsd Temporary Error'),
  },

  # ********** events that affect controls state transitions **********

  EventName.pcmEnable: {
    ET.ENABLE: EngagementAlert(AudibleAlert.engage),
  },

  EventName.buttonEnable: {
    ET.ENABLE: EngagementAlert(AudibleAlert.engage),
  },

  EventName.pcmDisable: {
    ET.USER_DISABLE: EngagementAlert(AudibleAlert.disengage),
  },

  EventName.startupCruiseCanceled: {
    ET.PERMANENT: Alert(
      "Cruise Canceled",
      "Cruise was on at startup",
      AlertStatus.normal, AlertSize.mid,
      Priority.MID, VisualAlert.none, AudibleAlert.disengage, 3.),
  },

  EventName.buttonCancel: {
    ET.USER_DISABLE: EngagementAlert(AudibleAlert.disengage),
    ET.NO_ENTRY: NoEntryAlert('Cancel Button Pressed'),
  },

  EventName.brakeHold: {
    ET.WARNING: Alert(
      'Press Resume to Release Brake Hold',
      "",
      AlertStatus.userPrompt, AlertSize.small,
      Priority.LOW, VisualAlert.none, AudibleAlert.none, .2),
  },

  EventName.parkBrake: {
    ET.USER_DISABLE: EngagementAlert(AudibleAlert.disengage),
    ET.NO_ENTRY: NoEntryAlert('Park Brake Engaged'),
  },

  EventName.pedalPressed: {
    ET.USER_DISABLE: EngagementAlert(AudibleAlert.disengage),
    ET.NO_ENTRY: NoEntryAlert('Pedal Pressed',
                              visual_alert=VisualAlert.brakePressed),
  },

  EventName.steerDisengage: {
    ET.USER_DISABLE: EngagementAlert(AudibleAlert.disengage),
    ET.NO_ENTRY: NoEntryAlert('Steering Wheel Turned'),
  },

  # Macan(MLB) 适配：停车踩刹车+按SET 原为 PRE_ENABLE → 进入 preEnabled 预激活态
  # （carControl.enabled=True）与 panda 拒控（TSK_04=0）冲突 → mismatch_counter 2秒后
  # controlsMismatch 报警（0000003e seg4 @268s 实锤）。且 Macan 激活门槛 30km/h，
  # preEnabled 窗口过长无意义。改为 NO_ENTRY：停车按 SET 直接挡在 disabled，不激活不报警。
  EventName.preEnableStandstill: {
    ET.PRE_ENABLE: Alert(
      'Release Brake to Engage',
      "",
      AlertStatus.normal, AlertSize.small,
      Priority.LOWEST, VisualAlert.none, AudibleAlert.none, .1, creation_delay=1.),
  },

  EventName.gasPressedOverride: {
    ET.OVERRIDE_LONGITUDINAL: Alert(
      "",
      "",
      AlertStatus.normal, AlertSize.none,
      Priority.LOWEST, VisualAlert.none, AudibleAlert.none, .1),
  },

  EventName.steerOverride: {
    ET.OVERRIDE_LATERAL: Alert(
      "",
      "",
      AlertStatus.normal, AlertSize.none,
      Priority.LOWEST, VisualAlert.none, AudibleAlert.none, .1),
  },

  EventName.wrongCarMode: {
    ET.USER_DISABLE: EngagementAlert(AudibleAlert.disengage),
    ET.NO_ENTRY: wrong_car_mode_alert,
  },

  EventName.resumeBlocked: {
    ET.NO_ENTRY: NoEntryAlert('Press Set to Engage'),
  },

  EventName.carNotReady: {
    ET.NO_ENTRY: NoEntryAlert("Car Not Ready"),
  },

  EventName.wrongCruiseMode: {
    ET.USER_DISABLE: EngagementAlert(AudibleAlert.disengage),
    ET.NO_ENTRY: NoEntryAlert('Adaptive Cruise Disabled'),
  },

  EventName.steerTempUnavailable: {
    ET.SOFT_DISABLE: soft_disable_alert('Steer Temporarily Unavailable'),
    ET.NO_ENTRY: NoEntryAlert('Steer Temporarily Unavailable'),
  },

  EventName.steerTimeLimit: {
    ET.SOFT_DISABLE: soft_disable_alert('Vehicle Steering Time Limit'),
    ET.NO_ENTRY: NoEntryAlert('Vehicle Steering Time Limit'),
  },

  EventName.outOfSpace: {
    ET.PERMANENT: out_of_space_alert,
    ET.NO_ENTRY: NoEntryAlert('Out of Storage'),
  },

  EventName.belowEngageSpeed: {
    ET.NO_ENTRY: below_engage_speed_alert,
  },

  EventName.sensorDataInvalid: {
    ET.PERMANENT: Alert(
      'Sensor Data Invalid',
      'Likely Hardware Issue',
      AlertStatus.normal, AlertSize.mid,
      Priority.LOWER, VisualAlert.none, AudibleAlert.none, .2, creation_delay=1.),
    ET.NO_ENTRY: NoEntryAlert('Sensor Data Invalid'),
    ET.SOFT_DISABLE: soft_disable_alert('Sensor Data Invalid'),
  },

  EventName.tooDistracted: {
    ET.NO_ENTRY: too_distracted_alert,
  },

  EventName.excessiveActuation: {
    ET.SOFT_DISABLE: soft_disable_alert('Excessive Steering Input'),
    ET.NO_ENTRY: NoEntryAlert('Excessive Steering Input'),
  },

  EventName.overheat: {
    ET.PERMANENT: overheat_alert,
    ET.SOFT_DISABLE: soft_disable_alert('System Overheated'),
    ET.NO_ENTRY: NoEntryAlert('System Overheated'),
  },

  EventName.wrongGear: {
    ET.SOFT_DISABLE: user_soft_disable_alert('Gear Not in Drive'),
    ET.NO_ENTRY: NoEntryAlert('Gear Not in Drive'),
  },

  # This alert is thrown when the calibration angles are outside of the acceptable range.
  # For example if the device is pointed too much to the left or the right.
  # Usually this can only be solved by removing the mount from the windshield completely,
  # and attaching while making sure the device is pointed straight forward and is level.
  # See https://comma.ai/setup for more information
  EventName.calibrationInvalid: {
    ET.PERMANENT: calibration_invalid_alert,
    ET.SOFT_DISABLE: soft_disable_alert('Calibration Invalid: Remount Device and Recalibrate'),
    ET.NO_ENTRY: NoEntryAlert('Calibration Invalid: Remount Device and Recalibrate'),
  },

  EventName.calibrationIncomplete: {
    ET.PERMANENT: calibration_incomplete_alert,
    ET.SOFT_DISABLE: soft_disable_alert('Calibration Incomplete'),
    ET.NO_ENTRY: NoEntryAlert('Calibration in Progress'),
  },

  EventName.calibrationRecalibrating: {
    ET.PERMANENT: calibration_incomplete_alert,
    ET.SOFT_DISABLE: soft_disable_alert('Device Remount Detected: Recalibrating'),
    ET.NO_ENTRY: NoEntryAlert('Device Remount Detected: Recalibrating'),
  },

  EventName.doorOpen: {
    ET.SOFT_DISABLE: user_soft_disable_alert('Door Open'),
    ET.NO_ENTRY: NoEntryAlert('Door Open'),
  },

  EventName.seatbeltNotLatched: {
    ET.SOFT_DISABLE: user_soft_disable_alert('Seatbelt Unfastened'),
    ET.NO_ENTRY: NoEntryAlert('Seatbelt Unfastened'),
  },

  EventName.espDisabled: {
    ET.SOFT_DISABLE: soft_disable_alert('ESC Disabled'),
    ET.NO_ENTRY: NoEntryAlert('ESC Disabled'),
  },

  EventName.lowBatteryDEPRECATED: {
    ET.SOFT_DISABLE: soft_disable_alert('Low Battery'),
    ET.NO_ENTRY: NoEntryAlert('Low Battery'),
  },

  # Different openpilot services communicate between each other at a certain
  # interval. If communication does not follow the regular schedule this alert
  # is thrown. This can mean a service crashed, did not broadcast a message for
  # ten times the regular interval, or the average interval is more than 10% too high.
  EventName.commIssue: {
    ET.SOFT_DISABLE: soft_disable_alert('Communication Issue Between Processes'),
    ET.NO_ENTRY: comm_issue_alert,
  },
  EventName.commIssueAvgFreq: {
    ET.SOFT_DISABLE: soft_disable_alert('Low IPC Rate'),
    ET.NO_ENTRY: NoEntryAlert('Low IPC Rate'),
  },

  EventName.selfdrivedLagging: {
    ET.SOFT_DISABLE: soft_disable_alert('System Lagging'),
    ET.NO_ENTRY: NoEntryAlert('selfdrive Processes Lagging: Restart Device'),
  },

  # Thrown when manager detects a service exited unexpectedly while driving
  EventName.processNotRunning: {
    ET.NO_ENTRY: process_not_running_alert,
    ET.SOFT_DISABLE: soft_disable_alert('Process Not Running'),
  },

  EventName.radarFault: {
    ET.SOFT_DISABLE: soft_disable_alert('Radar Error: Restart Car'),
    ET.NO_ENTRY: NoEntryAlert('Radar Error: Restart Car'),
  },

  EventName.radarTempUnavailable: {
    ET.SOFT_DISABLE: soft_disable_alert('Radar Temporarily Unavailable'),
    ET.NO_ENTRY: NoEntryAlert('Radar Temporarily Unavailable'),
  },

  # Carrot advisory: a measured front/corner obstacle ahead with no selected
  # lead. Warning only, with a 30 s refractory in the detector itself.
  EventName.radarStationaryLead: {
    ET.WARNING: Alert(
      'Object Ahead', 'Confirm Road Ahead and Prepare to Slow',
      AlertStatus.normal, AlertSize.mid,
      Priority.HIGH, VisualAlert.none, AudibleAlert.prompt, 2.),
  },

  # One-shot NNFF torque model notice. selfdrived rebinds this entry through
  # Events.bind_nnff_notice() once it knows the model name, which lives in
  # CarParamsSP rather than CarParams, so the callback signature cannot carry
  # it. This default only keeps the event a valid, silent placeholder.
  EventName.torqueNNLoad: {
    ET.PERMANENT: NormalPermanentAlert('NNFF Torque Model Loaded'),
  },

  # Every frame from the camera should be processed by the model. If modeld
  # is not processing frames fast enough they have to be dropped. This alert is
  # thrown when over 20% of frames are dropped.
  EventName.modeldLagging: {
    ET.SOFT_DISABLE: soft_disable_alert('Driving Model Lagging'),
    ET.NO_ENTRY: NoEntryAlert('Driving Model Lagging'),
    ET.PERMANENT: modeld_lagging_alert,
  },

  # Clustered one-frame resyncs (a few frames a second) trip the same
  # "驾驶模型滞后" text as an informational alert. The controller is not
  # starved, so this must never interrupt the drive the way modeldLagging does.
  EventName.modeldLaggingMild: {
    ET.PERMANENT: modeld_lagging_alert,
  },

  # Clustered one-frame resyncs (a few frames a second) trip the same
  # "Driving Model Lagging" text as an informational alert. The controller is
  # not starved, so this must never interrupt the drive the way modeldLagging
  # does - no SOFT_DISABLE / NO_ENTRY hook on purpose (guardrail test).
  EventName.modeldLaggingMild: {
    ET.PERMANENT: modeld_lagging_alert,
  },

  # Besides predicting the path, lane lines and lead car data the model also
  # predicts the current velocity and rotation speed of the car. If the model is
  # very uncertain about the current velocity while the car is moving, this
  # usually means the model has trouble understanding the scene. This is used
  # as a heuristic to warn the driver.
  EventName.posenetInvalid: {
    ET.SOFT_DISABLE: soft_disable_alert('Posenet Speed Invalid'),
    ET.NO_ENTRY: posenet_invalid_alert,
  },

  # When the localizer detects an acceleration of more than 40 m/s^2 (~4G) we
  # alert the driver the device might have fallen from the windshield.
  EventName.deviceFallingDEPRECATED: {
    ET.SOFT_DISABLE: soft_disable_alert('Device Fell Off Mount'),
    ET.NO_ENTRY: NoEntryAlert('Device Fell Off Mount'),
  },

  EventName.lowMemory: {
    ET.SOFT_DISABLE: soft_disable_alert('Low Memory: Restart Device'),
    ET.PERMANENT: low_memory_alert,
    ET.NO_ENTRY: NoEntryAlert('Low Memory: Restart Device'),
  },

  EventName.accFaulted: {
    ET.IMMEDIATE_DISABLE: ImmediateDisableAlert('Cruise Fault: Restart Car'),
    ET.PERMANENT: NormalPermanentAlert('Cruise Fault: Restart Car to Engage'),
    ET.NO_ENTRY: NoEntryAlert('Cruise Fault: Restart Car'),
  },

  EventName.espActive: {
    ET.SOFT_DISABLE: soft_disable_alert('ESC Active'),
    ET.NO_ENTRY: NoEntryAlert('ESC Active'),
  },

  EventName.controlsMismatch: {
    ET.IMMEDIATE_DISABLE: ImmediateDisableAlert('Controls Mismatch'),
    ET.NO_ENTRY: NoEntryAlert('Controls Mismatch'),
  },

  # Sometimes the USB stack on the device can get into a bad state
  # causing the connection to the panda to be lost
  EventName.usbErrorDEPRECATED: {
    ET.SOFT_DISABLE: soft_disable_alert('USB Error: Restart Device'),
    ET.PERMANENT: NormalPermanentAlert('USB Error: Restart Device'),
    ET.NO_ENTRY: NoEntryAlert('USB Error: Restart Device'),
  },

  # This alert can be thrown for the following reasons:
  # - No CAN data received at all
  # - CAN data is received, but some message are not received at the right frequency
  # If you're not writing a new car port, this is usually cause by faulty wiring
  EventName.canError: {
    ET.IMMEDIATE_DISABLE: ImmediateDisableAlert('CAN Error: Check Connections'),
    ET.PERMANENT: can_error_alert,
    ET.NO_ENTRY: NoEntryAlert('CAN Error: Check Connections'),
  },

  EventName.canBusMissing: {
    ET.IMMEDIATE_DISABLE: ImmediateDisableAlert('CAN Bus Disconnected'),
    ET.PERMANENT: Alert(
      'CAN Bus Disconnected: Likely Cable Fault',
      "",
      AlertStatus.normal, AlertSize.small,
      Priority.LOW, VisualAlert.none, AudibleAlert.none, 1., creation_delay=1.),
    ET.NO_ENTRY: NoEntryAlert('CAN Bus Disconnected: Check Connections'),
  },

  EventName.steerUnavailable: {
    ET.IMMEDIATE_DISABLE: ImmediateDisableAlert('LKAS Fault: Restart Car'),
    ET.PERMANENT: NormalPermanentAlert('LKAS Fault: Restart Car to Engage'),
    ET.NO_ENTRY: NoEntryAlert('LKAS Fault: Restart Car'),
  },

  EventName.reverseGear: {
    ET.PERMANENT: Alert(
      'Reversing',
      "",
      AlertStatus.normal, AlertSize.full,
      Priority.LOWEST, VisualAlert.none, AudibleAlert.none, .2, creation_delay=0.5),
    ET.USER_DISABLE: ImmediateDisableAlert('Reverse'),
    ET.NO_ENTRY: NoEntryAlert('Reverse'),
  },

  # On cars that use stock ACC the car can decide to cancel ACC for various reasons.
  # When this happens we can no long control the car so the user needs to be warned immediately.
  EventName.cruiseDisabled: {
    ET.IMMEDIATE_DISABLE: ImmediateDisableAlert('Cruise Off'),
  },

  # When the relay in the harness box opens the CAN bus between the LKAS camera
  # and the rest of the car is separated. When messages from the LKAS camera
  # are received on the car side this usually means the relay hasn't opened correctly
  # and this alert is thrown.
  EventName.relayMalfunction: {
    ET.IMMEDIATE_DISABLE: ImmediateDisableAlert('Harness Relay Fault'),
    ET.PERMANENT: NormalPermanentAlert('Harness Relay Fault', 'Check Hardware'),
    ET.NO_ENTRY: NoEntryAlert('Harness Relay Fault'),
  },

  EventName.speedTooLow: {
    ET.IMMEDIATE_DISABLE: Alert(
      'sunnypilot Cancelled',
      'Speed Too Low',
      AlertStatus.normal, AlertSize.mid,
      Priority.HIGH, VisualAlert.none, AudibleAlert.disengage, 3.),
  },

  # When the car is driving faster than most cars in the training data, the model outputs can be unpredictable.
  EventName.speedTooHigh: {
    ET.WARNING: Alert(
      'Speed Too High',
      'Model Unstable at This Speed',
      AlertStatus.userPrompt, AlertSize.mid,
      Priority.HIGH, VisualAlert.steerRequired, AudibleAlert.promptRepeat, 4.),
    ET.NO_ENTRY: NoEntryAlert('Slow Down to Engage'),
  },

  EventName.vehicleSensorsInvalid: {
    ET.IMMEDIATE_DISABLE: ImmediateDisableAlert('Vehicle Sensors Invalid'),
    ET.PERMANENT: NormalPermanentAlert('Vehicle Sensors Calibrating', 'Drive to Calibrate'),
    ET.NO_ENTRY: NoEntryAlert('Vehicle Sensors Calibrating'),
  },

  EventName.personalityChanged: {
    # 00000045 实锤：WARNING 类型在未激活时不在 current_alert_types → 停车调车距不显示提示
    # （personalityChanged 事件存在但 alert 被状态机过滤，00000045 seg1 15条事件 0 显示）。
    # 改 PERMANENT：未激活/激活都显示；事件仅变化帧存在 + duration=1.5s → 显示到期自动消失。
    ET.PERMANENT: personality_changed_alert,
  },

  EventName.userBookmark: {
    ET.PERMANENT: NormalPermanentAlert('Bookmark Saved', duration=1.5),
  },

  EventName.userBookmarkNotPaired: {
    ET.PERMANENT: NormalPermanentAlert('Device Not Paired', 'Bookmark Requires Paired Device', duration=2.0),
  },
}


if HARDWARE.get_device_type() == 'mici':
  EVENTS.update({
    EventName.driverDistracted1: {
      ET.PERMANENT: Alert(
        'Pay Attention',
        "",
        AlertStatus.normal, AlertSize.small,
        Priority.LOW, VisualAlert.none, AudibleAlert.preAlert, 2),
    },
    EventName.driverDistracted2: {
      ET.PERMANENT: Alert(
        'Pay Attention',
        'Driver Distracted',
        AlertStatus.userPrompt, AlertSize.mid,
        Priority.MID, VisualAlert.steerRequired, AudibleAlert.promptDistracted, 1),
    },
    EventName.resumeRequired: {
      ET.WARNING: Alert(
        'restore',
        "",
        AlertStatus.userPrompt, AlertSize.small,
        Priority.LOW, VisualAlert.none, AudibleAlert.none, .2),
    },
    EventName.preLaneChangeLeft: {
      ET.WARNING: Alert(
        'Turn Left',
        'Confirm Lane Change',
        AlertStatus.normal, AlertSize.mid,
        Priority.LOW, VisualAlert.none, AudibleAlert.none, .1),
    },
    EventName.preLaneChangeRight: {
      ET.WARNING: Alert(
        'Turn Right',
        'Confirm Lane Change',
        AlertStatus.normal, AlertSize.mid,
        Priority.LOW, VisualAlert.none, AudibleAlert.none, .1),
    },
    EventName.laneChangeBlocked: {
      ET.WARNING: Alert(
        'Vehicle in Blind Spot',
        "",
        AlertStatus.userPrompt, AlertSize.small,
        Priority.LOW, VisualAlert.none, AudibleAlert.prompt, .1),
    },
    EventName.steerSaturated: {
      ET.WARNING: Alert(
        'Take Over',
        'Steer Beyond Limit',
        AlertStatus.userPrompt, AlertSize.mid,
        Priority.LOW, VisualAlert.steerRequired, AudibleAlert.promptRepeat, 2.),
    },
    EventName.calibrationIncomplete: {
      ET.PERMANENT: calibration_incomplete_alert,
      ET.SOFT_DISABLE: soft_disable_alert('Calibration Incomplete'),
      ET.NO_ENTRY: NoEntryAlert('Calibrating'),
    },
    EventName.reverseGear: {
      ET.PERMANENT: Alert(
        'Reverse',
        "",
        AlertStatus.normal, AlertSize.full,
        Priority.LOWEST, VisualAlert.none, AudibleAlert.none, .2, creation_delay=0.5),
      ET.USER_DISABLE: ImmediateDisableAlert('Reverse'),
      ET.NO_ENTRY: NoEntryAlert('Reverse'),
    },
  })


if __name__ == '__main__':
  # print all alerts by type and priority
  from openpilot.cereal.services import SERVICE_LIST
  from collections import defaultdict

  event_names = {v: k for k, v in EventName.schema.enumerants.items()}
  alerts_by_type: dict[str, dict[Priority, list[str]]] = defaultdict(lambda: defaultdict(list))

  CP = car.CarParams.new_message()
  CS = car.CarState.new_message()
  sm = messaging.SubMaster(list(SERVICE_LIST.keys()))

  for i, alerts in EVENTS.items():
    for et, alert in alerts.items():
      if not isinstance(alert, Alert):
        alert = alert(CP, CS, sm, False, 1, log.LongitudinalPersonality.standard)
      alerts_by_type[et][alert.priority].append(event_names[i])

  all_alerts: dict[str, list[tuple[Priority, list[str]]]] = {}
  for et, priority_alerts in alerts_by_type.items():
    all_alerts[et] = sorted(priority_alerts.items(), key=lambda x: x[0], reverse=True)

  for status, evs in sorted(all_alerts.items(), key=lambda x: x[0]):
    print(f"**** {status} ****")
    for p, alert_list in evs:
      print(f"  {repr(p)}:")
      print("   ", ', '.join(alert_list), "\n")
