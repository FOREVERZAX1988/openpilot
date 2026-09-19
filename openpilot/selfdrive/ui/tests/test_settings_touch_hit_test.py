"""Regression tests for the "the tap did not do what my finger did" reports.

Two independent bugs, both about resolving a touch against the wrong thing:

1. Carrot Tuning's top tab strip (Settings -> Navigation -> Carrot Tuning) read its press
   from the render loop with rl.is_mouse_button_pressed(). raylib clears that edge on the
   next poll_input_events(), the touch sampler thread polls at 140 Hz
   (application.MOUSE_THREAD_RATE) and the UI only renders ~60 frames/s, so a tap was
   usually consumed before a frame ever looked at the strip - it felt dead to the touch,
   and when a frame did catch the edge the finger had often moved on, so the neighbouring
   tab got selected. The strip now consumes gui_app.mouse_events like every other widget.

2. The settings sidebar hit tested stored rows (panel_info.button_rect written while
   drawing). The sidebar is a Scroller, and Scroller deliberately skips the render of rows
   outside its viewport, so those rects kept the position the row had the last time it was
   visible; a tap on a visible row could match the stale rect of a row that had already
   scrolled off, and the parent took the first match in panel order, i.e. it opened a
   settings panel that was not on the list. Every row now clicks itself.

Both tests run without a window/GPU: the geometry helpers are pure and the widget event
path is fed by hand through gui_app's mouse event list.
"""
import pathlib
import unittest
from types import SimpleNamespace

import pyray as rl

from openpilot.selfdrive.ui.sunnypilot.layouts.settings import carrot_tuning as ct
from openpilot.selfdrive.ui.sunnypilot.layouts.settings import settings as sp_settings
from openpilot.system.ui.lib.application import gui_app, MouseEvent, MousePos
from openpilot.system.ui.widgets import Widget

STRIP = rl.Rectangle(100.0, 12.0, 1800.0, 96.0)
TAB_W = STRIP.width / ct.CarrotTuningLayout.TAB_COUNT


def _press(x, y, slot=0):
  return MouseEvent(MousePos(x, y), slot, True, False, True, 0.0)


def _release(x, y, slot=0):
  return MouseEvent(MousePos(x, y), slot, False, True, False, 0.01)


class _FakeParent:
  """Stands in for SettingsLayoutSP, recording which panel got opened."""

  def __init__(self):
    self.opened: list = []

  def set_current_panel(self, panel_type):
    self.opened.append(panel_type)


class _TouchTest(unittest.TestCase):
  """Feeds widget event lists by hand instead of waiting for real touches."""

  def setUp(self):
    self._saved = gui_app._mouse_events

  def tearDown(self):
    gui_app._mouse_events = self._saved

  def _feed(self, events, *widgets):
    # gui_app.mouse_events is what every rendered widget drains each frame; handing the
    # same list to several widgets is what happens when they overlap on screen.
    gui_app._mouse_events = list(events)
    for widget in widgets:
      widget._process_mouse_events()


class TestCarrotTabStripHitTest(_TouchTest):
  def _make_layout(self):
    # Widget.__init__ only needs the geometry bookkeeping, so the layout can be built
    # without its panels/fonts (which would need a window).
    layout = ct.CarrotTuningLayout.__new__(ct.CarrotTuningLayout)
    Widget.__init__(layout)
    layout._current_tab = ct.TabType.START
    layout._tab_strip_rect = STRIP
    # a widget only sees events that start inside its own rect (Widget._hit_rect)
    layout.set_rect(rl.Rectangle(0.0, 0.0, 2160.0, 1080.0))
    return layout

  def test_every_tab_owns_one_ninth_of_the_strip(self):
    for index in range(ct.CarrotTuningLayout.TAB_COUNT):
      centre_x = STRIP.x + (index + 0.5) * TAB_W
      with self.subTest(index=index):
        self.assertEqual(ct.CarrotTuningLayout.tab_index_at(MousePos(centre_x, STRIP.y + 48), STRIP), index)

  def test_points_outside_the_strip_have_no_tab(self):
    for pos in (MousePos(STRIP.x - 1, STRIP.y + 48),                  # left of the strip
                MousePos(STRIP.x + STRIP.width + 1, STRIP.y + 48),    # right of the strip
                MousePos(STRIP.x + 10, STRIP.y - 1),                  # above it
                MousePos(STRIP.x + 10, STRIP.y + STRIP.height + 1)):  # below it (the list)
      with self.subTest(pos=pos):
        self.assertIsNone(ct.CarrotTuningLayout.tab_index_at(pos, STRIP))

  def test_a_press_on_the_strip_switches_to_that_tab(self):
    """The bug this fixes: taps reached the strip only if a frame happened to see the edge."""
    layout = self._make_layout()
    self._feed((_press(STRIP.x + 5.5 * TAB_W, STRIP.y + 48),), layout)
    self.assertEqual(layout._current_tab, ct.TabType(5))

  def test_a_press_below_the_strip_does_not_switch_tabs(self):
    layout = self._make_layout()
    self._feed((_press(STRIP.x + 5.5 * TAB_W, STRIP.y + STRIP.height + 100),), layout)
    self.assertEqual(layout._current_tab, ct.TabType.START)

  def test_press_position_decides_the_tab_not_where_the_finger_ends_up(self):
    layout = self._make_layout()
    self._feed((_press(STRIP.x + 0.5 * TAB_W, STRIP.y + 48),), layout)
    self._feed((_release(STRIP.x + 8.5 * TAB_W, STRIP.y + 48),), layout)
    self.assertEqual(layout._current_tab, ct.TabType.START)

  def test_strip_does_not_poll_raylib_for_presses(self):
    """Guards against reintroducing the racy in-render press check."""
    src = pathlib.Path(ct.__file__).read_text(encoding="utf-8")
    self.assertNotIn("rl.is_mouse_button_pressed(", src)
    self.assertIn("gui_app.mouse_events", src)  # via the framework event path
    self.assertIn("def _handle_mouse_press(self, mouse_pos", src)


class TestSettingsSidebarHitTest(_TouchTest):
  def _make_row(self, rect, parent, panel_type):
    row = sp_settings.NavButton(parent, panel_type, SimpleNamespace(name="panel", icon=""))
    row.set_rect(rect)
    return row

  def test_a_tap_on_a_sidebar_row_opens_that_panel(self):
    parent = _FakeParent()
    row = self._make_row(rl.Rectangle(0, 110, 400, 110), parent, 7)
    self._feed((_press(200, 165),), row)
    self._feed((_release(200, 165),), row)
    self.assertEqual(parent.opened, [7])

  def test_a_tap_that_drifts_onto_another_row_opens_nothing(self):
    """A release must not be able to pick a panel the press never started on."""
    parent = _FakeParent()
    above = self._make_row(rl.Rectangle(0, 0, 400, 110), parent, 3)
    below = self._make_row(rl.Rectangle(0, 110, 400, 110), parent, 4)
    self._feed((_press(200, 55),), above, below)
    self._feed((_release(200, 165),), above, below)
    self.assertEqual(parent.opened, [])

  def test_sidebar_does_not_hit_test_stored_row_rects(self):
    """The stale-rect scan is what opened panels that were not on screen."""
    src = pathlib.Path(sp_settings.__file__).read_text(encoding="utf-8")
    self.assertIn("self.set_click_callback(self._activate)", src)
    self.assertNotIn("panel_info.button_rect = rect", src)
    release_handler = src.split("def _handle_mouse_release")[1].split("def ")[0]
    self.assertNotIn("button_rect", release_handler)


if __name__ == '__main__':
  unittest.main()
