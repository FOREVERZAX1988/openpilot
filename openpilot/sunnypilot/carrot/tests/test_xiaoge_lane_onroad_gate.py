"""Tests for the plan-A onroad gate on the xiaoge pipelines.

Background (2026-09-29): `xiaoge_data` is gated by `CarrotEnabled`, so it runs offroad too,
and the lane ONNX model was inferring on a parked, ignition-off car -- burning CPU with
nobody in it.  Two candidate fixes were on the table:

  * **A (chosen)** -- gate on onroad only (`deviceState.started`).  Standstill (red light,
    idling, jam, ACC stop-and-go) is still onroad, so the lane signal never goes stale
    during a drive; only ignition-off / parked skips the inference.
  * B -- additionally gate on speed (~5 km/h + 10 s grace).  Rejected: it stops refreshing
    the lane signal while stopped, which is when lane guidance wants it.

Both `v_asm_server.py` threads consult the gate (the blind-spot pipeline keeps its own,
stricter speed gate on top).  What is checked here:

1. the policy function itself, including the fail-open case, and
2. that each camera thread consults it *before* running its ONNX model, that the lane
   thread clears the stale lane result when it pauses, and that the BSD speed gate survives.

`v_asm_server.py` cannot be imported in this environment (`onnxruntime` is only present on
device), so the wiring is pinned on the source text.  `py_compile` cannot catch a gate that
is computed but never used, which is the failure this test exists for.
"""
import re
import unittest
from pathlib import Path

from openpilot.sunnypilot.carrot.xiaoge.onroad_gate import (
  REASON_OFFROAD,
  REASON_ONROAD,
  REASON_UNKNOWN,
  xiaoge_inference_allowed,
)

XIAOGE_ROOT = Path(__file__).resolve().parents[1] / "xiaoge"
VASM_SOURCE = (XIAOGE_ROOT / "v_asm_server.py").read_text()


def function_body(source: str, name: str) -> str:
  """Return the source of ``def <name>(self, ...)`` up to the next method."""
  match = re.search(rf"\n  def {re.escape(name)}\(", source)
  assert match is not None, f"{name} not found"
  tail = source[match.start():]
  next_match = re.search(r"\n  def ", tail[1:])
  return tail[: next_match.start() + 1 if next_match else len(tail)]


class TestOnroadPolicy(unittest.TestCase):
  def test_onroad_runs_without_a_reason(self):
    allowed, reason = xiaoge_inference_allowed(device_state_available=True, started=True)
    self.assertTrue(allowed)
    self.assertEqual(reason, REASON_ONROAD)

  def test_offroad_pauses(self):
    allowed, reason = xiaoge_inference_allowed(device_state_available=True, started=False)
    self.assertFalse(allowed)
    self.assertEqual(reason, REASON_OFFROAD)
    # The reason lands in the on-device /status payload; keep it self-explanatory.
    self.assertIn("offroad", reason)
    self.assertIn("started=False", reason)

  def test_unknown_device_state_fails_open(self):
    # A false "offroad" would silently disable a driving feature (the failure mode that
    # already killed the wide-road thread once), so "cannot tell" must mean "run".
    allowed, reason = xiaoge_inference_allowed(device_state_available=False, started=False)
    self.assertTrue(allowed)
    self.assertEqual(reason, REASON_UNKNOWN)

  def test_policy_is_not_speed_based(self):
    # Plan A must not reintroduce the rejected speed gate: there is no speed argument, so
    # a standstill (speed 0) can never close the gate.
    allowed, _ = xiaoge_inference_allowed(device_state_available=True, started=True)
    self.assertTrue(allowed, "standstill is onroad; moving or not must not matter")


class TestGateWiring(unittest.TestCase):
  def test_subscribes_to_device_state(self):
    # The gate reads deviceState.started, which the manager also uses for IsOffroad.
    self.assertIn('messaging.SubMaster(["deviceState"])', VASM_SOURCE)
    gate = function_body(VASM_SOURCE, "_update_onroad_gate")
    self.assertIn('all_alive(["deviceState"])', gate)
    self.assertIn('all_valid(["deviceState"])', gate)
    self.assertIn("xiaoge_inference_allowed(", gate)

  def test_gate_uses_its_own_submaster(self):
    # self.sm is driven by the wide-road thread; two threads must not update one
    # SubMaster (sockets + per-service dicts are not thread safe).
    gate = function_body(VASM_SOURCE, "_update_onroad_gate")
    self.assertIn("self.onroad_sm.update(0)", gate)
    self.assertNotIn("self.sm.update", gate)

  def test_gate_serializes_the_shared_submaster(self):
    # BOTH camera threads call the gate, and SubMaster.update() is not thread safe (a
    # capnp reader swapped out by a concurrent update() in another thread is the SIGBUS
    # that restarted carrot_man, abddb1065d), so the shared update() must be serialized.
    self.assertIn("self.onroad_sm_lock", VASM_SOURCE)
    gate = function_body(VASM_SOURCE, "_update_onroad_gate")
    lock_at = gate.index("with self.onroad_sm_lock:")
    update_at = gate.index("self.onroad_sm.update(0)")
    self.assertLess(lock_at, update_at, "the update must happen inside the lock")

  def test_status_exposes_the_gate(self):
    status = function_body(VASM_SOURCE, "status")
    self.assertIn('"onroadGate": self.onroad_gate', status)


class TestLaneThread(unittest.TestCase):
  def setUp(self):
    self.body = function_body(VASM_SOURCE, "run_road_camera")

  def test_gate_is_consulted_before_the_onnx_model(self):
    gate_call = self.body.index("_update_onroad_gate()")
    infer_call = self.body.index("self.lane_inference.infer(")
    self.assertLess(gate_call, infer_call, "the gate must run before the lane ONNX call")
    self.assertIn("if not onroad:", self.body)
    # And the inference must be unreachable while the gate is closed.
    pause = self.body.index("if not onroad:")
    self.assertIn("continue", self.body[pause:infer_call])
    self.assertLess(pause, infer_call)

  def test_offroad_pauses_and_slows_the_poll(self):
    pause = self.body.index("if not onroad:")
    self.assertIn("time.sleep(OFFROAD_POLL_INTERVAL_SECONDS)", self.body[pause:])
    # 5 ms cadence is for onroad; offroad the 50 ms backoff still resumes within a frame.
    self.assertIn("OFFROAD_POLL_INTERVAL_SECONDS = 0.05", VASM_SOURCE)

  def test_offroad_clears_the_stale_lane_result(self):
    # carStateSP.xiaoge*LaneLine stays applied for XIAOGE_LANE_TIMEOUT_NS (4 s) after the
    # last valid payload, so pausing without clearing would hold a stale lane for 4 s.
    pause = self.body.index("if not onroad:")
    resume = self.body.index("if not onroad:\n          if lane_publish_clear")
    block = self.body[pause:resume]
    self.assertIn("dict(LANE_RESULT_INVALID", block)
    self.assertIn('lane_publish_clear = bool(self.lane_result["valid"])', block)
    self.assertIn("publish_vision_result()", self.body[pause:])


class TestBlindspotThread(unittest.TestCase):
  def setUp(self):
    self.body = function_body(VASM_SOURCE, "run_camera")

  def test_gate_is_consulted_before_the_onnx_model(self):
    gate_call = self.body.index("_update_onroad_gate()")
    infer_call = self.body.index("self.inference.update(")
    self.assertLess(gate_call, infer_call, "the gate must run before the BSD ONNX call")
    # offroad the BSD gate is forced closed, so the inference below cannot run.
    self.assertIn('gate_active, side = False, ""', self.body)
    pause = self.body.index("if not gate_active:")
    self.assertIn("time.sleep(OFFROAD_POLL_INTERVAL_SECONDS)", self.body[pause:])

  def test_speed_gate_survives_onroad(self):
    # Plan A only adds a precondition: onroad still goes through the 30-120 km/h gate.
    self.assertIn("gate_active, side = self._update_vasm_gate()", self.body)
    self.assertIn("VASM_MIN_SPEED_MPS", VASM_SOURCE)
    self.assertIn("VASM_MAX_SPEED_MPS", VASM_SOURCE)

  def test_offroad_reports_the_reason_in_the_bsd_gate(self):
    # /status must not keep showing the last onroad gate verdict while parked.
    pause = self.body.index("if not gate_active:")
    block = self.body[pause:self.body.index("publish_clear = self.vasm_result")]
    self.assertIn('self.vasm_gate = {"active": False, "side": "", "reason": offroad_reason', block)


if __name__ == "__main__":
  unittest.main()
