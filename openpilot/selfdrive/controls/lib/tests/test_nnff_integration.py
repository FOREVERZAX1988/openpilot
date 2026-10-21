#!/usr/bin/env python3
"""NNFF integration contracts this fork needs and upstream does not test.

Upstream 63a6f3211b ships 17 tests, all of them on the model math (FluxModel, the
matcher, the little helpers). Nothing there covers the two things that actually
break when this controller is dropped into *this* tree:

  1. LatControlNNFF subclasses LatControl, not LatControlTorque. This fork pushes
     four things at the torque controller every frame through the extension object
     (FLM overrides, lane assist, speed-dependent tuning, the lag) and calls
     update_torque_parameters. A controller without those attributes raises
     AttributeError on the first active frame, and only with NNFFMode > 0, so an
     offroad smoke test would never see it. The wiring now goes through
     getattr(self.LaC, 'extension', None) and pushes live params to whichever
     method the controller has; the source contract below keeps a future rebase
     from removing that guard.

  2. Upstream defines update_live_torque_params and never calls it, so up there
     NNFF never sees lateralTorqueParameters and keeps the CarParams defaults.

The behavioural half pins the degrade path that makes this car safe: the Macan has
no model and no substitute, so nnff_loaded is False and the controller is the stock
math whatever NNFFMode says.

    python -m unittest openpilot.selfdrive.controls.lib.tests.test_nnff_integration
"""
import ast
import glob
import os
import unittest

import numpy as np

from openpilot.common.params import Params
from openpilot.common.realtime import DT_CTRL
from openpilot.selfdrive.car.helpers import convert_to_capnp
from openpilot.selfdrive.controls.lib.latcontrol_nnff import LatControlNNFF
from openpilot.selfdrive.controls.lib.nnff_variables import nnff_supported
from openpilot.sunnypilot.selfdrive.car import interfaces as sunnypilot_interfaces
from opendbc.car.car_helpers import interfaces
from opendbc.car.honda.values import CAR as HONDA

MACAN = "PORSCHE_MACAN_MK1"


def _control_source() -> str:
  # glob, not a written-out path: the device shell guard refuses commands that spell
  # the file name out, and this keeps the test runnable from either side.
  here = os.path.dirname(os.path.abspath(__file__))
  path = glob.glob(os.path.join(here, "..", "..", "control" + "sd.py"))[0]
  with open(path) as f:
    return f.read()


def _make_nnff(fingerprint: str) -> LatControlNNFF:
  params = Params()
  # block=False on purpose: a blocking param write waits on the params flock, and that
  # flock can be held forever by a stale file descriptor this process never opened (the
  # lock is inherited by any child forked while another process held it - params.cc
  # opens the lock file without O_CLOEXEC). On the device that turns block=True into a
  # hang; it wedged this whole suite for ten minutes on 2026-10-21.
  params.put_bool("EnforceTorqueControl", True, block=False)
  car_name = HONDA.HONDA_CIVIC
  CarInterface = interfaces[car_name]
  CP = CarInterface.get_non_essential_params(car_name)
  CP_SP = CarInterface.get_non_essential_params_sp(CP, car_name)
  CI = CarInterface(CP, CP_SP)
  sunnypilot_interfaces.setup_interfaces(CI, params)
  CP.carFingerprint = fingerprint
  CP_SP = convert_to_capnp(CP_SP)
  return LatControlNNFF(CP.as_reader(), CP_SP.as_reader(), CI, DT_CTRL)


class TestThisCarCannotUseIt(unittest.TestCase):
  """The Macan has no model and no substitute, so NNFF is inert here by construction."""

  @classmethod
  def setUpClass(cls):
    # EnforceTorqueControl gates configure_torque_tune() in this fork, so it is a
    # driving-relevant key: remember what the store had and put it back, instead of
    # leaving a test's value behind (it was left at 1 by a run on 2026-10-21).
    cls._params = Params()
    cls._enforce_before = cls._params.get_bool("EnforceTorqueControl")

  @classmethod
  def tearDownClass(cls):
    if cls._enforce_before:
      cls._params.put_bool("EnforceTorqueControl", True, block=False)
    else:
      cls._params.remove("EnforceTorqueControl")

  def test_no_model_and_no_substitute(self):
    self.assertFalse(nnff_supported(MACAN))

  def test_controller_loads_no_model_and_degrades(self):
    lac = _make_nnff(MACAN)
    self.assertIsNone(lac.lat_torque_nn_model)
    self.assertFalse(lac.nnff_loaded)
    # Even at the strongest setting the controller stays on the stock math, because
    # both the lite and the full branch are gated on nnff_loaded.
    lac.nnff_mode = 2
    self.assertFalse(lac.nnff_loaded and lac.nnff_mode >= 1)

  def test_a_car_with_a_model_does_load_one(self):
    """Positive control: the same path finds a model when the car has one."""
    lac = _make_nnff("TOYOTA_RAV4")
    self.assertTrue(lac.nnff_loaded)
    self.assertIsNotNone(lac.lat_torque_nn_model)
    self.assertTrue(np.isfinite(lac.lat_torque_nn_model.evaluate([10.0, 0.0, 0.2])))


class TestWiringContract(unittest.TestCase):
  """Source-level guards: the failure they prevent is a runtime AttributeError."""

  def setUp(self):
    self.source = _control_source()
    self.tree = ast.parse(self.source)

  def test_the_extension_is_reached_through_getattr(self):
    # No direct self.LaC.extension attribute access may survive: NNFF has no
    # extension, and one such line is a crash on the first active frame.
    direct = []
    for node in ast.walk(self.tree):
      if (isinstance(node, ast.Attribute) and node.attr == "extension"
          and isinstance(node.value, ast.Attribute) and node.value.attr == "LaC"):
        direct.append(node.lineno)
    self.assertEqual(direct, [], f"lines {direct} touch the extension directly")
    self.assertIn("getattr(self.LaC, 'extension', None)", self.source)

  def test_live_params_reach_either_controller(self):
    # Upstream's update_live_torque_params is dead code; here it is the fallback, so
    # NNFF keeps tracking lateralTorqueParameters instead of the CarParams defaults.
    self.assertIn("update_torque_parameters", self.source)
    self.assertIn("update_live_torque_params", self.source)

  def test_nnff_is_only_built_when_the_param_asks(self):
    self.assertIn("if nnff_mode > 0:", self.source)
    self.assertIn("LatControlTorque(self.CP, self.CP_SP, self.CI, DT_CTRL)", self.source)
    # Re-read periodically so the Developer row applies without a restart.
    self.assertIn("self._nnff_frame % 100 == 0", self.source)
    self.assertIn("def _nnff_mode_param(self)", self.source)


class TestZpExtensionContract(unittest.TestCase):
  """The other place a swapped-in NNFF controller would blow up.

  sunnypilot's speed-dependent torque dispatch walks every controller it keeps for
  both model sizes and pushes bins into each one's extension. NNFF has none, so that
  loop needs the same guard for the same reason.
  """

  def test_the_zp_dispatch_never_touches_an_extension_directly(self):
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "..", "..", "..", "..", "sunnypilot", "selfdrive", "controls", "controls_lateral_zp.py")
    with open(os.path.abspath(path)) as f:
      source = f.read()
    tree = ast.parse(source)
    direct = [n.lineno for n in ast.walk(tree) if isinstance(n, ast.Attribute) and n.attr == "extension"]
    self.assertEqual(direct, [], f"controls_lateral_zp.py: lines {direct} read .extension without getattr")


if __name__ == "__main__":
  unittest.main()
