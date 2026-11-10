# Copyright (c) 2026, firestar5683 and StarPilot contributors
# SPDX-License-Identifier: MIT
"""End-to-end wiring tests for the FLM override admission path.

These cover the Seam B adjudication at the control-path level: the
controller must not publish a bundle that the owner refused, and it must
publish nothing at all when the feature is off.
"""
import json
import sys
import types
import unittest

# Off-device (Windows) the params import chain pulls in fcntl through the
# hardware layer. The FLM admission path does not touch the hardware, so a
# minimal stub keeps the test runnable on a dev machine. On the device the
# real modules are present and this stub is not installed.
if "fcntl" not in sys.modules:
  try:
    import fcntl  # noqa: F401
  except ImportError:
    _fcntl = types.ModuleType("fcntl")
    _fcntl.fcntl = lambda *args, **kwargs: 0
    _fcntl.ioctl = lambda *args, **kwargs: 0
    _fcntl.flock = lambda *args, **kwargs: 0
    _fcntl.LOCK_EX = 2
    _fcntl.LOCK_UN = 8
    sys.modules["fcntl"] = _fcntl

# The compiled params library is a POSIX build artifact and does not exist
# on a Windows dev machine. The FLM admission path never touches the real
# params store (the test injects a fake), so the whole params module is
# stubbed before it is imported. On the device the real module is used.
if "openpilot.common.params" not in sys.modules:
  try:
    import openpilot.common.params  # noqa: F401
  except Exception:
    _params_mod = types.ModuleType("openpilot.common.params")

    class _StubParams:
      def __init__(self, *args, **kwargs):
        self.values = {}

      def get(self, key, encoding=None, return_default=False):
        return self.values.get(key, "" if not return_default else None)

      def get_bool(self, key, return_default=False):
        return bool(self.values.get(key, False))

      def get_int(self, key, default=0):
        return int(self.values.get(key, default))

      def get_float(self, key, default=0.0):
        return float(self.values.get(key, default))

    _params_mod.Params = _StubParams
    _params_mod.put_bool = lambda *a, **k: None
    _params_mod.put_int = lambda *a, **k: None
    _params_mod.put_float = lambda *a, **k: None
    _params_mod.put_string = lambda *a, **k: None
    sys.modules["openpilot.common.params"] = _params_mod

from openpilot.selfdrive.controls.lib import latcontrol_torque as lct
from openpilot.selfdrive.controls.lib.latcontrol_vehicle_tunes import (
  clear_flm_runtime_overrides,
  get_flm_runtime_overrides,
)


class FakeParams:
  """Minimal Params stand-in for the pieces LatControlTorque touches."""

  def __init__(self, values=None):
    self.values = values or {}

  def get(self, key, encoding=None, return_default=False):
    return self.values.get(key, "" if not return_default else None)

  def get_bool(self, key, return_default=False):
    value = self.values.get(key, False)
    return bool(value)

  def get_int(self, key, default=0):
    return int(self.values.get(key, default))

  def get_float(self, key, default=0.0):
    return float(self.values.get(key, default))


def make_controller(flm_enabled=True, overrides=None):
  """Build a LatControlTorque with only the FLM path exercised.

  The real constructor needs a full CarParams and a car interface, which
  are not available off-device. The FLM admission path only touches the
  params object and the owner, so the controller is assembled directly.
  """
  controller = object.__new__(lct.LatControlTorque)
  controller.params = FakeParams({
    "FlmRuntimeOverridesEnabled": "1" if flm_enabled else "0",
    "FLMActiveOverrides": json.dumps(overrides) if overrides is not None else "",
  })
  controller._flm_frame = -1
  controller._flm_enabled = flm_enabled
  controller._flm_owner = lct.FlmOverrideOwner(
    identity=lct.identity_for_fingerprint(1234),
    baselines=lct._flm_baseline_curves(),
  )
  return controller


class TestBaselineCurves(unittest.TestCase):
  def test_every_family_has_a_curve(self):
    curves = lct._flm_baseline_curves()
    self.assertEqual(set(curves), {"gm", "standard", "hkg_canfd"})
    for family, values in curves.items():
      self.assertEqual(len(values), len(lct.FLM_FRICTION_SPEED_KNOTS), family)
      for value in values:
        self.assertGreater(value, 0.0)


class TestControlPathWiring(unittest.TestCase):
  def setUp(self):
    clear_flm_runtime_overrides()

  def tearDown(self):
    clear_flm_runtime_overrides()

  def _bundle(self, family="gm", delta=0.10):
    baselines = lct._flm_baseline_curves()
    base = baselines[family]
    return {"baseFrictionThresholds": {family: {"values": [v * (1.0 + delta) for v in base]}}}

  def test_disabled_publishes_nothing(self):
    controller = make_controller(flm_enabled=False, overrides=self._bundle())
    controller._refresh_flm_overrides()
    self.assertEqual(get_flm_runtime_overrides(), {})

  def test_enabled_publishes_a_slewed_bundle(self):
    controller = make_controller(flm_enabled=True, overrides=self._bundle())
    controller._refresh_flm_overrides()
    published = get_flm_runtime_overrides()
    self.assertIn("baseFrictionThresholds", published)
    # The first frame may only move by the slew step, never the full delta.
    baselines = lct._flm_baseline_curves()
    values = published["baseFrictionThresholds"]["gm"]["values"]
    delta = values[0] / baselines["gm"][0] - 1.0
    self.assertGreater(abs(delta), 0.0)
    self.assertLessEqual(abs(delta), 0.30 + 1e-9)

  def test_an_unparsable_bundle_publishes_nothing_new(self):
    controller = make_controller(flm_enabled=True, overrides=None)
    controller.params.values["FLMActiveOverrides"] = "{not json"
    controller._refresh_flm_overrides()
    published = get_flm_runtime_overrides()
    # The bundle must never contain a non-finite or absurd value.
    for family, payload in published.get("baseFrictionThresholds", {}).items():
      for value in payload["values"]:
        self.assertTrue(0.05 <= value < 10.0, family)

  def test_an_out_of_band_bundle_is_refused(self):
    controller = make_controller(flm_enabled=True, overrides=self._bundle(delta=0.9))
    controller._refresh_flm_overrides()
    published = get_flm_runtime_overrides()
    baselines = lct._flm_baseline_curves()
    for family, payload in published.get("baseFrictionThresholds", {}).items():
      for value, base in zip(payload["values"], baselines[family], strict=True):
        self.assertLessEqual(abs(value / base - 1.0), 0.30 + 1e-9)

  def test_a_nan_bundle_is_refused(self):
    controller = make_controller(flm_enabled=True, overrides=None)
    controller.params.values["FLMActiveOverrides"] = json.dumps(
      {"baseFrictionThresholds": {"gm": {"values": [float("nan")] * 5}}})
    controller._refresh_flm_overrides()
    published = get_flm_runtime_overrides()
    for family, payload in published.get("baseFrictionThresholds", {}).items():
      for value in payload["values"]:
        self.assertTrue(0.05 <= value < 10.0, family)


class TestNoDirectReadPath(unittest.TestCase):
  def test_the_controller_no_longer_reads_the_bundle_directly(self):
    """The direct read must be gone: the owner owns the admission.

    A regression here would silently re-enable the one-frame step and the
    fail-open behavior the adjudication removed.
    """
    import inspect
    source = inspect.getsource(lct.LatControlTorque._refresh_flm_overrides)
    self.assertNotIn("set_flm_runtime_overrides(overrides)", source)
    self.assertIn("self._flm_owner.admit(", source)
    self.assertIn("self._flm_owner.tick(", source)


if __name__ == "__main__":
  unittest.main()
