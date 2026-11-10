"""
Copyright (c) 2026-, Zeph Leggett.

This file is part of zoompilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""

from openpilot.common.test import approx
from openpilot.cereal import custom
from openpilot.common.constants import CV
from openpilot.sunnypilot.selfdrive.car.intelligent_cruise_button_management.helpers import icbm_moves_speed_limits, minimum_set_speed_ms
from openpilot.sunnypilot.selfdrive.car.tests.icbm_servo_harness import make_icbm, run_frames, DECREASE_HOLD
from openpilot.sunnypilot.selfdrive.controls.lib.speed_limit.common import Mode
import unittest

SendButtonState = custom.IntelligentCruiseButtonManagement.SendButtonState

MAZDA_FLOOR = 30. * CV.KPH_TO_MS  # MRCC's floor in either unit mode; an imperial dash shows 19


class TestIcbmHelpers(unittest.TestCase):
  def test_icbm_moves_speed_limits(self):
    for has_long, has_icbm, mode, moves in [
    (True, True, Mode.assist, True),
    (True, True, Mode.warning, False),  # warn never moves the set speed
    (True, False, Mode.assist, False),  # alpha long alone: the planner prompts
    (False, True, Mode.assist, False),  # stock ACC: ICBM owns everything, no split to show
  ]:
      with self.subTest(has_long=has_long, has_icbm=has_icbm, mode=mode, moves=moves):
        assert icbm_moves_speed_limits(has_long, has_icbm, mode) is moves

  def test_mode_as_stored_param(self):
    for mode in [3, None]:
      with self.subTest(mode=mode):
        assert icbm_moves_speed_limits(True, True, mode) is (mode == 3)

  def test_minimum_set_speed(self):
    for floor, is_metric, expected_ms, dash in [
    (0., False, 20 * CV.MPH_TO_MS, 20),  # sunnypilot's default floor, in the dash unit
    (0., True, 30 * CV.KPH_TO_MS, 30),
    (MAZDA_FLOOR, False, MAZDA_FLOOR, 19),  # a car's own floor holds in either unit
    (MAZDA_FLOOR, True, MAZDA_FLOOR, 30),
  ]:
      with self.subTest(floor=floor, is_metric=is_metric, expected_ms=expected_ms, dash=dash):
        assert minimum_set_speed_ms(custom.CarParamsSP(zoompilot={'minimumSetSpeed': floor}), is_metric) == approx(expected_ms)
        # the servo compares it (CarParamsZP.minimumSetSpeed) in whole dash units
        icbm = make_icbm("mazda", min_set_speed=floor)
        run_frames(icbm, target_mph=40, cluster_mph=40, is_metric=is_metric)
        assert icbm.v_cruise_min == dash

  def test_servo_steps_down_to_the_cars_floor(self):
    for floor, steps_down in [(MAZDA_FLOOR, True), (0., False)]:
      with self.subTest(floor=floor, steps_down=steps_down):
        sends = run_frames(make_icbm("mazda", min_set_speed=floor), target_mph=15, cluster_mph=20, n=500)
        assert any(s in (SendButtonState.decrease, DECREASE_HOLD) for s in sends) == steps_down
