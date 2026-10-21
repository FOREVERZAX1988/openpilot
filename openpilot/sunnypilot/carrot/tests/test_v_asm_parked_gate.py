"""The parked gate: no ONNX runs while the vehicle is not moving.

Measured 2026-10-22 (``ai/docs/jetlink_stability_1022.md``): with onroad preview open
and the car parked, ``xiaoge_data`` held **24 % of the whole device's CPU** while
``modeld`` and the UI were competing for the same cores — the lane model was running
at its 1 Hz floor on a car that was not going anywhere, and every camera frame also
paid a 2.7 MB Y-plane copy that nothing consumed.

These tests pin the gate that came out of that measurement:

  * the decision function's shape, including its **fail-open** answer when carState is
    missing (unknown is not parked; losing lane data on a highway hiccup would be a
    worse bug than the CPU bill),
  * the wiring into both camera threads (`_update_inference_gate` /
    `_update_vasm_gate`) and what `status()` reports,
  * the ordering inside ``run_road_camera``: the gate is consulted *before* the Y plane
    is built and before the model is touched.
"""
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace

from openpilot.cereal import log
from openpilot.sunnypilot.carrot.xiaoge import v_asm_server
from openpilot.sunnypilot.carrot.xiaoge.v_asm_server import PARKED_SPEED_MPS, VASMService, parked_gate

SOURCE_PATH = Path(v_asm_server.__file__)


class FakeSubMaster:
  """The slice of SubMaster the two gates use, with a controllable speed."""

  def __init__(self, speed=None, direction=None, alive=True, lane_width=3.5):
    self._speed = speed
    self._direction = direction
    self._alive = alive
    self._lane_width = lane_width
    self.updates = 0

  def update(self, _timeout):
    self.updates += 1

  def all_alive(self, _services):
    return self._alive

  def all_valid(self, _services):
    return self._alive

  def __getitem__(self, name):
    if not self._alive:
      raise KeyError(name)
    if name == "carState":
      return SimpleNamespace(vEgo=self._speed)
    return SimpleNamespace(meta=SimpleNamespace(laneChangeDirection=self._direction,
                                                laneWidthLeft=self._lane_width,
                                                laneWidthRight=self._lane_width))


def _service(**kw):
  """A VASMService with only the attributes the gates touch (no ONNX, no camera)."""
  service = object.__new__(VASMService)
  service.lock = threading.Lock()
  service.sm_lock = threading.Lock()
  service.sm = FakeSubMaster(**kw)
  service.vasm_gate = {"active": False, "side": "", "reason": "waiting", "laneWidth": 0.0}
  service.inference_gate = {"active": True, "reason": "not checked yet", "speed": None}
  return service


def _status_service():
  """A VASMService with everything ``status()`` reads (still no models, no camera)."""
  service = _service()
  service.params = None
  service.last_param_refresh_at = 0.0
  service.last_frame_at = 0.0
  service.last_road_frame_at = 0.0
  service.camera_error = ""
  service.lane_camera_error = ""
  service.vasm_result = {"left": False, "right": False, "side": "", "updatedMonoTimeNanos": 0}
  service.lane_result = {"leftLine": -1, "rightLine": -1, "leftConf": 0.0, "rightConf": 0.0,
                         "candidatesCount": 0, "valid": False, "error": "", "updatedMonoTimeNanos": 0}
  service.inference = SimpleNamespace(valid=True, error="", confidence={"left": 0.0, "right": 0.0},
                                      model_path=Path("/dev/null"), configured_sides=["left", "right"])
  service.lane_inference = SimpleNamespace(valid=True, error="")
  service.config = {}
  service.threshold = 0.45
  service.smoothing_seconds = 0.2
  service.base_interval_seconds = 0.25
  service.lane_threshold = 0.25
  service.lane_interval_seconds = 1.0
  service.last_inference_ms = 0.0
  service.last_inference_thread_cpu_ms = 0.0
  service.inference_fps = 0.0
  service.inference_count = 0
  service.last_inference_at = 0.0
  service.last_lane_inference_ms = 0.0
  service.last_lane_inference_thread_cpu_ms = 0.0
  service.lane_inference_fps = 0.0
  service.lane_inference_count = 0
  service.last_lane_inference_at = 0.0
  return service


class ParkedGateDecisionTest(unittest.TestCase):
  """``parked_gate`` is pure: no service, no locking, no IO."""

  def test_zero_speed_is_parked(self):
    gate = parked_gate(0.0)
    self.assertFalse(gate["active"])
    self.assertIn("parked", gate["reason"])
    self.assertEqual(gate["speed"], 0.0)

  def test_speed_under_the_threshold_is_parked(self):
    # 0.29 m/s is 29 cm in a second: creep noise on a stationary car, not motion
    self.assertFalse(parked_gate(PARKED_SPEED_MPS - 0.01)["active"])

  def test_threshold_itself_infers(self):
    # the comparison is strictly-greater-for-parked, so the boundary opens the gate
    self.assertTrue(parked_gate(PARKED_SPEED_MPS)["active"])

  def test_moving_infers_with_an_empty_reason(self):
    gate = parked_gate(15.0)
    self.assertTrue(gate["active"])
    self.assertEqual(gate["reason"], "")
    self.assertEqual(gate["speed"], 15.0)

  def test_negative_speed_infers_nothing(self):
    # vEgo should never be negative, but a signed reading must not be read as motion
    self.assertFalse(parked_gate(-0.1)["active"])

  def test_unknown_speed_fails_open(self):
    gate = parked_gate(None)
    self.assertTrue(gate["active"], "unknown carState must not silence the vision path")
    self.assertIn("unavailable", gate["reason"])
    self.assertIsNone(gate["speed"])


class UpdateInferenceGateTest(unittest.TestCase):
  """The wiring both camera threads call, per frame."""

  def test_parked_service_stores_an_inactive_gate(self):
    service = _service(speed=0.0)
    active, reason = service._update_inference_gate()
    self.assertFalse(active)
    self.assertIn("parked", reason)
    self.assertFalse(service.inference_gate["active"])
    self.assertEqual(service.inference_gate["speed"], 0.0)

  def test_moving_service_stores_an_active_gate(self):
    service = _service(speed=20.0)
    active, reason = service._update_inference_gate()
    self.assertTrue(active)
    self.assertEqual(reason, "")
    self.assertTrue(service.inference_gate["active"])

  def test_dead_carstate_fails_open(self):
    service = _service(alive=False)
    service.sm = FakeSubMaster(alive=False)
    active, reason = service._update_inference_gate()
    self.assertTrue(active)
    self.assertIn("unavailable", reason)
    self.assertIsNone(service.inference_gate["speed"])

  def test_unreadable_speed_field_fails_open(self):
    # a cereal schema without vEgo (or a torn state message) must not look parked
    service = _service()
    service.sm = SimpleNamespace(update=lambda _t: None, all_alive=lambda _s: True,
                                 all_valid=lambda _s: True,
                                 __getitem__=lambda _self, _n: SimpleNamespace())
    active, reason = service._update_inference_gate()
    self.assertTrue(active)
    self.assertIn("unavailable", reason)


class LaneChangeGateTest(unittest.TestCase):
  """The blindspot gate now reports "parked" instead of "outside 30-120 km/h"."""

  def test_parked_reason_wins_over_the_speed_range(self):
    service = _service(speed=0.0)
    active, _side = service._update_vasm_gate()
    self.assertFalse(active)
    self.assertIn("parked", service.vasm_gate["reason"])

  def test_low_speed_still_reports_the_range(self):
    service = _service(speed=20.0 / 3.6, direction=log.LaneChangeDirection.left)
    service._update_vasm_gate()
    self.assertIn("30-120", service.vasm_gate["reason"])

  def test_moving_lane_change_keeps_the_old_behaviour(self):
    service = _service(speed=60.0 / 3.6, direction=log.LaneChangeDirection.left, lane_width=3.5)
    active, side = service._update_vasm_gate()
    self.assertTrue(active)
    self.assertEqual(side, "left")
    self.assertEqual(service.vasm_gate["laneWidth"], 3.5)

  def test_narrow_target_lane_stays_closed(self):
    service = _service(speed=60.0 / 3.6, direction=log.LaneChangeDirection.right, lane_width=2.5)
    active, _side = service._update_vasm_gate()
    self.assertFalse(active)
    self.assertIn("3.0 m", service.vasm_gate["reason"])


class StatusContractTest(unittest.TestCase):
  """The web panel reads this JSON: the gate has to be visible there."""

  def test_status_exposes_the_inference_gate(self):
    service = _status_service()
    service.inference_gate = {"active": False, "reason": "parked (vEgo 0.00 m/s)", "speed": 0.0}
    status = service.status()
    self.assertIn("inferenceGate", status)
    self.assertFalse(status["inferenceGate"]["active"])
    self.assertIn("parked", status["inferenceGate"]["reason"])
    # the lane-change gate keeps its own key, so old readers are untouched
    self.assertIn("gate", status)

  def test_status_carries_the_live_gate_not_a_copy(self):
    service = _status_service()
    service._update_inference_gate()
    status = service.status()
    self.assertTrue(status["inferenceGate"]["active"])
    self.assertEqual(status["inferenceGate"]["speed"], 0.0 if service.sm._speed is not None else None)


class RoadLoopOrderTest(unittest.TestCase):
  """Source-level: the gate is consulted before the Y plane and before the model."""

  @classmethod
  def setUpClass(cls):
    source = SOURCE_PATH.read_text()
    start = source.index("def run_road_camera")
    end = source.index("class Handler", start)
    cls.body = source[start:end]

  def test_gate_is_consulted_in_the_road_loop(self):
    self.assertIn("self._update_inference_gate()", self.body)

  def test_y_plane_is_built_only_after_the_gate(self):
    gate_at = self.body.index("_update_inference_gate()")
    y_plane_at = self.body.index("nv12_y_plane(")
    model_at = self.body.index("self.lane_inference.infer(")
    self.assertLess(gate_at, y_plane_at, "a parked car must not pay the Y-plane copy")
    self.assertLess(y_plane_at, model_at)

  def test_gate_guard_skips_the_model(self):
    guard_at = self.body.index("if not infer_active or not self.lane_inference.valid:")
    model_at = self.body.index("self.lane_inference.infer(")
    self.assertLess(guard_at, model_at)


if __name__ == "__main__":
  unittest.main()
