"""Ported-but-inert features must stay on screen, off, and un-clickable.

Policy (driver's call, 2026-10-21): every upstream feature gets pulled as-is; when our
car cannot use one, the UI switch greys out and stops accepting taps instead of the
feature being deleted from the tree. That keeps the next upstream pull cheap and makes
"ported, but not usable here" self-documenting on the device.

The risk this file covers is silent rot: upstream renames a param key, or somebody adds
the switch to a page without the `enabled=` wiring, and the switch quietly starts
looking live again. Both cases fail here rather than on the road.
"""
import ast
import os
import unittest

from openpilot.sunnypilot.carrot import feature_support as fs

MACAN = "PORSCHE_MACAN_MK1"
OTHER_CAR = "TOYOTA_COROLLA_TSS2"

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
SETTINGS_DIR = os.path.join(REPO_ROOT, "selfdrive", "ui", "sunnypilot", "layouts", "settings")
TUNING_ITEMS = os.path.join(SETTINGS_DIR, "carrot_tuning_items.py")
#: Every page that renders a `param=` switch is scanned. NNFFMode's row lives on the
#: Developer page, and a page nobody scans is exactly where the `enabled=` wiring rots.
SWITCH_PAGES = (
  TUNING_ITEMS,
  os.path.join(SETTINGS_DIR, "developer.py"),
)
PARAMS_KEYS = os.path.join(REPO_ROOT, "common", "params_keys.h")


class FakeParams:
  """Just the two Params methods `enforce` uses."""

  def __init__(self, values=None):
    self.values = dict(values or {})
    self.writes = []

  def get(self, key):
    raw = self.values.get(key)
    if raw is None:
      return None
    return b"1" if raw is True else b"0" if raw is False else str(raw).encode()

  def put(self, key, value):
    self.writes.append((key, value))
    self.values[key] = value


class TestTable(unittest.TestCase):
  def test_every_row_names_a_registered_param(self):
    """A renamed key upstream must break the build, not just the switch."""
    with open(PARAMS_KEYS) as f:
      keys = f.read()
    for row in fs.UNSUPPORTED:
      self.assertIn(f'"{row.param}"', keys, f"{row.param} is in feature_support but not in params_keys.h")

  def test_every_row_has_a_reason(self):
    for row in fs.UNSUPPORTED:
      self.assertTrue(row.reason.strip(), f"{row.param} has no reason to show on screen")

  def test_rows_are_unique(self):
    seen = [row.param for row in fs.UNSUPPORTED]
    self.assertEqual(len(seen), len(set(seen)), "duplicate param in UNSUPPORTED")

  def test_our_cars_are_listed_for_every_row(self):
    """The whole point is Macan; a row that does not target this car is dead weight."""
    for row in fs.UNSUPPORTED:
      self.assertTrue(row.cars & fs.OUR_CARS, f"{row.param} does not target any of OUR_CARS")


class TestSupportDecision(unittest.TestCase):
  def test_inert_on_our_car(self):
    for row in fs.UNSUPPORTED:
      self.assertFalse(fs.is_supported(row.param, MACAN), row.param)
      self.assertIsNotNone(fs.unsupported_row(row.param, MACAN), row.param)

  def test_live_on_other_cars(self):
    for row in fs.UNSUPPORTED:
      self.assertTrue(fs.is_supported(row.param, OTHER_CAR), row.param)

  def test_unlisted_param_is_live_everywhere(self):
    self.assertTrue(fs.is_supported("SomeParamWeNeverListed", MACAN))
    self.assertIsNone(fs.row("SomeParamWeNeverListed"))

  def test_unknown_platform_does_not_disable_anything(self):
    """No CarParams yet must not read as "unsupported" -- that would grey out the world."""
    for row in fs.UNSUPPORTED:
      self.assertTrue(fs.is_supported(row.param, None))

  def test_ui_enabled_returns_a_live_callable(self):
    row = fs.UNSUPPORTED[0]
    off = fs.ui_enabled(row.param, MACAN)
    on = fs.ui_enabled(row.param, OTHER_CAR)
    self.assertTrue(callable(off))
    self.assertFalse(off())
    self.assertTrue(on())

  def test_describe_appends_reason_only_when_inert(self):
    row = fs.UNSUPPORTED[0]
    grayed = fs.describe(row.param, "base", MACAN)
    self.assertTrue(grayed.startswith("base"))
    self.assertIn(row.reason, grayed)
    self.assertEqual(fs.describe(row.param, "base", OTHER_CAR), "base")
    self.assertEqual(fs.describe("UnlistedParam", "base", MACAN), "base")


class TestEnforce(unittest.TestCase):
  def test_forces_inert_key_off(self):
    row = fs.UNSUPPORTED[0]
    p = FakeParams({row.param: True})
    changed = fs.enforce(p, MACAN)
    self.assertIn(row.param, changed)
    self.assertEqual(p.values[row.param], row.off)

  def test_is_idempotent(self):
    row = fs.UNSUPPORTED[0]
    p = FakeParams({row.param: True})
    fs.enforce(p, MACAN)
    p.writes.clear()
    self.assertEqual(fs.enforce(p, MACAN), [])
    self.assertEqual(p.writes, [])

  def test_no_write_when_already_off(self):
    row = fs.UNSUPPORTED[0]
    p = FakeParams({row.param: False})
    self.assertEqual(fs.enforce(p, MACAN), [])
    self.assertEqual(p.writes, [])

  def test_touches_nothing_on_other_cars(self):
    for row in fs.UNSUPPORTED:
      p = FakeParams({row.param: True})
      self.assertEqual(fs.enforce(p, OTHER_CAR), [])
      self.assertEqual(p.writes, [])

  def test_missing_value_is_left_alone(self):
    """Absent key = registered default, which is already off for these switches."""
    for row in fs.UNSUPPORTED:
      p = FakeParams()
      self.assertEqual(fs.enforce(p, MACAN), [])
      self.assertEqual(p.writes, [])


class TestUiWiring(unittest.TestCase):
  """Every table row that has a switch on a settings page must be wired as disabled.

  Parsed, not grepped, and keyed on the `param=` keyword rather than on the factory
  function name -- so renaming a `*_item_sp` helper does not silently disable this
  check, while dropping the `enabled=` wiring does fail it.
  """

  def _switch_calls(self):
    for page in SWITCH_PAGES:
      with open(page) as f:
        tree = ast.parse(f.read(), filename=page)
      for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
          continue
        param_kw = next((kw for kw in node.keywords if kw.arg == "param"), None)
        if param_kw is None or not isinstance(param_kw.value, ast.Constant):
          continue
        if not isinstance(param_kw.value.value, str):
          continue
        yield param_kw.value.value, node

  def test_table_rows_found_in_the_page_are_gated(self):
    rows = {row.param: row for row in fs.UNSUPPORTED}
    gated = set()
    for param, call in self._switch_calls():
      if param not in rows:
        continue
      enabled_kw = next((kw for kw in call.keywords if kw.arg == "enabled"), None)
      self.assertIsNotNone(enabled_kw, f"{param} has a switch on a settings page but no enabled= wiring")
      fn = enabled_kw.value
      self.assertIsInstance(fn, ast.Call, f"{param}: enabled= must be feature_support.ui_enabled(...)")
      self.assertIsInstance(fn.func, ast.Attribute, f"{param}: enabled= must be feature_support.ui_enabled(...)")
      self.assertEqual(fn.func.attr, "ui_enabled", f"{param}: enabled= must call ui_enabled()")
      args = [a.value for a in fn.args if isinstance(a, ast.Constant)]
      self.assertIn(param, args, f"{param}: ui_enabled() must be called with its own key")
      gated.add(param)
    # Rows marked on_screen=False have no switch; everything else must be gated above.
    expected = {r.param for r in rows.values() if r.on_screen}
    self.assertEqual(gated, expected, f"gated: {sorted(gated)}, expected: {sorted(expected)}")


if __name__ == "__main__":
  unittest.main()
