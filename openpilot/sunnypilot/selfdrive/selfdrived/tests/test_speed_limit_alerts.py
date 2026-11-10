"""
Copyright (c) 2026-, Zeph Leggett.

This file is part of zoompilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.

The speed limit assist prompt and its activation notice name the speed the car is going to,
not just that a limit exists.
"""
import unittest
from unittest import mock

from openpilot.cereal import custom, messaging
from opendbc.car import structs
from openpilot.common.constants import CV
from openpilot.sunnypilot.selfdrive.selfdrived import events_zp
from openpilot.sunnypilot.selfdrive.selfdrived.events import EVENTS_SP
from openpilot.sunnypilot.selfdrive.selfdrived.events_base import ET, AlertSize

EventNameSP = custom.OnroadEventSP.EventName


def _alert(event, target: float, set_speed: float, metric: bool = False, pcm_long: bool = False, adapting: bool = False):
  """target and set_speed in display units; the resolver carries m/s, carState kph."""
  to_ms = CV.KPH_TO_MS if metric else CV.MPH_TO_MS
  lp_sp = messaging.new_message('longitudinalPlanSP').longitudinalPlanSP
  lp_sp.speedLimit.resolver.speedLimitFinalLast = target * to_ms
  lp_sp.speedLimit.assist.vTarget = target * to_ms
  if adapting:
    lp_sp.speedLimit.assist.state = custom.LongitudinalPlanSP.SpeedLimit.AssistState.adapting
  sm = {
    'longitudinalPlanSP': lp_sp,
    'controlsState': messaging.new_message('controlsState').controlsState,
    'carStateSP': messaging.new_message('carStateSP').carStateSP,
  }
  CP = structs.CarParams()
  CP.openpilotLongitudinalControl = pcm_long
  CP.pcmCruise = pcm_long
  CS = structs.CarState()
  CS.vCruiseCluster = set_speed * to_ms * CV.MS_TO_KPH
  return EVENTS_SP[event][ET.WARNING](CP, CS, sm, metric, 0, None)


class TestPreActivePrompt(unittest.TestCase):
  def _mici(self):
    patcher = mock.patch.object(events_zp, 'IS_MICI', True)
    patcher.start()
    self.addCleanup(patcher.stop)

  def test_names_the_target(self):
    self._mici()
    for set_speed, text in [(40, 'Press + to Set\n45 mph'), (55, 'Press - to Set\n45 mph')]:
      with self.subTest(set_speed=set_speed):
        self.assertEqual(_alert(EventNameSP.speedLimitPreActive, 45, set_speed).alert_text_1, text)

  def test_metric(self):
    self._mici()
    self.assertEqual(_alert(EventNameSP.speedLimitPreActive, 80, 100, metric=True).alert_text_1, 'Press - to Set\n80 km/h')

  def test_tizi_draws_the_sign_instead(self):
    self.assertEqual(_alert(EventNameSP.speedLimitPreActive, 45, 40).alert_size, AlertSize.none)


class TestActiveNotice(unittest.TestCase):
  def _mici(self):
    patcher = mock.patch.object(events_zp, 'IS_MICI', True)
    patcher.start()
    self.addCleanup(patcher.stop)

  def test_names_the_speed_it_settles_at(self):
    for target, set_speed, speed in [
      (45, 60, 45),  # down to the limit
      (65, 60, 60),  # a limit over the set speed settles at the set speed
    ]:
      with self.subTest(target=target, set_speed=set_speed):
        alert = _alert(EventNameSP.speedLimitActive, target, set_speed)
        self.assertEqual(alert.alert_text_1, f'Adjusting to Speed Limit {speed} mph')
        self.assertEqual(alert.alert_size, AlertSize.small)

  def test_metric(self):
    self.assertEqual(_alert(EventNameSP.speedLimitActive, 80, 100, metric=True).alert_text_1, 'Adjusting to Speed Limit 80 km/h')

  def test_below_the_confirm_threshold_says_the_same(self):
    self.assertEqual(_alert(EventNameSP.speedLimitChanged, 35, 45).alert_text_1, 'Adjusting to Speed Limit 35 mph')

  def test_mici_keeps_the_unit_with_its_number(self):
    self._mici()
    self.assertEqual(_alert(EventNameSP.speedLimitActive, 45, 60).alert_text_1, 'Adjusting to Speed Limit\n45 mph')

  def test_unset_set_speed_falls_back_to_the_target(self):
    # vCruiseCluster 0 falls back to controlsState's vCruise, 0 when nothing published
    self.assertEqual(_alert(EventNameSP.speedLimitActive, 45, 0).alert_text_1, 'Adjusting to Speed Limit 45 mph')


class TestGasCancel(unittest.TestCase):
  """pcm long applies a lower limit unasked; while it slows the car the notice says the gas declines it."""

  def _mici(self):
    patcher = mock.patch.object(events_zp, 'IS_MICI', True)
    patcher.start()
    self.addCleanup(patcher.stop)

  def test_slowing_offers_the_gas(self):
    alert = _alert(EventNameSP.speedLimitChanged, 20, 60, pcm_long=True, adapting=True)
    self.assertEqual(alert.alert_text_1, 'Adjusting to Speed Limit 20 mph')
    self.assertEqual(alert.alert_text_2, 'Press Gas to Maintain Current Speed')
    self.assertEqual(alert.alert_size, AlertSize.mid)  # tizi draws the second line only on mid

  def test_mici_keeps_both_lines(self):
    self._mici()
    alert = _alert(EventNameSP.speedLimitChanged, 20, 60, pcm_long=True, adapting=True)
    self.assertEqual(alert.alert_text_1, 'Adjusting to Speed Limit\n20 mph')
    self.assertEqual(alert.alert_text_2, 'Press Gas to Maintain Current Speed')

  def test_not_slowing_stays_small(self):
    """A raise, or a limit the car is already at: the gas has nothing to decline."""
    alert = _alert(EventNameSP.speedLimitActive, 45, 60, pcm_long=True)
    self.assertEqual(alert.alert_text_2, "")
    self.assertEqual(alert.alert_size, AlertSize.small)

  def test_arbiter_cars_get_no_gas_line(self):
    """ICBM and non-pcm cars confirm with the buttons, and the gas declines nothing there."""
    self.assertEqual(_alert(EventNameSP.speedLimitChanged, 20, 60, adapting=True).alert_text_2, "")
