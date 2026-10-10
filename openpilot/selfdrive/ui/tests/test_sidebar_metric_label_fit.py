"""Regression tests for the metrics-sidebar label centering (openpilot/selfdrive/ui/layouts/sidebar.py).

Two things made the "SUNNYLINK" label of the left sidebar hug the card's left border instead of
staying centered:

1. ``measure_text_cached`` scaled *every* string by FALLBACK_FONT_SCALE in a CJK UI, while the
   patched ``rl.draw_text_ex`` (application._patch_text_functions) only applies that scale to
   text that is drawn with a Noto fallback font. Latin labels were measured 25% too wide, and
   centering a line on a width it does not have moves it (FALLBACK_FONT_SCALE - 1) / 2 of its
   width toward the start edge.
2. Even measured correctly, "SUNNYLINK" is wider than the metric text area at FONT_SIZE, so it
   has to be shrunk to fit instead of being centered on a width it cannot occupy.

Nothing here needs a display or a font atlas.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT))

from openpilot.common.test import OpenpilotTestCase
from openpilot.selfdrive.ui.layouts.sidebar import (FONT_SIZE, METRIC_TEXT_GAP,
                                                    METRIC_TEXT_INSET, METRIC_WIDTH,
                                                    fit_metric_line_width)
from openpilot.system.ui.lib import text_measure
from openpilot.system.ui.lib.application import FALLBACK_FONT_SCALE, FONT_SCALE
from openpilot.system.ui.lib.multilang import multilang

# The metric text area: everything right of the colored bar.
TEXT_AREA_W = METRIC_WIDTH - METRIC_TEXT_INSET
METRIC_BOX_BORDER = 2  # drawn 2px inside the 240px card

# Widths of the sidebar labels in the shipped Inter-SemiBold at FONT_SIZE (measured offline;
# the assertions are geometric, only the ordering matters).
SUNNYLINK_W = 238.9  # the longest label: wider than TEXT_AREA_W (218)
TEMP_W = 115.5


class SidebarMetricLabelFitTest(OpenpilotTestCase):
  def test_short_line_keeps_font_size(self):
    self.assertEqual(fit_metric_line_width(TEMP_W, TEXT_AREA_W), FONT_SIZE)

  def test_long_line_is_shrunk_until_it_fits_with_a_gap(self):
    self.assertGreater(SUNNYLINK_W, TEXT_AREA_W, "fixture: SUNNYLINK must overflow the area")
    font_size = fit_metric_line_width(SUNNYLINK_W, TEXT_AREA_W)
    self.assertLess(font_size, FONT_SIZE)
    drawn_w = SUNNYLINK_W * font_size / FONT_SIZE
    self.assertAlmostEqual(drawn_w, TEXT_AREA_W - METRIC_TEXT_GAP, places=6)

  def test_line_widths_from_the_area_to_far_wider_stay_inside_the_card(self):
    bar_right = METRIC_TEXT_INSET                  # the colored bar ends where the text starts
    right_border = METRIC_WIDTH - METRIC_BOX_BORDER
    for text_w in (TEMP_W, TEXT_AREA_W - METRIC_TEXT_GAP, TEXT_AREA_W, SUNNYLINK_W, 400.0):
      with self.subTest(text_w=text_w):
        font_size = fit_metric_line_width(text_w, TEXT_AREA_W)
        drawn_w = text_w * font_size / FONT_SIZE
        left = METRIC_TEXT_INSET + (TEXT_AREA_W - drawn_w) / 2
        self.assertGreaterEqual(left, bar_right, "label slides under the colored bar")
        self.assertLessEqual(left + drawn_w, right_border, "label overflows the card border")
        self.assertAlmostEqual(left + drawn_w / 2, METRIC_TEXT_INSET + TEXT_AREA_W / 2, places=6,
                              msg="label is not centered in the text area")


class TextMeasureScaleTest(OpenpilotTestCase):
  """measure_text_cached must use the same scale rl.draw_text_ex will apply to the string."""

  def setUp(self):
    self._saved_language = multilang.language

  def tearDown(self):
    multilang._language = self._saved_language  # no setter; change_language() writes Params
    text_measure.clear_cache()

  def test_latin_is_not_scaled_by_the_fallback_in_a_cjk_ui(self):
    multilang._language = "zh-CHS"
    text_measure.clear_cache()
    self.assertTrue(multilang.requires_font_fallback())
    # Inter carries these glyphs, so they are drawn at FONT_SCALE alone; measuring them with
    # the fallback scale is what pushed every centered Latin label toward the start edge.
    for text in ("SUNNYLINK", "TEMP", "ONLINE", "Українська"):
      self.assertAlmostEqual(text_measure.text_scale(text), FONT_SCALE, msg=text)

  def test_cjk_text_is_still_scaled_by_the_fallback(self):
    multilang._language = "zh-CHS"
    text_measure.clear_cache()
    self.assertAlmostEqual(text_measure.text_scale("温度"), FONT_SCALE * FALLBACK_FONT_SCALE)

  def test_english_ui_is_unaffected(self):
    multilang._language = "en"
    text_measure.clear_cache()
    self.assertFalse(multilang.requires_font_fallback())
    for text in ("SUNNYLINK", "温度"):
      self.assertAlmostEqual(text_measure.text_scale(text), FONT_SCALE, msg=text)


if __name__ == "__main__":
  unittest.main()
