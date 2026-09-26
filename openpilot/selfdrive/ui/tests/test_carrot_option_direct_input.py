"""Guard tests for direct numeric input on Carrot Tuning option controls.

The +/- buttons step a value by `value_change_step`, which is slow for wide ranges
(e.g. 0..300 in steps of 5) and awkward for enum-like indices.  Tapping the value box
now opens the on-screen keypad so the value can be typed (user request, 2026-09-19).

These tests pin the parsing/clamping contract of that path without needing a GPU/window.
"""
import unittest
from types import SimpleNamespace

from openpilot.system.ui.sunnypilot.widgets import option_control as oc
from openpilot.system.ui.widgets import DialogResult


class _FakeParams:
  def __init__(self):
    self.store = {}

  def get(self, key, default=None, **kwargs):
    return self.store.get(key, default)

  def put(self, key, value):
    self.store[key] = value


class TestCarrotOptionDirectInput(unittest.TestCase):
  def setUp(self):
    self._orig_params = oc.unified_params
    self._orig_gui = oc.gui_app
    self.params = _FakeParams()
    oc.unified_params = self.params
    oc.gui_app = SimpleNamespace(font=lambda *a, **k: None)

  def tearDown(self):
    oc.unified_params = self._orig_params
    oc.gui_app = self._orig_gui

  def _make(self, **kwargs):
    kwargs.setdefault("param", "TestParam")
    kwargs.setdefault("min_value", 0)
    kwargs.setdefault("max_value", 300)
    return oc.OptionControlSP(**kwargs)

  def test_typed_integer_is_written(self):
    ctrl = self._make()
    ctrl._on_input_result(DialogResult.CONFIRM, "123")
    self.assertEqual(ctrl.get_value(), 123)
    self.assertEqual(self.params.store["TestParam"], 123)

  def test_out_of_range_is_clamped_to_max(self):
    ctrl = self._make()
    ctrl._on_input_result(DialogResult.CONFIRM, "999")
    self.assertEqual(ctrl.get_value(), 300)

  def test_negative_is_clamped_to_min(self):
    ctrl = self._make()
    ctrl._on_input_result(DialogResult.CONFIRM, "-5")
    self.assertEqual(ctrl.get_value(), 0)

  def test_non_numeric_entry_leaves_value_untouched(self):
    ctrl = self._make()
    ctrl.current_value = 42
    ctrl._on_input_result(DialogResult.CONFIRM, "abc")
    self.assertEqual(ctrl.get_value(), 42)
    self.assertNotIn("TestParam", self.params.store)

  def test_cancel_does_not_write(self):
    ctrl = self._make()
    ctrl.current_value = 42
    ctrl._on_input_result(DialogResult.CANCEL, "99")
    self.assertEqual(ctrl.get_value(), 42)
    self.assertNotIn("TestParam", self.params.store)

  def test_float_scaling_round_trips(self):
    ctrl = self._make(min_value=0, max_value=500, use_float_scaling=True)
    ctrl._on_input_result(DialogResult.CONFIRM, "1.25")
    self.assertEqual(ctrl.get_value(), 125)
    self.assertAlmostEqual(self.params.store["TestParam"], 1.25)

  def test_value_map_reverse_lookup(self):
    ctrl = self._make(max_value=2, value_map={0: 0, 1: 10, 2: 20})
    ctrl._on_input_result(DialogResult.CONFIRM, "20")
    self.assertEqual(ctrl.get_value(), 2)
    self.assertEqual(self.params.store["TestParam"], 20)

  def test_value_map_unknown_value_is_ignored(self):
    ctrl = self._make(max_value=2, value_map={0: 0, 1: 10, 2: 20})
    ctrl._on_input_result(DialogResult.CONFIRM, "15")
    self.assertEqual(ctrl.get_value(), 0)
    self.assertNotIn("TestParam", self.params.store)

  def test_prefill_shows_editable_number(self):
    ctrl = self._make(min_value=0, max_value=500, use_float_scaling=True)
    ctrl.current_value = 125
    self.assertEqual(ctrl._editable_text(), "1.25")

  def test_tapping_value_box_opens_keypad(self):
    ctrl = self._make()
    ctrl.label_rect = oc.rl.Rectangle(10, 10, 100, 100)
    opened = []
    ctrl._open_input_dialog = lambda: opened.append(True)  # keep pyray/window out of the test
    import pyray as rl
    ctrl._handle_mouse_release(rl.Vector2(50, 50))
    self.assertEqual(opened, [True])

  def test_tapping_outside_value_box_does_not_open_keypad(self):
    ctrl = self._make()
    ctrl.label_rect = oc.rl.Rectangle(10, 10, 100, 100)
    opened = []
    ctrl._open_input_dialog = lambda: opened.append(True)
    import pyray as rl
    ctrl._handle_mouse_release(rl.Vector2(2000, 2000))
    self.assertEqual(opened, [])


if __name__ == "__main__":
  unittest.main()
