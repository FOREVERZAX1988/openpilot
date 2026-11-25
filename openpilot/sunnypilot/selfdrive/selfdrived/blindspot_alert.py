"""Blind-spot audible advisory, ported from StarPilot (starpilot/audio/blindspot_alert.py).

Optional sound-only presentation for the OEM blind-spot data that already
reaches carState (`leftBlindspot` / `rightBlindspot`, populated by opendbc for
cars whose BSD CAN messages are decoded). It never changes lane-change or
control authority: a car without BSD signals keeps both fields False, so the
matching condition below never holds and the module stays completely silent.

Three opt-in parameters mirror StarPilot exactly:
  * LoudBlindspotAlert                 - replace the blocked-lane-change alert
                                         ("laneChangeBlocked/warning") with the
                                         blind-spot alert while a lane change is
                                         actually blocked. Never muted at standstill.
  * LoudBlindspotAlertWhenDisengaged   - standing advisory while lateral control
                                         is off and the driver signals toward a
                                         blind spot occupied on the same side.
  * LoudBlindspotAlertMuteAtStandstill - mutes only the disengaged advisory
                                         while parked/stopped.

The returned Alert is injected into the AlertManager by selfdrived
(update_alerts), not through the events map: the advisory has to reach the
driver independent of the engagement WARNING filter, and the SP event-name
enum (cereal custom.capnp OnroadEventSP.EventName) is frozen for this fork.
"""

from openpilot.sunnypilot.selfdrive.selfdrived.events_base import Alert, AlertSize, AlertStatus, AudibleAlert, Priority, VisualAlert

KEYS = ("LoudBlindspotAlert", "LoudBlindspotAlertWhenDisengaged", "LoudBlindspotAlertMuteAtStandstill")
ALERT_TYPE = "blindSpotAdvisory"

CAR_STATE_MAX_AGE_NS = 200_000_000
DEVICE_STATE_MAX_AGE_NS = 2_000_000_000
CAR_CONTROL_MAX_AGE_NS = 200_000_000
STANDSTILL_VEGO = 0.5  # m/s; same threshold StarPilot uses for the standstill mute


def blindspot_alert(cs, sm, *, loud: bool, without_lateral: bool, lane_change_blocked: bool,
                    mute_at_standstill: bool = False, now_ns: int = 0, car_ns: int = 0):
  """The advisory for this frame, or None when every gate says stay silent.

  Defensive on purpose: any missing field, stale or invalid input (carState
  older than 200 ms, deviceState older than 2 s, carControl older than 200 ms,
  unhealthy services, CAN timeout) returns None, so a car without BSD signals
  or with flaky inputs is indistinguishable from the params being off.
  """
  if not loud and not without_lateral:
    return None
  try:
    if not 0 < car_ns <= now_ns or now_ns - car_ns > CAR_STATE_MAX_AGE_NS:
      return None
    if not sm['deviceState'].started or not sm.all_checks(['deviceState', 'carControl']):
      return None
    if any(not 0 < int(sm.logMonoTime[key]) <= now_ns or now_ns - int(sm.logMonoTime[key]) > limit
           for key, limit in (('deviceState', DEVICE_STATE_MAX_AGE_NS), ('carControl', CAR_CONTROL_MAX_AGE_NS))):
      return None
    if not cs.canValid or cs.canTimeout:
      return None
    matching_signal = (bool(cs.leftBlinker) != bool(cs.rightBlinker) and
                       (cs.leftBlinker and cs.leftBlindspot or cs.rightBlinker and cs.rightBlindspot))
    standstill = bool(getattr(cs, 'standstill', False) or float(getattr(cs, 'vEgo', 1.0)) < STANDSTILL_VEGO)
    if not (loud and lane_change_blocked or
            without_lateral and not sm['carControl'].latActive and matching_signal and
            not (mute_at_standstill and standstill)):
      return None
  except (AttributeError, KeyError, TypeError, ValueError, OverflowError):
    return None
  alert = Alert("盲区检测到车辆", "", AlertStatus.userPrompt, AlertSize.small,
                Priority.LOW, VisualAlert.none, AudibleAlert.warningSoft, .1)
  alert.alert_type, alert.event_type = ALERT_TYPE, ALERT_TYPE
  return alert
