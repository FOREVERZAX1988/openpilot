"""The impossible-limit threshold got a row, so the row gets a guard.

`VisionSpeedLimitLowLimitThreshold` was the last control-path parameter with no
control anywhere on the device (audit_ui_reach.py: 24 switches, 1 unreachable -
the table said so for a full round). The row that closed it is one
`option_item_sp` call, and every way that call can go wrong is silent on a
screenshot:

  * dropping `use_float_scaling` writes an int into a FLOAT key. The scaling
    contract test catches that one, but the row still renders either way;
  * a wrong conversion factor prints a plausible-but-wrong km/h number, and
    3.6 vs 0.36 is not something a driver can tell by looking at the screen;
  * losing the `enabled` gate leaves a row that looks live while the value it
    writes is never read - `speed_limit_resolver.py` only reads the threshold
    when the filter toggle is on;
  * the row disappearing puts the key back on curl-only, which is the state
    this whole audit exists to prevent.

Plain `unittest.TestCase` and nothing but `ast` + `params_keys.h` on purpose:
the UI package cannot be imported on a PC (it pulls PIL through the text
measurer and `fcntl` through Params), and a test that only runs on the device is
a test that does not run while the mistake is being made.
"""
import ast
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
ITEMS = REPO_ROOT / "openpilot" / "selfdrive" / "ui" / "sunnypilot" / "layouts" / "settings" / "carrot_tuning_items.py"
PARAMS_KEYS = REPO_ROOT / "openpilot" / "common" / "params_keys.h"

KEY = "VisionSpeedLimitLowLimitThreshold"
GATE = "VisionSpeedLimitLowLimitFilter"

# {"Key", {PERSISTENT | BACKUP, FLOAT, "0.0"}},  // ...
_KEY_ENTRY = re.compile(r'^\s*\{[ ]*"([A-Za-z0-9_]+)"[ ]*,[ ]*\{[ ]*[A-Z_ |]+,[ ]*(BOOL|INT|FLOAT|STRING|JSON|BYTES)')


def declared_type(key: str) -> str | None:
  for line in PARAMS_KEYS.read_text(encoding="utf-8").splitlines():
    match = _KEY_ENTRY.match(line)
    if match and match.group(1) == key:
      return match.group(2)
  return None


def row_kwargs() -> dict[str, ast.expr]:
  """Keyword arguments of the one `option_item_sp(...)` call that targets KEY."""
  tree = ast.parse(ITEMS.read_text(encoding="utf-8"))
  found = []
  for node in ast.walk(tree):
    if not isinstance(node, ast.Call):
      continue
    name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
    if name != "option_item_sp":
      continue
    kwargs = {kw.arg: kw.value for kw in node.keywords if kw.arg}
    param = kwargs.get("param")
    if isinstance(param, ast.Constant) and param.value == KEY:
      found.append(kwargs)
  assert len(found) == 1, f"expected exactly one row for {KEY} in {ITEMS.name}, found {len(found)}"
  return found[0]


def label_source(kwargs: dict[str, ast.expr]) -> str:
  return ast.unparse(kwargs["label_callback"])


def evaluate_label(kwargs: dict[str, ast.expr]):
  """The label lambda, compiled on its own - it closes over nothing."""
  lambda_node = kwargs["label_callback"]
  assert isinstance(lambda_node, ast.Lambda), "label_callback should stay a bare lambda"
  return eval(compile(ast.Expression(body=lambda_node), "<label_callback>", "eval"), {})


class TestVisionLimitThresholdRow(unittest.TestCase):
  def test_the_key_is_float_so_scaling_is_legal(self):
    """`option_item_sp(use_float_scaling=True)` stores value/100, so the key must be FLOAT."""
    self.assertEqual("FLOAT", declared_type(KEY),
                     f"{KEY} is no longer declared FLOAT, so the scaled row would write the wrong type")

  def test_the_row_asks_the_control_to_scale(self):
    scaling = row_kwargs().get("use_float_scaling")
    self.assertIsInstance(scaling, ast.Constant,
                          "the row stopped asking for use_float_scaling; on a FLOAT key the control would then write 140 instead of 1.40 m/s")
    self.assertIs(scaling.value, True)

  def test_the_label_shows_km_h_next_to_m_s(self):
    label = evaluate_label(row_kwargs())
    self.assertEqual("0.0 m/s (0 km/h)", label(0))
    self.assertEqual("1.4 m/s (5 km/h)", label(140))       # 1.4 m/s
    self.assertEqual("2.8 m/s (10 km/h)", label(278))      # 2.8 m/s
    self.assertEqual("10.0 m/s (36 km/h)", label(1000))    # the row's maximum

  def test_the_km_h_half_uses_the_real_factor(self):
    """Pin the factor itself: 0.036 = 3.6/100, i.e. the control's internal m/s*100 to km/h."""
    source = label_source(row_kwargs())
    self.assertIn("0.036", source,
                  f"the km/h conversion changed; the control's internal unit is m/s*100, so km/h = v * 0.036 (got: {source})")

  def test_the_range_covers_a_useful_misread_but_not_a_real_limit(self):
    kwargs = row_kwargs()
    low = ast.literal_eval(kwargs["min_value"])
    high = ast.literal_eval(kwargs["max_value"])
    step = ast.literal_eval(kwargs["value_change_step"])
    self.assertEqual(0, low)
    self.assertGreaterEqual(high / 100.0, 5.0, "the ceiling must reach at least 18 km/h")
    self.assertLessEqual(high / 100.0, 20.0, "a ceiling above 72 km/h would drop real limits")
    self.assertGreater(step, 0)
    self.assertLess(step, high)

  def test_the_row_stays_gated_by_the_filter_toggle(self):
    kwargs = row_kwargs()
    self.assertIn("enabled", kwargs, "the row lost its enabled= gate")
    gate_msg = f"the row must stay greyed out until {GATE} is on: the resolver reads the threshold only on that path"
    self.assertIn(GATE, ast.unparse(kwargs["enabled"]), gate_msg)


if __name__ == "__main__":
  unittest.main()
