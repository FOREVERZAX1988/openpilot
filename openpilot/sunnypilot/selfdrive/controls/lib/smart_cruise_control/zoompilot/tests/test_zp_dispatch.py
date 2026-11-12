"""
Copyright (c) 2026-, Zeph Leggett.

This file is part of zoompilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.

Only measured brands run zoompilot's curve planners; every other brand gets sunnypilot's own,
wrapped only for the Curve Speed profile.
"""
import unittest

from opendbc.car import structs
from openpilot.sunnypilot.selfdrive.controls.lib.smart_cruise_control import map_controller as sp_map
from openpilot.sunnypilot.selfdrive.controls.lib.smart_cruise_control import vision_controller as sp_vision
from openpilot.sunnypilot.selfdrive.controls.lib.smart_cruise_control.zoompilot import TUNED_BRANDS, make_smart_cruise_control
from openpilot.sunnypilot.selfdrive.controls.lib.smart_cruise_control.zoompilot import curve_speed_profile as zp_profile
from openpilot.sunnypilot.selfdrive.controls.lib.smart_cruise_control.zoompilot import map_controller as zp_map
from openpilot.sunnypilot.selfdrive.controls.lib.smart_cruise_control.zoompilot import vision_controller as zp_vision


class TestZpDispatch(unittest.TestCase):

  def test_brand_selects_the_planner(self):
    for brand in ["mazda", "hyundai", "honda", "toyota", "chrysler", "gm", "ford", "subaru", "body"]:
      for op_long in [False, True]:
        with self.subTest(brand=brand, op_long=op_long):
          scc = make_smart_cruise_control(structs.CarParams(brand=brand, openpilotLongitudinalControl=op_long))
          if brand in TUNED_BRANDS:
            self.assertIs(type(scc.vision), zp_vision.SmartCruiseControlVision)
            self.assertIs(type(scc.map), zp_map.SmartCruiseControlMap)
          else:
            self.assertIs(type(scc.vision), zp_profile.SmartCruiseControlVision)
            self.assertIs(type(scc.map), zp_profile.SmartCruiseControlMap)
            self.assertIs(zp_profile.SmartCruiseControlVision.__bases__[-1], sp_vision.SmartCruiseControlVision)
            self.assertIs(zp_profile.SmartCruiseControlMap.__bases__[-1], sp_map.SmartCruiseControlMap)
            self.assertFalse(hasattr(scc.vision, 'v_ahead_min'))  # the planner publishes 0: no lookahead

  def test_only_mazda_is_tuned(self):
    self.assertEqual(TUNED_BRANDS, ('mazda',))
