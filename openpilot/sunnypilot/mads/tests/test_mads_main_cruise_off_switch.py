"""
Copyright (c) 2026-, Zeph Leggett.

This file is part of zoompilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""

from openpilot.cereal import custom
from opendbc.car.hyundai.values import HyundaiFlags
from opendbc.sunnypilot.car.mazda.values import MazdaFlagsSP
from openpilot.common.test import OpenpilotTestCase
from openpilot.sunnypilot.mads.tests.mads_harness import car_state, make_mads

EventNameSP = custom.OnroadEventSP.EventName


class TestMainCruiseOffSwitch(OpenpilotTestCase):
  """On cars whose only MADS off-switch is the ACC main state, lateral must not be able to
  outlive it. A carstate that reports cruise enabled while main is off engages MADS with no
  falling edge behind it, which used to leave lateral on until ignition off (route 00000057)."""

  def _run(self, brand, prev_available, enabled, flags=0):
    mocker = self._fixture("mocker")
    mads, sd = make_mads(mocker, brand, prev_available, flags)
    mads.enabled = enabled
    mads.update_events(car_state(False))
    return sd.events_sp.has(EventNameSP.lkasDisable)

  def test_falling_edge_still_disables(self):
    assert self._run("mazda", prev_available=True, enabled=True)

  def test_enabled_with_availability_already_low_disables(self):
    assert self._run("mazda", prev_available=False, enabled=True)

  def test_disabled_mads_stays_quiet(self):
    assert not self._run("mazda", prev_available=False, enabled=False)

  def test_own_button_brands_keep_the_edge_only_behavior(self):
    # a hyundai with an LDA button engages MADS with main cruise off, so a low availability
    # level is a normal state there and must not disable it
    assert not self._run("hyundai", prev_available=False, enabled=True, flags=HyundaiFlags.HAS_LDA_BUTTON)


class TestMainCruiseEngage(OpenpilotTestCase):
  """MadsMainCruiseAllowed engages lateral on the ACC main rising edge. Brands in
  MADS_NO_ACC_MAIN_BUTTON have no ACC main button of their own, so they set
  no_main_cruise and must NOT engage from that edge; Mazda without a declared
  TJA button is the positive case. A declared MADS button that owns lateral
  (Mazda TJA) also takes ACC main out of it."""

  def _engages(self, brand, sp_flags=0):
    mocker = self._fixture("mocker")
    mads, sd = make_mads(mocker, brand, prev_available=False, sp_flags=sp_flags)
    mads.update_events(car_state(True))
    return sd.events_sp.has(EventNameSP.lkasEnable)

  def test_no_acc_main_brands_do_not_engage_on_main(self):
    from openpilot.sunnypilot.mads.helpers import MADS_NO_ACC_MAIN_BUTTON
    assert MADS_NO_ACC_MAIN_BUTTON  # guard against an empty list making this vacuous
    for brand in MADS_NO_ACC_MAIN_BUTTON:
      assert not self._engages(brand), brand

  def test_no_acc_main_brands_set_no_main_cruise(self):
    from openpilot.sunnypilot.mads.helpers import MADS_NO_ACC_MAIN_BUTTON
    for brand in MADS_NO_ACC_MAIN_BUTTON:
      mocker = self._fixture("mocker")
      mads, _ = make_mads(mocker, brand, prev_available=False)
      assert mads.no_main_cruise, brand

  def test_mazda_without_a_tja_button_engages_on_main(self):
    assert self._engages("mazda")

  def test_tja_button_keeps_main_out_of_lateral(self):
    assert not self._engages("mazda", sp_flags=MazdaFlagsSP.TJA_BUTTON)
