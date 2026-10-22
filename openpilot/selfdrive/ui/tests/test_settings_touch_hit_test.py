"""Regression test for the "the tap opened the wrong settings panel" report.

The settings sidebar hit tested stored rows (``panel_info.button_rect`` written while
drawing). The sidebar is a Scroller, and Scroller deliberately skips the render of rows
outside its viewport, so those rects kept the position the row had the last time it was
visible; a tap on a visible row could match the stale rect of a row that had already
scrolled off, and the parent took the first match in panel order, i.e. it opened a
settings panel that was not on the list. Every row now clicks itself.

The test runs without a window/GPU: the widget event path is fed by hand through
gui_app's mouse event list.
"""
import pathlib
import unittest
from types import SimpleNamespace

import pyray as rl

from openpilot.selfdrive.ui.sunnypilot.layouts.settings import settings as sp_settings
from openpilot.system.ui.lib.application import gui_app, MouseEvent, MousePos

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
