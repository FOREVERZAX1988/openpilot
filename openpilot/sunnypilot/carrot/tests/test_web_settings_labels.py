"""
Copyright (c) 2026-, mouxan

Tests for the carrot web panel's setting controls: the Chinese labels that mirror the
on-device UI, the fallback to the raw param key, and the auto-scanned Blendful switch.
"""
import unittest

from openpilot.sunnypilot.carrot import web_settings as ws
from openpilot.sunnypilot.carrot.web_settings import T_BOOL, T_INT, render_control


class TestParamLabels(unittest.TestCase):
  def test_blendful_has_a_chinese_label(self):
    # the new sunnypilot lateral policy must read in Chinese like the on-device UI
    labels = ws.param_labels()
    title, descr = labels["Blendful"]
    self.assertEqual(title, "融合车道（测试版）")
    self.assertIn("车道中央", descr)

  def test_rendered_control_shows_title_key_and_description(self):
    labels = ws.param_labels()
    html = render_control("Blendful", T_BOOL, 0, labels)
    self.assertIn("融合车道（测试版）", html)
    self.assertIn(">Blendful<", html)          # raw key still shown for traceability
    self.assertIn('name="p[Blendful]"', html)  # form writes the declared key
    self.assertIn('type="checkbox"', html)

  def test_unlabelled_key_falls_back_to_the_raw_name(self):
    html = render_control("SomeRawKey", T_INT, 5, {"Blendful": ("t", "d")})
    self.assertIn(">SomeRawKey<", html)
    self.assertNotIn('class="t"', html)

  def test_blendful_no_longer_auto_scanned_after_three_state_button(self):
    # 2026-11-01 zp chill rework: Lane Center Assist became a three-state button
    # (Off / On / Debug UI) whose callback writes Blendful + BlendfulReadout, so the page
    # source no longer declares `param="Blendful"` and the web panel's auto-scan has
    # nothing to pick up. The on-device button (and sunnylink) are the way to set it now.
    # Pinning the trade-off so a silent change shows up here rather than being noticed
    # only when someone looks for the row in the web panel.
    pages = ws.scan_ui_pages(ws.ui_settings_dir())
    self.assertNotIn("Blendful", pages.get("models", []))


if __name__ == "__main__":
  unittest.main()
