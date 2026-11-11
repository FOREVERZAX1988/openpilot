"""The FLM override bundle must reach the torque controller's friction term.

Upstream 44a32ec77c calls this the "nothing consumed the analyzer's output"
gap. The wiring lives in LatControlTorque._refresh_flm_overrides, which hands
the FLMActiveOverrides param to the FLM ProfileOwner and publishes whatever the
owner returns into the process-wide override table.

These tests pin the *wiring* only: they use a stub Params and a stand-in owner
so they run without capnp. The owner's slew limiting, fail-closed behaviour and
identity binding are covered by sunnypilot/flm/tests/test_runtime_overrides.py.

unittest (not pytest) so the suite also runs on a device, where pytest is not
installed: python -m unittest openpilot.selfdrive.controls.lib.tests.test_flm_injection_wiring
"""

import json
from types import SimpleNamespace
import unittest

from openpilot.selfdrive.controls.lib import latcontrol_vehicle_tunes as tunes
from openpilot.selfdrive.controls.lib.latcontrol_torque import (
  FLM_OVERRIDE_REFRESH_FRAMES,
  LatControlTorque,
)

CURVE = [0.30, 0.31, 0.32, 0.33, 0.34]
BUNDLE = {
  "schemaVersion": 1,
  "baseFrictionThresholds": {"standard": {"values": CURVE}},
}


class ParamsStub:
  def __init__(self, bundle=None):
    self.bundle = bundle

  def get(self, key, default=None, **kwargs):
    assert key == "FLMActiveOverrides", key
    return None if self.bundle is None else json.dumps(self.bundle).encode()


class OwnerStub:
  """Stand-in for FlmOverrideOwner, matching its withdraw/admit/tick contract.

  Seam B moved bundle publication behind the owner. The real owner slews and
  validates; this stub publishes immediately and keeps the last non-empty
  bundle so the wiring assertions stay about wiring, not control policy.
  """

  def __init__(self):
    self.bundle: dict = {}
    self.admits: list[dict] = []

  def withdraw(self) -> None:
    self.bundle = {}

  def admit(self, bundle: dict, *, now_ns: int) -> bool:
    self.admits.append(bundle)
    if bundle:
      self.bundle = bundle
    return bool(bundle)

  def tick(self, *, now_ns: int, enabled: bool, **kwargs) -> dict:
    return self.bundle if enabled else {}


def _controller(bundle, enabled: bool):
  return SimpleNamespace(params=ParamsStub(bundle), _flm_frame=-1,
                         _flm_enabled=enabled, _flm_owner=OwnerStub())


class TestFLMInjectionWiring(unittest.TestCase):
  def tearDown(self):
    tunes.set_flm_runtime_overrides({})

  def test_gate_off_publishes_nothing(self):
    ctrl = _controller(BUNDLE, enabled=False)
    LatControlTorque._refresh_flm_overrides(ctrl)
    self.assertFalse(tunes.flm_runtime_overrides_active())

  def test_gate_on_with_bundle_activates_the_friction_curve(self):
    ctrl = _controller(BUNDLE, enabled=True)
    LatControlTorque._refresh_flm_overrides(ctrl)
    self.assertTrue(tunes.flm_runtime_overrides_active())
    # 0 m/s sits on the first knot, 25 m/s on the last one: the published curve is
    # what the controller reads instead of the constant FRICTION_THRESHOLD.
    self.assertAlmostEqual(tunes.get_standard_friction_threshold(0.0), CURVE[0], delta=1e-3)
    self.assertAlmostEqual(tunes.get_standard_friction_threshold(25.0), CURVE[-1], delta=1e-3)

  def test_gate_on_without_bundle_stays_inactive(self):
    ctrl = _controller(None, enabled=True)
    LatControlTorque._refresh_flm_overrides(ctrl)
    self.assertFalse(tunes.flm_runtime_overrides_active())

  def test_unparsable_bundle_keeps_the_previous_overrides(self):
    ctrl = _controller(BUNDLE, enabled=True)
    LatControlTorque._refresh_flm_overrides(ctrl)
    ctrl.params = SimpleNamespace(get=lambda *a, **k: b"{not json")
    ctrl._flm_frame = -1
    LatControlTorque._refresh_flm_overrides(ctrl)
    # Wiring hands an empty bundle to the owner on a parse failure; the owner
    # owns fail-closed, so this stub deliberately keeps the previous curve.
    self.assertEqual(ctrl._flm_owner.admits[-1], {})
    self.assertTrue(tunes.flm_runtime_overrides_active())

  def test_refresh_runs_once_per_cadence(self):
    ctrl = _controller(BUNDLE, enabled=True)
    calls = []
    ctrl.params = SimpleNamespace(get=lambda key, *a, **k: (calls.append(key), json.dumps(BUNDLE).encode())[1])
    for _ in range(FLM_OVERRIDE_REFRESH_FRAMES * 2):
      LatControlTorque._refresh_flm_overrides(ctrl)
    self.assertEqual(len(calls), 2, calls)


if __name__ == "__main__":
  unittest.main()
