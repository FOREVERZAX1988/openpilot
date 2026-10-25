"""The FLM override bundle must reach the torque controller's friction term.

Upstream 44a32ec77c calls this the "nothing consumed the analyzer's output"
gap. The wiring lives in LatControlTorque._refresh_flm_overrides, which
publishes the FLMActiveOverrides param into the process-wide override table and
flips the base friction threshold to the speed-dependent curve.

These tests drive that method with a stub Params so they run without capnp.
"""

import json
from types import SimpleNamespace

import pytest

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


def _controller(bundle, enabled: bool):
  return SimpleNamespace(params=ParamsStub(bundle), _flm_frame=-1, _flm_enabled=enabled)


@pytest.fixture(autouse=True)
def _clear_overrides():
  yield
  tunes.set_flm_runtime_overrides({})


def test_gate_off_publishes_nothing():
  ctrl = _controller(BUNDLE, enabled=False)
  LatControlTorque._refresh_flm_overrides(ctrl)
  assert not tunes.flm_runtime_overrides_active()


def test_gate_on_with_bundle_activates_the_friction_curve():
  ctrl = _controller(BUNDLE, enabled=True)
  LatControlTorque._refresh_flm_overrides(ctrl)
  assert tunes.flm_runtime_overrides_active()
  # 0 m/s sits on the first knot, 25 m/s on the last one: the published curve is
  # what the controller reads instead of the constant FRICTION_THRESHOLD.
  assert tunes.get_standard_friction_threshold(0.0) == pytest.approx(CURVE[0], abs=1e-3)
  assert tunes.get_standard_friction_threshold(25.0) == pytest.approx(CURVE[-1], abs=1e-3)


def test_gate_on_without_bundle_stays_inactive():
  ctrl = _controller(None, enabled=True)
  LatControlTorque._refresh_flm_overrides(ctrl)
  assert not tunes.flm_runtime_overrides_active()


def test_unparsable_bundle_keeps_the_previous_overrides():
  ctrl = _controller(BUNDLE, enabled=True)
  LatControlTorque._refresh_flm_overrides(ctrl)
  ctrl.params = SimpleNamespace(get=lambda *a, **k: b"{not json")
  ctrl._flm_frame = -1
  LatControlTorque._refresh_flm_overrides(ctrl)
  assert tunes.flm_runtime_overrides_active()


def test_refresh_runs_once_per_cadence():
  ctrl = _controller(BUNDLE, enabled=True)
  calls = []
  ctrl.params = SimpleNamespace(get=lambda key, *a, **k: (calls.append(key), json.dumps(BUNDLE).encode())[1])
  for _ in range(FLM_OVERRIDE_REFRESH_FRAMES * 2):
    LatControlTorque._refresh_flm_overrides(ctrl)
  assert len(calls) == 2, calls
