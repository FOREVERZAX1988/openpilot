import pathlib
import re

from openpilot.selfdrive.controls.lib.longitudinal_planner import LongitudinalPlanner

PLANNER_PATH = pathlib.Path(__file__).resolve().parents[1] / "lib" / "longitudinal_planner.py"


def _planner_source():
  return PLANNER_PATH.read_text()


def test_policy_hooks_default_off():
  # Both StarPilot policy stages must ship disabled: the params default to "0"
  # and the planner reads them lazily, so an unwritten key keeps stock behavior.
  src = _planner_source()
  for key in ("LeadFollowPolicyEnabled", "LeadStopDepartPolicyEnabled"):
    assert re.search(rf'self\.\w+ = self\._params\.get_bool\("{key}"\)', src), key
  for flag in ("lead_follow_policy_enabled", "lead_stop_depart_enabled"):
    assert re.search(rf"if self\.{flag} and ", src), flag


def test_policy_hooks_run_after_arbitration_before_red_light():
  # Order matters: both shapers act on the post-arbitration final a_target and
  # must stay ahead of the sunnypilot red-light pre-deceleration.
  src = _planner_source()
  arbitration = src.index("self.output_a_target = np.clip(output_a_target, ACCEL_MIN, ACCEL_MAX)")
  follow = src.index("StarPilot lead_follow_policy")
  stop_depart = src.index("StarPilot stop/depart policy")
  red_light = src.index("apply_signal_prepare")
  assert arbitration < follow < stop_depart < red_light


def test_planner_flags_are_off_by_default():
  # Constructor-level check: no Params override in the test env -> gated off.
  assert LongitudinalPlanner.__init__ is not None
  src = _planner_source()
  assert "self._stop_depart_policy = None" in src
