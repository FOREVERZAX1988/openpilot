"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
"""A car whose PCM owns the ACC set speed must follow the car, not carrot's own value.

opendbc's Toyota carstate only ever emits `lkas` (LFA) and `gapAdjustCruise` (distance)
button events - the ACC accel/decel/resume/set presses are consumed by the PCM, which
keeps its own set speed on the cluster. Measured on a TOYOTA_WILDLANDER_PHEV
(CarParams pcmCruise=True, openpilotLongitudinalControl=True,
CarParamsSP.pcmCruiseSpeed=True): 16 consecutive route segments contained ZERO cruise
button events, while `cruiseState.speed` moved with the steering wheel.

`VCruiseCarrot` only read the car's set speed when the `SpeedFromPCM` param was 1
(default 0), so in the default configuration the cluster moved but `v_cruise_kph` stayed
on openpilot's internal value (clamped to >= 30) and, with openpilot longitudinal on,
openpilot actually controlled to it. Reported as "cluster went to 80, openpilot still
showed 40".

Requires the installed `opendbc` package (so: device or CI, not a bare PC checkout).
CarState / CS_SP stand-ins are plain objects rather than capnp messages: loading
car.capnp and custom.capnp in one process aborts pycapnp, which is why the stand-ins
mirror the real field names instead.
"""
import unittest
from types import SimpleNamespace

from openpilot.common.constants import CV
from openpilot.selfdrive.car.cruise import GearShifter, VCruiseCarrot, V_CRUISE_UNSET


class _CruiseState:
  def __init__(self, available, speed_kph, standstill):
    self.available = available
    self.enabled = available
    self.standstill = standstill
    self.speed = speed_kph * CV.KPH_TO_MS
    self.speedCluster = self.speed


class _CarState:
  def __init__(self, speed_kph, available=True, standstill=False):
    self.vEgo = 15.0
    self.vEgoCluster = 15.0
    self.aEgo = 0.0
    self.steeringAngleDeg = 0.0
    self.steeringPressed = False
    self.canValid = True
    self.canTimeout = False
    self.gasPressed = False
    self.brakePressed = False
    self.brakeHoldActive = False
    self.parkingBrake = False
    self.gearShifter = GearShifter.drive
    self.cruiseState = _CruiseState(available, speed_kph, standstill)
    self.pcmCruiseGap = 0
    self.leftBlinker = False
    self.rightBlinker = False
    self.buttonEvents = []


def _make_sm():
  services = {
    'carControl': SimpleNamespace(enabled=True),
    'carrotManSP': None,
    'longitudinalPlan': SimpleNamespace(xState=0, trafficState=0, aTarget=0.0),
    'radarState': SimpleNamespace(leadOne=SimpleNamespace(dRel=0.0, vRel=0.0, vLeadK=0.0, present=False)),
    'drivingModelData': SimpleNamespace(action=SimpleNamespace(desiredAcceleration=0.0)),
  }

  class SM:
    alive = {'longitudinalPlan': True, 'radarState': True, 'drivingModelData': True}
    valid = {'carrotManSP': False, 'carStateSP': True}
    updated: dict = {}
    frame = 0

    def __getitem__(self, key):
      return services[key]

  return SM()


def _make_helper(brand, pcm_cruise, op_long, carrot_own_kph=40.0):
  cp = SimpleNamespace(brand=brand, pcmCruise=pcm_cruise, openpilotLongitudinalControl=op_long)
  cp_sp = SimpleNamespace(pcmCruiseSpeed=True)
  helper = VCruiseCarrot(cp, cp_sp)
  # The button state machine is not what these tests cover, and its real implementation
  # writes params (LongitudinalPersonality / MyDrivingMode / ActivateCruiseAfterBrake) -
  # a test must not touch the machine it runs on. Pin its result and silence the one
  # path that could cancel cruise.
  helper._update_cruise_buttons = lambda *a, **k: carrot_own_kph
  helper._cruise_control = lambda *a, **k: None
  helper._params_count = 1  # force the parameter refresh on the first call
  return helper


class TestPcmOwnedSetSpeed(unittest.TestCase):
  def test_pcm_owns_set_speed_property(self):
    self.assertTrue(_make_helper('toyota', pcm_cruise=True, op_long=True).pcm_owns_set_speed,
                    "a pcmCruise Toyota never delivers ACC button events, so it must read the car")
    self.assertFalse(_make_helper('toyota', pcm_cruise=False, op_long=True).pcm_owns_set_speed,
                     "without pcmCruise the car has no stock set speed to read")
    self.assertFalse(_make_helper('hyundai', pcm_cruise=True, op_long=True).pcm_owns_set_speed,
                     "other brands deliver ACC button events, so carrot's own machine keeps working")

  def test_toyota_pcm_cruise_follows_the_car(self):
    helper = _make_helper('toyota', pcm_cruise=True, op_long=True)
    cs = _CarState(speed_kph=80.0)
    # The first call also runs the `cruiseState.available` rising edge, which seeds
    # v_cruise from vEgoCluster (54 kph here). Adopting the PCM's 80 must win over that.
    helper.update_v_cruise(cs, True, True, _make_sm(), SimpleNamespace())
    self.assertAlmostEqual(helper.v_cruise_kph, 80.0, places=1,
                           msg="openpilot must adopt the PCM's set speed, not keep its own")
    self.assertAlmostEqual(helper.v_cruise_cluster_kph, 80.0, places=1)
    # ... and it must keep tracking it, not just once.
    cs.cruiseState.speed = 60.0 * CV.KPH_TO_MS
    cs.cruiseState.speedCluster = cs.cruiseState.speed
    helper.update_v_cruise(cs, True, True, _make_sm(), SimpleNamespace())
    self.assertAlmostEqual(helper.v_cruise_kph, 60.0, places=1)

  def test_other_brands_keep_carrot_own_set_speed(self):
    helper = _make_helper('hyundai', pcm_cruise=True, op_long=True, carrot_own_kph=40.0)
    cs = _CarState(speed_kph=80.0)
    helper.update_v_cruise(cs, True, True, _make_sm(), SimpleNamespace())  # consumes the available edge
    helper.update_v_cruise(cs, True, True, _make_sm(), SimpleNamespace())
    self.assertAlmostEqual(helper.v_cruise_kph, 40.0, places=1,
                           msg="carrot's own state machine must stay authoritative for brands "
                               "whose button events openpilot receives")

  def test_missing_pcm_set_speed_does_not_zero_the_target(self):
    helper = _make_helper('toyota', pcm_cruise=True, op_long=True)
    before = helper.v_cruise_kph
    self.assertGreater(before, 0.0)
    cs = _CarState(speed_kph=0.0)
    helper.update_v_cruise(cs, True, True, _make_sm(), SimpleNamespace())
    self.assertEqual(helper.v_cruise_kph, before,
                     "a PCM that has not reported a set speed yet must not zero the planner target")


def _make_macan_helper(carrot_own_kph=40.0):
  """A Macan in fusion mode: stock ACC owns the setpoint, OP only mirrors it.

  `macan_fusion` is keyed off carFingerprint, so the stand-in CP needs that field
  (plus `flags` for is_volkswagen_meb) and CarParamsSP.pcmCruiseSpeed=False, matching
  the real PORSCHE_MACAN_MK1 CarParams.
  """
  cp = SimpleNamespace(brand='volkswagen', carFingerprint='PORSCHE_MACAN_MK1', flags=0,
                       pcmCruise=False, openpilotLongitudinalControl=True)
  cp_sp = SimpleNamespace(pcmCruiseSpeed=False)
  helper = VCruiseCarrot(cp, cp_sp)
  helper._update_cruise_buttons = lambda *a, **k: carrot_own_kph
  helper._cruise_control = lambda *a, **k: None
  return helper


class TestMacanFusionSetSpeed(unittest.TestCase):
  """Macan fusion control: OP's vCruise must mirror ACC_02.Wunschgeschw, always.

  Route 0000008f (2026-10-03, sp-macan-re) showed OP transmitting ACC_02 with a
  constant 5.12 kph while the stock ACC was at 29.8-53.8 kph: `VCruiseCarrot.
  update_v_cruise` overrode `VCruiseHelper.update_v_cruise`, so the fusion branch
  never ran and carrot's own state machine (clamped to `_cruise_speed_min` = 5)
  stayed authoritative. The cluster showed a phantom 5 km/h, SET appeared to do
  nothing, and the planner fought the stock ACC (the "sudden accel/decel" report).
  """

  def test_parked_with_no_stock_setpoint_shows_nothing(self):
    helper = _make_macan_helper()
    cs = _CarState(speed_kph=0.0)
    for _ in range(3):
      helper.update_v_cruise(cs, False, True, _make_sm(), SimpleNamespace())
    self.assertEqual(helper.v_cruise_kph, V_CRUISE_UNSET,
                     "no stock setpoint must map to V_CRUISE_UNSET, not carrot's 5 kph minimum")
    self.assertGreaterEqual(helper.v_cruise_cluster_kph, 250,
                            "cluster must be >= 250 so create_acc_hud_control sends the MLB keine-Anzeige sentinel")

  def test_mirrors_stock_setpoint(self):
    helper = _make_macan_helper()
    cs = _CarState(speed_kph=30.0)
    helper.update_v_cruise(cs, True, True, _make_sm(), SimpleNamespace())
    self.assertAlmostEqual(helper.v_cruise_kph, 30.0, places=1,
                           msg="the stock ACC's 30 kph initial setpoint must reach OP")
    # The driver presses SET/speed+ and the stock ACC answers with a new setpoint.
    cs.cruiseState.speed = 53.76 * CV.KPH_TO_MS
    cs.cruiseState.speedCluster = cs.cruiseState.speed
    helper.update_v_cruise(cs, True, True, _make_sm(), SimpleNamespace())
    self.assertAlmostEqual(helper.v_cruise_kph, 53.8, places=1,
                           msg="OP must keep tracking the stock ACC, or the two controllers fight")
    self.assertAlmostEqual(helper.v_cruise_cluster_kph, 53.8, places=1)


if __name__ == '__main__':
  unittest.main()
