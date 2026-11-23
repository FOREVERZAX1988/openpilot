#!/usr/bin/env python3
"""
Offline unit tests for sunnypilot/carrot/carrot_navi_coordination.py.

These run WITHOUT building cereal/gen (no pycapnp import), mirroring
test_carrot_navi_fusion.py. They verify the constraint-only semantics:
away-from-exit lane changes are blocked inside the convergence window, the
exit side stays open, and everything is inert when the gate is off.
"""
import importlib.util
import pathlib
import sys
import unittest


# carrot_navi_coordination imports Params lazily inside _read_param and has no
# hard module-level openpilot imports, so it can be exec'd directly.
_SRC = pathlib.Path(__file__).resolve().parent.parent / "carrot_navi_coordination.py"
_spec = importlib.util.spec_from_file_location("carrot_navi_coordination_under_test", _SRC)
coord = importlib.util.module_from_spec(_spec)
sys.modules["carrot_navi_coordination_under_test"] = coord
_spec.loader.exec_module(coord)


class _FakeMeta:
  def __init__(self, present: bool = False):
    self.present = present


class _FakeGuidance:
  def __init__(self, present: bool, distance_m: int):
    self.present = present
    self.distanceM = distance_m
    self.meta = _FakeMeta(present)


class _FakeNavi:
  def __init__(self, distances: dict[str, tuple[bool, int]] | None = None):
    self.guidanceNext = _FakeGuidance(*distances.get("next", (False, 0))) if distances else _FakeGuidance(False, 0)
    self.guidanceCurrent = _FakeGuidance(*distances.get("current", (False, 0))) if distances else _FakeGuidance(False, 0)
    # capnp publish heartbeat timestamp (ns); default to a live value.
    self.publishMonoTimeNanos = 987_654_321_000_000_000


class _FakeParams:
  def __init__(self, enabled: bool):
    self.enabled = enabled
    self.get_bool_calls = 0

  def get_bool(self, key: str) -> bool:
    self.get_bool_calls += 1
    assert key == "CarrotNavLaneCoordination"
    return self.enabled


def _make_coordinator(enabled: bool) -> tuple[coord.CarrotNaviLaneCoordinator, _FakeParams]:
  params = _FakeParams(enabled)
  return coord.CarrotNaviLaneCoordinator(params), params


class TestNormalizeAtcDirection(unittest.TestCase):
  def test_raw_types(self):
    self.assertEqual(coord.normalize_atc_direction("fork right"), "right")
    self.assertEqual(coord.normalize_atc_direction("turn left"), "left")

  def test_prepare_suffix(self):
    self.assertEqual(coord.normalize_atc_direction("fork right prepare"), "right")
    self.assertEqual(coord.normalize_atc_direction("turn left prepare"), "left")

  def test_active_prefix(self):
    self.assertEqual(coord.normalize_atc_direction("atc right"), "right")
    self.assertEqual(coord.normalize_atc_direction("atc left"), "left")

  def test_non_lateral_types(self):
    for t in ("", "none", "straight", None):
      self.assertEqual(coord.normalize_atc_direction(t), "")


class TestCoordinationUpdate(unittest.TestCase):
  _DT = 0.01

  def test_gate_off_means_inert(self):
    coordinator, params = _make_coordinator(enabled=False)
    navi = _FakeNavi({"next": (True, 300)})
    self.assertEqual(coordinator.update(navi, "fork right", self._DT), (False, False))

  def test_exit_right_blocks_left_side(self):
    coordinator, _ = _make_coordinator(enabled=True)
    coordinator._enabled = True  # skip the 1 Hz param throttle window
    navi = _FakeNavi({"next": (True, 300)})
    self.assertEqual(coordinator.update(navi, "fork right", self._DT), (True, False))
    self.assertEqual(coordinator.update(navi, "atc right", self._DT), (True, False))

  def test_exit_left_blocks_right_side(self):
    coordinator, _ = _make_coordinator(enabled=True)
    coordinator._enabled = True
    navi = _FakeNavi({"next": (True, 300)})
    self.assertEqual(coordinator.update(navi, "fork left", self._DT), (False, True))

  def test_beyond_window_is_inert(self):
    coordinator, _ = _make_coordinator(enabled=True)
    coordinator._enabled = True
    navi = _FakeNavi({"next": (True, coord.EXIT_CONSTRAINT_RANGE_M + 1)})
    self.assertEqual(coordinator.update(navi, "fork right", self._DT), (False, False))

  def test_no_guidance_distance_is_inert(self):
    coordinator, _ = _make_coordinator(enabled=True)
    coordinator._enabled = True
    self.assertEqual(coordinator.update(None, "fork right", self._DT), (False, False))
    self.assertEqual(coordinator.update(_FakeNavi(), "fork right", self._DT), (False, False))

  def test_no_direction_is_inert(self):
    coordinator, _ = _make_coordinator(enabled=True)
    coordinator._enabled = True
    navi = _FakeNavi({"next": (True, 300)})
    self.assertEqual(coordinator.update(navi, "straight", self._DT), (False, False))
    self.assertEqual(coordinator.update(navi, "", self._DT), (False, False))

  def test_uses_closest_guidance_distance(self):
    coordinator, _ = _make_coordinator(enabled=True)
    coordinator._enabled = True
    # next far (outside), current near (inside) -> constraint applies
    navi = _FakeNavi({"next": (True, coord.EXIT_CONSTRAINT_RANGE_M + 500),
                      "current": (True, 200)})
    self.assertEqual(coordinator.update(navi, "fork right", self._DT), (True, False))

  def test_param_refresh_is_throttled(self):
    coordinator, params = _make_coordinator(enabled=True)
    coordinator.update(None, "straight", self._DT)
    initial_calls = params.get_bool_calls
    for _ in range(10):
      coordinator.update(None, "straight", self._DT)
    self.assertEqual(params.get_bool_calls, initial_calls, "param reads must be throttled to 1 Hz")

  def test_param_flip_is_picked_up(self):
    params = _FakeParams(enabled=False)
    coordinator = coord.CarrotNaviLaneCoordinator(params)
    navi = _FakeNavi({"next": (True, 300)})
    self.assertEqual(coordinator.update(navi, "fork right", 1.1), (False, False))
    params.enabled = True
    self.assertEqual(coordinator.update(navi, "fork right", 1.1), (True, False))


class TestCoordinationFreshnessGate(unittest.TestCase):
  """Safety review C3: a stalled navigation stream must not keep blocking."""

  _DT = 0.01

  def _primed_coordinator(self):
    coordinator, _ = _make_coordinator(enabled=True)
    coordinator._enabled = True
    navi = _FakeNavi({"next": (True, 300)})
    # Prime with one publish timestamp; freeze the clock to a known point.
    coordinator.update(navi, "fork right", self._DT)
    primed_publish_ns = coordinator._last_publish_ns
    primed_mono = coordinator._last_publish_mono
    self.assertGreater(primed_publish_ns, 0)
    return coordinator, navi, primed_publish_ns, primed_mono

  def test_fresh_timestamps_block(self):
    coordinator, navi, primed_ns, primed_mono = self._primed_coordinator()
    # New publish timestamp (stream alive) + tiny clock advance -> still blocks.
    navi.publishMonoTimeNanos = primed_ns + 1
    coordinator._last_publish_mono = primed_mono - 0.1
    self.assertEqual(coordinator.update(navi, "fork right", self._DT), (True, False))

  def test_repeated_timestamp_within_window_blocks(self):
    coordinator, navi, primed_ns, primed_mono = self._primed_coordinator()
    coordinator._last_publish_mono = primed_mono - coord.NAV_COORD_MAX_AGE_S / 2
    self.assertEqual(coordinator.update(navi, "fork right", self._DT), (True, False))

  def test_stalled_stream_goes_inert(self):
    coordinator, navi, primed_ns, primed_mono = self._primed_coordinator()
    # Same publish timestamp (no new publish) beyond the max age -> inert.
    coordinator._last_publish_mono = primed_mono - (coord.NAV_COORD_MAX_AGE_S + 0.1)
    self.assertEqual(coordinator.update(navi, "fork right", self._DT), (False, False))

  def test_missing_publish_timestamp_is_inert(self):
    coordinator, _ = _make_coordinator(enabled=True)
    coordinator._enabled = True
    navi = _FakeNavi({"next": (True, 300)})
    navi.publishMonoTimeNanos = 0
    self.assertEqual(coordinator.update(navi, "fork right", self._DT), (False, False))

  def test_stream_resumes_after_stall(self):
    coordinator, navi, primed_ns, primed_mono = self._primed_coordinator()
    coordinator._last_publish_mono = primed_mono - (coord.NAV_COORD_MAX_AGE_S + 0.1)
    self.assertEqual(coordinator.update(navi, "fork right", self._DT), (False, False))
    # Fresh publish timestamp revives the constraint.
    navi.publishMonoTimeNanos = primed_ns + 1
    self.assertEqual(coordinator.update(navi, "fork right", self._DT), (True, False))


if __name__ == "__main__":
  unittest.main()
